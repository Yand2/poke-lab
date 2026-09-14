"""Evidence-bounded market research and explicit cost estimates."""
import os,json,uuid
from datetime import datetime,timezone
from typing import Literal
import httpx
from fastapi import HTTPException,BackgroundTasks
from pydantic import BaseModel,Field,ConfigDict,model_validator,ValidationError
from accounts import user_id
from llm_client import request_json

class Idea(BaseModel):
    text:str=Field(min_length=2,max_length=30000)
    region:str=Field(default="中国",max_length=100)
    period:Literal['all','year','month']='year'
class CostLine(BaseModel):
    name:str=Field(min_length=1,max_length=80)
    cadence:Literal['once','monthly']
    low:float=Field(ge=0,le=1000000000,allow_inf_nan=False)
    high:float=Field(ge=0,le=1000000000,allow_inf_nan=False)
    assumption:str=Field(max_length=800)
    @model_validator(mode='after')
    def ordered(self):
        if self.high<self.low:raise ValueError('high below low')
        return self
class CostResult(BaseModel):
    summary:str=Field(max_length=2500)
    assumptions:list[str]=Field(max_length=15)
    items:list[CostLine]=Field(min_length=1,max_length=30)
    exclusions:list[str]=Field(max_length=15)
COST_PROMPT="""你是产品预算规划师，针对中国市场人民币提出落地估算。先判断方案是软件、硬件还是线下服务。给出一次性开发/设备/设计以及每月人力/云资源/模型API/营销/维护等适用明细。所有金额都是假设估算而非实时报价，明确人月、数量、规模、是否含税及外包或自建，避免重复计费。未知则列出待确认项，不假装查询了价格。low和high是该行完整数量下的总额，once是一次性，monthly是每月。"""

def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS planning_jobs(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,kind TEXT NOT NULL,input_json TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT,error TEXT,created_at TEXT)')
    db.execute("UPDATE planning_jobs SET status='failed',error='服务重启中断任务，请重新提交。' WHERE status='running'")

def work(jid,kind,idea,evidence):
    import backend as b
    try:
        b.load_config()
        result=request_json(COST_PROMPT,idea.model_dump(),CostResult,thinking='disabled').model_dump()
        with b.connect() as db:db.execute("UPDATE planning_jobs SET status='completed',result_json=? WHERE id=?",(json.dumps(result,ensure_ascii=False),jid))
    except Exception as exc:
        if isinstance(exc,httpx.TimeoutException):message='模型响应超时，成本报告未完成。请稍后重新提交。'
        elif isinstance(exc,httpx.HTTPStatusError):message='模型服务暂时拒绝请求，请稍后重试或联系管理员检查模型余额与权限。'
        elif isinstance(exc,ValidationError):message='模型没有返回完整、有效的报告格式，已自动重试仍未成功。请稍后重新提交。'
        elif isinstance(exc,ValueError):message='报告引用未通过来源校验，为避免展示无依据结论，本次分析未保存为成功。请重新提交。'
        else:message='报告处理失败，请联系管理员检查服务记录。'
        import logging
        logging.getLogger(__name__).warning('planning_failed job=%s kind=%s error_type=%s',jid,kind,type(exc).__name__)
        with b.connect() as db:db.execute("UPDATE planning_jobs SET status='failed',error=? WHERE id=?",(message,jid))

def install(app):
    import backend as b
    @app.get('/planning')
    def history():
        with b.connect() as db:return {'items':[dict(r) for r in db.execute("SELECT id,kind,status,created_at,input_json FROM planning_jobs WHERE owner_id=? AND kind='cost' ORDER BY created_at DESC LIMIT 50",(user_id.get(),))]}
    @app.get('/planning/{jid}')
    def get(jid:str):
        with b.connect() as db:r=db.execute("SELECT * FROM planning_jobs WHERE id=? AND owner_id=? AND kind='cost'",(jid,user_id.get())).fetchone()
        if not r:raise HTTPException(404,'记录不存在或无权访问。')
        v=dict(r);v['input']=json.loads(v.pop('input_json'));v['result']=json.loads(v.pop('result_json') or 'null');return v
    @app.post('/planning/{kind}')
    def create(kind:Literal['cost'],data:Idea,tasks:BackgroundTasks):
        evidence=[]
        if not data.text.strip():raise HTTPException(422,'请描述想法。')
        # Reserve before any paid search request; the shared limit must cap both services.
        from usage_limits import reserve,QuotaExceeded
        try:reserve(user_id.get())
        except QuotaExceeded as exc:raise HTTPException(429,str(exc))
        jid=str(uuid.uuid4())
        with b.connect() as db:db.execute('INSERT INTO planning_jobs(id,owner_id,kind,input_json,status,created_at) VALUES(?,?,?,?,?,?)',(jid,user_id.get(),kind,data.model_dump_json(),'running',datetime.now(timezone.utc).isoformat()))
        tasks.add_task(work,jid,kind,data,evidence);return {'id':jid}
