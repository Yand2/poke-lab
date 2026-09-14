import sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
import backend as b
import planning_service as p
from web_app import app
@pytest.fixture
def client(tmp_path,monkeypatch):
 monkeypatch.setattr(b,'DB',tmp_path/'test.sqlite3');monkeypatch.delenv('DATABASE_URL',raising=False);monkeypatch.delenv('REQUIRE_POSTGRES',raising=False);monkeypatch.delenv('ZHIPU_API_KEY',raising=False);monkeypatch.setenv('AI_DAILY_USER_LIMIT','100');monkeypatch.setenv('AI_DAILY_GLOBAL_LIMIT','100')
 with TestClient(app) as c:
  t=c.post('/api/auth/register',json={'username':'planner','password':'test-password'}).json()['token'];c.headers['Authorization']='Bearer '+t;yield c

def test_missing_search_no_quota(client):
 assert not client.get('/api/planning/status').json()['search_ready']
 assert client.post('/api/planning/market',json={'text':'校园雨伞'}).status_code==503
 assert client.get('/api/auth/me').json()['user_budget']['remaining']==100

def test_cost_persist_isolation_and_quota(client,monkeypatch):
 monkeypatch.setattr(p,'request_json',lambda *a,**k:p.CostResult(summary='预算',assumptions=['试点'],items=[dict(name='开发',cadence='once',low=100,high=200,assumption='1人月')],exclusions=['税费']))
 rid=client.post('/api/planning/cost',json={'text':'校园雨伞'}).json()['id'];r=client.get('/api/planning/'+rid).json();assert r['status']=='completed' and len(r['result']['items'])==1
 assert client.get('/api/auth/me').json()['user_budget']['remaining']==99
 other=client.post('/api/auth/register',json={'username':'another','password':'test-password'}).json()['token'];assert client.get('/api/planning/'+rid,headers={'Authorization':'Bearer '+other}).status_code==404

def test_market_sources_and_failure(client,monkeypatch):
 monkeypatch.setenv('ZHIPU_API_KEY','test-key')
 monkeypatch.setattr(p,'search',lambda x:[dict(id=1,title='官网',url='https://example.com',excerpt='雨伞',page_date=None,retrieved_at='2026-09-14')])
 def model(*a,**kw):
  r=p.MarketResult(conclusion='已有方案',competitors=[dict(name='测试方案',positioning='共享',strengths=[],weaknesses=[],feedback='未知',sources=[1])],opportunities=[],gaps=['无份额']);kw['validate'](r);return r
 monkeypatch.setattr(p,'request_json',model);rid=client.post('/api/planning/market',json={'text':'校园雨伞'}).json()['id'];r=client.get('/api/planning/'+rid).json();assert r['result']['sources'][0]['id']==1
 def bad(*a,**k):raise ValueError('invalid')
 monkeypatch.setattr(p,'request_json',bad);rid=client.post('/api/planning/cost',json={'text':'校园雨伞'}).json()['id'];assert client.get('/api/planning/'+rid).json()['status']=='failed'

def test_cost_range():
 with pytest.raises(ValueError):p.CostLine(name='x',cadence='once',low=3,high=2,assumption='x')
 with pytest.raises(ValueError):p.CostLine(name='x',cadence='once',low=float('nan'),high=2,assumption='x')


def test_zhipu_contract(monkeypatch):
 import httpx
 monkeypatch.setenv('ZHIPU_API_KEY','test-secret')
 real=httpx.Client
 def handler(req):
  import json
  data=json.loads(req.content)
  assert req.url.host=='open.bigmodel.cn'
  assert data['search_engine']=='search_pro' and len(data['search_query'])<=70
  assert '深圳' in data['search_query'] and data['search_recency_filter']=='oneMonth'
  assert req.headers['Authorization']=='Bearer test-secret'
  return httpx.Response(200,json={'search_result':[{'title':'官网','link':'https://example.com','content':'实际片段','publish_date':'2026-01-01'},{'link':'javascript:alert(1)'},{'link':'https://example.com'}]})
 monkeypatch.setattr(p.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
 result=p.search(p.Idea(text='创新点'*100,region='中国广东深圳',period='month'));assert len(result)==1 and result[0]['id']==1 and result[0]['excerpt']=='实际片段'


def test_limit_precedes_paid_search(client,monkeypatch):
 monkeypatch.setenv('ZHIPU_API_KEY','test-key')
 monkeypatch.setenv('AI_DAILY_GLOBAL_LIMIT','1')
 monkeypatch.setattr(p,'request_json',lambda *a,**k:p.CostResult(summary='x',assumptions=[],items=[dict(name='x',cadence='once',low=1,high=2,assumption='x')],exclusions=[]))
 assert client.post('/api/planning/cost',json={'text':'测试预算'}).status_code==200
 def forbidden(*a):raise AssertionError('paid search should not run')
 monkeypatch.setattr(p,'search',forbidden)
 assert client.post('/api/planning/market',json={'text':'测试竞品'}).status_code==429
