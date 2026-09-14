import json, sys, threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import backend as b
import llm_client as lc
import pytest, httpx
from fastapi.testclient import TestClient
from diagnosis import Diagnosis, Profiles, synthesize

D={'executive_summary':'先验证迁移阻力','core_barriers':[{'title':'迁移成本','analysis':'现有习惯难改变','persona_ids':['R2'],'validation':'观察一次迁移任务'}],'unexpected_values':[],'value_gap_note':'暂无足够依据识别意外价值','direction':'证据不足','rationale':'缺少真实反馈','pivot_conditions':'持续出现相同阻力再考虑转型','next_steps':['访谈目标用户'],'limitations':['模拟不是市场证据']}
P=[{'persona_id':f'R{i}','scenario':'假设校园用户','current_habit':'人工记录','budget_constraint':'未知','adoption_condition':'省时','assumptions':['场景为假设']} for i in range(1,6)]
@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'DB',tmp_path/'test.sqlite3')
    monkeypatch.setattr(b,'profiles_for',lambda *a:P)
    monkeypatch.setattr(b,'synthesize',lambda *a:D)
    monkeypatch.setattr(b,'live_result',lambda r,p:b.Result(recognition='需要整理记录',choice='需要验证',barrier='习惯',reason='迁移需要时间',evidence='concept: 测试商业概念',question='目前怎么做'))
    with TestClient(b.app) as client:
        token=client.post('/auth/register',json={'username':'audit20','password':'test-password-20'}).json()['token']
        client.headers['Authorization']='Bearer '+token
        yield client

def create(c):
    r=c.post('/runs',json={'concept':'测试商业概念','pain_point':'整理会议很麻烦','alternative':'人工记录'})
    assert r.status_code==202
    return r.json()['id']

def test_synthesis_and_report(c):
    rid=create(c);r=c.get('/runs/'+rid).json()
    assert r['status']=='completed' and len(r['results'])==5
    assert json.loads(r['diagnosis_json'])==D
    assert len(json.loads(r['profiles_json']))==5
    report=c.get('/runs/'+rid+'/report').text
    for heading in ['执行摘要','核心劝退因素','意外的爽点','Pivot','下一步验证','假设用户画像']: assert heading in report

def test_challenge_preserves_context_and_short_unknown(c):
    rid=create(c)
    with b.connect() as db:
        db.execute('UPDATE runs SET raw_text=?,structured_json=?,pain_point=? WHERE id=?',('原始输入',json.dumps({'target_user':'学生'}),'未说明',rid))
    r=c.post('/runs/'+rid+'/challenge',json={'variable':'price','value':'免费试用'})
    assert r.status_code==202
    child=c.get('/runs/'+r.json()['id']).json();base=c.get('/runs/'+rid).json()
    for k in ['raw_text','structured_json','profiles_json','concept','pain_point','alternative']: assert child[k]==base[k]
    assert child['variable']=='price' and child['change_value']=='免费试用'
    assert c.post('/runs/'+child['id']+'/challenge',json={'variable':'price','value':'免费试用'}).status_code==409

def test_synthesis_failure_retains_results_and_retries(c,monkeypatch):
    monkeypatch.setattr(b,'synthesize',lambda *a: (_ for _ in ()).throw(ValueError()))
    rid=create(c);r=c.get('/runs/'+rid).json()
    assert r['status']=='completed' and len(r['results'])==5 and r['diagnosis_error']
    assert '综合诊断尚未生成' in c.get('/runs/'+rid+'/report').text
    monkeypatch.setattr(b,'synthesize',lambda *a:D)
    assert c.post('/runs/'+rid+'/diagnosis').status_code==202
    assert c.get('/runs/'+rid).json()['diagnosis_json']

def test_resume_failed_roles(c,monkeypatch):
    orig=b.live_result
    def fail(r,p):
        if p[0]=='R3': raise ValueError()
        return orig(r,p)
    monkeypatch.setattr(b,'live_result',fail)
    rid=create(c);r=c.get('/runs/'+rid).json()
    assert r['status']=='failed' and len(r['results'])==4
    calls=[]
    def resume(r,p): calls.append(p[0]);return orig(r,p)
    monkeypatch.setattr(b,'live_result',resume)
    assert c.post('/runs/'+rid+'/retry').status_code==202
    assert calls==['R3'] and c.get('/runs/'+rid).json()['status']=='completed'
    assert c.post('/runs/'+rid+'/retry').status_code==409

def test_roles_actually_parallel(c,monkeypatch):
    barrier=threading.Barrier(5,timeout=5);orig=b.live_result
    def parallel(r,p): barrier.wait();return orig(r,p)
    monkeypatch.setattr(b,'live_result',parallel)
    assert c.get('/runs/'+create(c)).json()['status']=='completed'

@pytest.mark.parametrize('mode,expected',[('malformed',2),('429',2),('401',1),('always_bad',3)])
def test_bounded_retries(monkeypatch,mode,expected):
    calls=[];original=httpx.Client
    def handler(req):
        calls.append(1)
        if mode=='401':return httpx.Response(401)
        if mode=='429' and len(calls)==1:return httpx.Response(429)
        raw='bad' if mode=='always_bad' or (mode=='malformed' and len(calls)==1) else json.dumps(D)
        return httpx.Response(200,json={'choices':[{'message':{'content':raw}}]})
    monkeypatch.setattr(lc.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(lc.time,'sleep',lambda *a:None)
    if mode in ['401','always_bad']:
        with pytest.raises(Exception):lc.request_json('test',{},Diagnosis)
    else:assert lc.request_json('test',{},Diagnosis).direction=='证据不足'
    assert len(calls)==expected

def test_cross_account_new_endpoints(c):
    rid=create(c)
    token=c.post('/auth/register',json={'username':'another20','password':'test-password-20'}).json()['token']
    for action in ['diagnosis','retry']:
        assert c.post('/runs/'+rid+'/'+action,headers={'Authorization':'Bearer '+token}).status_code==404

def test_chat_live_contract_with_mocked_model(c,monkeypatch):
    from chat_service import Brief,Fact,Advice
    def response(prompt,payload,schema,**kw):
        if schema is Brief:
            text=payload['user_messages'][-1]
            result=Brief(concept=Fact(value=text,evidence=[text]),pain_point=Fact(value=None,evidence=[]),alternative=Fact(value=None,evidence=[]),target_user=Fact(value=None,evidence=[]),business_model=Fact(value=None,evidence=[]),user_question='',open_questions=[])
        else: result=Advice(response='可以先探索使用场景',suggestion='观察一次借伞过程',question='')
        if kw.get('validate'):kw['validate'](result)
        return result
    # install_chat imports the shared function at application installation time.
    import chat_service
    original=httpx.Client
    def handler(req):
        body=json.loads(req.content);payload=json.loads(body['messages'][1]['content'])
        schema=Brief if 'user_messages' in payload else Advice
        result=response('',payload,schema)
        return httpx.Response(200,json={'choices':[{'message':{'content':result.model_dump_json()}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=c.post('/conversations',json={'message':'伞'})
    assert r.status_code==202
    cid=r.json()['id'];data=c.get('/conversations/'+cid).json()
    assert len(data['turns'][0]['replies'])==5
    assert data['turns'][0]['structured']['alternative']['value'] is None
    assert c.post('/conversations/'+cid+'/messages',json={'message':'免费借用'}).status_code==202
    assert len(c.get('/conversations/'+cid).json()['turns'])==2

def test_semantic_validation_is_retried(monkeypatch):
    calls=[];original=httpx.Client
    def handler(req):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(D)}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(lc.time,'sleep',lambda *a:None)
    def valid(result):
        if len(calls)==1:raise ValueError('invalid evidence')
    assert lc.request_json('test',{},Diagnosis,validate=valid)
    assert len(calls)==2

def test_role_receives_full_original_constraints(monkeypatch):
    seen={}
    def request(prompt,payload,schema,**kw):
        seen.update(payload)
        assert '原文是最高优先级事实依据' in prompt
        return b.Result(recognition='理解概念',choice='需要验证',barrier='复核',reason='需校对',evidence='concept: 测试商业概念',question='如何复核')
    monkeypatch.setattr(b,'request_json',request)
    b.live_result({'model':'test','concept':'测试商业概念','pain_point':'漏项','alternative':'人工','variable':None,'change_value':None,'raw_text':'暂时不接入企业内部系统'},b.PERSONAS[0])
    assert seen['raw_text']=='暂时不接入企业内部系统'
