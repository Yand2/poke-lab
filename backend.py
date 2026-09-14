from urllib.parse import quote
"""Local API for Poke. Run with uvicorn backend:app --port 8000."""
import json
import os
import sqlite3
import uuid
import tomllib
from concurrent.futures import ThreadPoolExecutor
from llm_client import request_json
from diagnosis import profiles_for, synthesize, report_sections
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parent
_config_stamp = None
_file_values = {}
def load_config():
    global _config_stamp
    config_path = ROOT / 'api_config.toml'
    stamp = config_path.stat().st_mtime_ns if config_path.exists() else None
    if stamp == _config_stamp:
        return
    if config_path.exists():
        config = tomllib.loads(config_path.read_text(encoding='utf-8-sig')).get('llm', {})
        for key, env in [('api_key','LLM_API_KEY'),('model','LLM_MODEL'),('base_url','LLM_BASE_URL')]:
            value = str(config.get(key,'')).strip()
            if not os.getenv(env) or os.getenv(env) == _file_values.get(env):
                if value:
                    os.environ[env] = value
                else:
                    os.environ.pop(env, None)
                _file_values[env] = value
        _config_stamp = stamp

load_config()
DB = Path(os.getenv('POKE_DB', str(ROOT / 'data' / 'poke.sqlite3')))
PERSONAS = [
    ('R1', '尝鲜者', '创新体验', '概念与现有方案有何实质差异？'),
    ('R2', '保守用户', '习惯与迁移', '放弃现有做法，需要付出什么代价？'),
    ('R3', '价格敏感者', '成本与收益', '我为什么要为它付费？'),
    ('R4', '信任怀疑者', '风险与信任', '有什么证据让我放心使用？'),
    ('R5', '专业用户', '质量与可控性', '关键任务失败后，能否检查和恢复？'),
]

def connect():
    from database import connect as open_db
    return open_db(DB)

def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, mode TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS chat_turns (id TEXT PRIMARY KEY, conversation_id TEXT REFERENCES conversations(id), message TEXT, status TEXT, structured_json TEXT, replies_json TEXT, error TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, concept TEXT, pain_point TEXT, alternative TEXT,
          status TEXT, model TEXT, mode TEXT, created_at TEXT,
          parent_id TEXT REFERENCES runs(id), variable TEXT, change_value TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs(id), persona_id TEXT,
          stage TEXT, status TEXT, result_json TEXT, UNIQUE(run_id, persona_id));
        ''')
        from accounts import init
        init(db)
        for name in ["profiles_json", "diagnosis_json", "diagnosis_error"]:
            if name not in [r[1] for r in db.execute("PRAGMA table_info(runs)")]:
                db.execute(f"ALTER TABLE runs ADD COLUMN {name} TEXT")
        db.execute("UPDATE runs SET status='failed',error='服务重启中断了分析，请重试。' WHERE status='running'")
        db.execute("UPDATE chat_turns SET status='failed',error='服务重启中断，请重试本轮。' WHERE status='running'")

@asynccontextmanager
async def lifespan(app):
    init_db()
    from planning_service import init as init_planning
    with connect() as db:init_planning(db)
    from admin_service import bootstrap_admin
    bootstrap_admin()
    yield

app = FastAPI(title='Poke the Hypothetical', version='1.0.0', lifespan=lifespan)

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    concept: str = Field(min_length=5, max_length=3000)
    pain_point: str = Field(min_length=5, max_length=2000)
    alternative: str = Field(min_length=2, max_length=2000)
    mode: Literal['live'] = 'live'

class Challenge(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    variable: Literal['price', 'onboarding', 'trust', 'quality', 'novelty']
    value: str = Field(min_length=2, max_length=1000)

class Result(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    recognition: str = Field(min_length=1, max_length=1600)
    choice: Literal['愿意尝试', '暂不采用', '需要验证']
    barrier: str = Field(min_length=1, max_length=1600)
    reason: str = Field(min_length=1, max_length=1600)
    evidence: str = Field(min_length=1, max_length=3000)
    question: str = Field(min_length=1, max_length=1600)

def get_run(run_id):
    with connect() as db:
        row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, '实验不存在')
        run = dict(row)
        tasks = db.execute('SELECT * FROM tasks WHERE run_id=? ORDER BY persona_id', (run_id,)).fetchall()
    run['results'] = [dict(json.loads(t['result_json']), persona_id=t['persona_id']) for t in tasks if t['status']=='completed']
    rank = {'暂不采用': 0, '需要验证': 1, '愿意尝试': 2}
    run['focus'] = min(run['results'], key=lambda r: (rank[r['choice']], r['persona_id']))['persona_id'] if run['results'] else None
    return run

def live_result(run, persona):
    from persona_prompts import role_prompt, PREFIX
    prompt = role_prompt(persona)
    payload = {k:run[k] for k in ['concept','pain_point','alternative','variable','change_value']}
    if run.get('structured_json'): payload['structured_context']=json.loads(run['structured_json'])
    payload['raw_text'] = run.get('raw_text')
    prompt += '用户原文是最高优先级事实依据，结构化字段不是全部信息；必须保留原文中明确的否定与范围限制，不得把已说明条件说成未知。角色画像中的额外习惯只能称为假设。变量补充覆盖原文中对应条件，其他不变。'
    payload['hypothetical_profile'] = next((p for p in json.loads(run.get('profiles_json') or '[]') if p['persona_id']==persona[0]),None)
    prompt += '画像是假设情境，不是真实用户事实；有价值的特性也可在reason中说明。'
    def valid(result):
        if not result.recognition.startswith(PREFIX) or '我' not in result.recognition:
            raise ValueError('缺少第一人称模拟角色台词')
        if any(x in result.recognition for x in ['hypothetical_profile','structured_context']):
            raise ValueError('角色台词含程序字段')
        sources=[str(run.get(k) or '') for k in ['concept','pain_point','alternative','raw_text','change_value']]
        if not any(v and v in result.evidence for v in sources):
            # A field-prefixed citation may quote only part of a longer source.
            excerpt=result.evidence.split(':',1)[-1].strip().strip('“”"')
            if len(excerpt)<2 or not any(excerpt in v for v in sources):
                raise ValueError('模型证据未引用原始输入')
    return request_json(prompt,payload,Result,model=run['model'],validate=valid)


def build_diagnosis(run_id):
    try:
        diagnosis=synthesize(get_run(run_id))
        with connect() as db:
            db.execute('UPDATE runs SET diagnosis_json=?,diagnosis_error=NULL WHERE id=?',(json.dumps(diagnosis,ensure_ascii=False),run_id))
    except Exception:
        with connect() as db:
            db.execute("UPDATE runs SET diagnosis_error='综合报告暂未生成，请重试；五角色结果已保留。' WHERE id=?",(run_id,))

def analyze(run_id):
    run = get_run(run_id)
    try:
        if not run.get('profiles_json'):
            run['profiles_json']=json.dumps(profiles_for(run,PERSONAS),ensure_ascii=False)
            with connect() as db: db.execute('UPDATE runs SET profiles_json=? WHERE id=?',(run['profiles_json'],run_id))
        done={r['persona_id'] for r in run['results']}
        def work(persona):
            result=live_result(run,persona)
            with connect() as db:
                db.execute('INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?)',
                    (str(uuid.uuid4()),run_id,persona[0],'challenge' if run['parent_id'] else 'baseline','completed',result.model_dump_json()))
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(work,[p for p in PERSONAS if p[0] not in done]))
        build_diagnosis(run_id)
        with connect() as db:
            db.execute("UPDATE runs SET status='completed',error=NULL WHERE id=?", (run_id,))
    except Exception as exc:
        message = '模型服务连接失败或超时，请检查配置并重试。' if isinstance(exc,httpx.HTTPError) else '模型返回结构或证据不符合要求，请重试。'
        with connect() as db:
            db.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (message,run_id))


def create(data, bg, parent=None, challenge=None):
    load_config()
    if data.mode=='live' and not (os.getenv('LLM_API_KEY') and os.getenv('LLM_MODEL')):
        raise HTTPException(503, '未读到完整模型配置，请在 api_config.toml 的 llm 下填写 api_key 和 model 并保存。')
    run_id = str(uuid.uuid4())
    with connect() as db:
        db.execute('INSERT INTO runs (id,concept,pain_point,alternative,status,model,mode,created_at,parent_id,variable,change_value,error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (run_id,data.concept,data.pain_point,data.alternative,'running',os.getenv('LLM_MODEL'),
             data.mode,datetime.now(timezone.utc).isoformat(),parent,challenge.variable if challenge else None,challenge.value if challenge else None,None))
    from accounts import user_id
    with connect() as db: db.execute('UPDATE runs SET owner_id=? WHERE id=?',(user_id.get(),run_id))
    if parent:
        original=get_run(parent)
        with connect() as db:
            db.execute('UPDATE runs SET raw_text=?,structured_json=?,profiles_json=? WHERE id=?',(original.get('raw_text'),original.get('structured_json'),original.get('profiles_json'),run_id))
    bg.add_task(analyze,run_id)
    return {'id':run_id,'status':'running'}

@app.get('/health')
def health():
    load_config()
    with connect() as db:
        db.execute('SELECT 1')
    return {'status':'ok','service':'poke-demo-local','live_configured':bool(os.getenv('LLM_API_KEY') and os.getenv('LLM_MODEL'))}

@app.post('/runs',status_code=202)
def post_run(data:Input,bg:BackgroundTasks):
    return create(data,bg)

@app.get('/runs')
def list_runs():
    from accounts import user_id
    with connect() as db:
        rows = db.execute("SELECT id,concept,status,mode,created_at,parent_id FROM runs WHERE mode='live' AND owner_id=? ORDER BY created_at DESC LIMIT 200",(user_id.get(),)).fetchall()
    return [dict(r) for r in rows]

@app.get('/runs/{run_id}')
def read_run(run_id:str):
    return get_run(run_id)

@app.post('/runs/{run_id}/challenge',status_code=202)
def post_challenge(run_id:str,data:Challenge,bg:BackgroundTasks):
    parent = get_run(run_id)
    if parent['status']!='completed':
        raise HTTPException(409,'请等待基线分析完成。')
    if parent['parent_id']:
        raise HTTPException(409,'请从原始基线发起挑战，避免累积多个变量。')
    return create(Input.model_construct(**{k:parent[k] for k in ['concept','pain_point','alternative','mode']}),bg,run_id,data)

@app.post('/runs/{run_id}/diagnosis',status_code=202)
def regenerate_diagnosis(run_id:str,bg:BackgroundTasks):
    r=get_run(run_id)
    if r['status']!='completed': raise HTTPException(409,'请先完成角色分析。')
    with connect() as db:
        changed=db.execute("UPDATE runs SET status='running',diagnosis_error=NULL WHERE id=? AND status='completed'",(run_id,)).rowcount
    if not changed: raise HTTPException(409,'正在生成报告。')
    def finish():
        build_diagnosis(run_id)
        with connect() as db: db.execute("UPDATE runs SET status='completed' WHERE id=?",(run_id,))
    bg.add_task(finish)
    return {'id':run_id,'status':'running'}

@app.post('/runs/{run_id}/retry',status_code=202)
def retry_run(run_id:str,bg:BackgroundTasks):
    r=get_run(run_id)
    if r['status']!='failed': raise HTTPException(409,'只有失败的实验可以重试。')
    with connect() as db:
        changed=db.execute("UPDATE runs SET status='running',error=NULL WHERE id=? AND status='failed'",(run_id,)).rowcount
    if not changed: raise HTTPException(409,'实验正在运行。')
    if r.get('raw_text') and not r.get('structured_json'):
        from experiment_text import process
        bg.add_task(process,run_id,r['raw_text'])
    else: bg.add_task(analyze,run_id)
    return {'id':run_id,'status':'running'}

@app.get('/runs/{run_id}/report',response_class=PlainTextResponse)
def report(run_id:str):
    r = get_run(run_id)
    if r['status']!='completed':
        raise HTTPException(409,'分析尚未完成，暂不能生成报告。')
    lines = ['# 创新概念可行性与Pivot（转型）诊断报告',f'实验编号：{r["id"]}',f'创建时间：{r["created_at"]}',f'模式：{r["mode"]} / {r["model"]}',
             '> AI 建议不是市场预测；结论须由真人验证。',
             '## 原始输入',f'概念：{r["concept"]}',f'痛点：{r["pain_point"]}',f'替代方案：{r["alternative"]}']
    if r.get('diagnosis_json'):
        lines += [report_sections(json.loads(r['diagnosis_json']))]
    else:
        lines += ['## 综合诊断尚未生成', '以下仅为角色结果，不能作为完整诊断报告。请在报告页面生成或重试。']
    if r.get('profiles_json'):
        lines += ['## 假设用户画像（非真实用户样本）']
        for p in json.loads(r['profiles_json']):
            lines += [f"### {p['persona_id']}",p['scenario'],'现有习惯：'+p['current_habit'],'预算约束：'+p['budget_constraint'],'采用条件：'+p['adoption_condition'],'假设：'+'；'.join(p['assumptions'])]
    if r['parent_id']:
        lines += ['## 单变量挑战',f'基线编号：{r["parent_id"]}',f'仅变更 {r["variable"]}：{r["change_value"]}']
        base = get_run(r['parent_id'])
        lines += [f'{a["persona_id"]}：{a["choice"]} → {b["choice"]}' for a,b in zip(base['results'],r['results'])]
    lines += ['## 重点角色',f'{r["focus"]}；按暂不采用、需要验证、愿意尝试排序，同级按角色编号。']
    labels={'recognition':'需求理解','choice':'采用倾向','barrier':'采用阻力','reason':'判断理由','evidence':'输入证据','question':'访谈问题'}
    for result in r['results']:
        name=next((p[1] for p in PERSONAS if p[0]==result['persona_id']),result['persona_id'])
        if result.get('recognition','').startswith('【模拟内心独白】'):
            labels={**labels,'recognition':'模拟内心独白（虚构角色）','reason':'概念交锋、选择与行动'}
        else:
            labels={**labels,'recognition':'需求理解','reason':'判断理由'}
        lines += [f'## {result["persona_id"]} {name} · {result["choice"]}']+[f'{labels.get(k,k)}：{v}' for k,v in result.items() if k!='persona_id']
    lines += ['## 真人验证计划','招募 5 位符合目标场景的受访者（探索性访谈，不代表统计结论）。',
              '请他们回顾最近一次遇到痛点的经历，展示当前替代方案，并完成一次真实任务。',
              '记录任务是否完成、付出时间、拒绝原因和原话。不要用“你会不会购买”代替行为证据。',
              '挑战实验只比较一个条件，保持任务与人群一致。若仍出现同类阻力，修订假设后再测。']
    return PlainTextResponse('\n\n'.join(lines),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':"attachment; filename=report.md; filename*=UTF-8''"+quote('创新概念可行性与Pivot（转型）诊断报告.md')})

@app.get('/runs/{run_id}/report.docx')
def word_report(run_id:str):
    from word_report import export_docx
    markdown=report(run_id).body.decode('utf-8')
    return Response(export_docx(markdown),media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':"attachment; filename=report.docx; filename*=UTF-8''"+quote('创新概念可行性与Pivot（转型）诊断报告.docx')})

from chat_service import install_chat
install_chat(app)

from accounts import install as install_accounts
install_accounts(app)
from experiment_text import install as install_experiments
install_experiments(app)

from admin_service import install_admin
install_admin(app)
from document_extract import install_documents
install_documents(app)

from planning_service import install as install_planning
install_planning(app)
