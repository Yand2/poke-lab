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

def test_removed_market_no_quota(client):
 assert client.post('/api/planning/market',json={'text':'共享雨伞'}).status_code==422
 assert client.get('/api/auth/me').json()['user_budget']['remaining']==100

def test_cost_persist_isolation_and_quota(client,monkeypatch):
 monkeypatch.setattr(p,'request_json',lambda *a,**k:p.CostResult(summary='预算',assumptions=['试点'],items=[dict(name='开发',cadence='once',low=100,high=200,assumption='1人月')],exclusions=['税费']))
 rid=client.post('/api/planning/cost',json={'text':'校园雨伞'}).json()['id'];r=client.get('/api/planning/'+rid).json();assert r['status']=='completed' and len(r['result']['items'])==1
 assert client.get('/api/auth/me').json()['user_budget']['remaining']==99
 other=client.post('/api/auth/register',json={'username':'another','password':'test-password'}).json()['token'];assert client.get('/api/planning/'+rid,headers={'Authorization':'Bearer '+other}).status_code==404

def test_cost_range():
 with pytest.raises(ValueError):p.CostLine(name='x',cadence='once',low=3,high=2,assumption='x')
 with pytest.raises(ValueError):p.CostLine(name='x',cadence='once',low=float('nan'),high=2,assumption='x')


def test_old_market_hidden(client):
 from accounts import user_id
 with b.connect() as db:
  uid=db.execute("SELECT id FROM users WHERE username='planner'").fetchone()[0]
  db.execute("INSERT INTO planning_jobs(id,owner_id,kind,input_json,status,created_at) VALUES('old',?,'market','{}','completed','2026-01-01')",(uid,))
 assert client.get('/api/planning/old').status_code==404
 assert client.get('/api/planning').json()['items']==[]
