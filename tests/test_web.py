from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
import backend as b
from web_app import app
@pytest.fixture
def web(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'DB',tmp_path/'web.sqlite3')
    monkeypatch.setenv('AI_DAILY_USER_LIMIT','100')
    monkeypatch.setenv('AI_DAILY_GLOBAL_LIMIT','100')
    with TestClient(app) as c: yield c

def signup(c,name):
    r=c.post('/api/auth/register',json={'username':name,'password':'Web-test-2026'})
    assert r.status_code==201
    return {'Authorization':'Bearer '+r.json()['token']}

def test_static_no_secret_and_security_headers(web):
    r=web.get('/');assert r.status_code==200 and '/assets/app.js' in r.text
    assert r.headers['X-Frame-Options']=='DENY'
    assert "script-src 'self'" in r.headers['Content-Security-Policy']
    for path in ['/assets/../api_config.toml','/assets/%2e%2e/api_config.toml','/api_config.toml']:
        assert web.get(path).status_code==404
    assert web.get('/_stcore/health').status_code==200

def test_mounted_api_auth_ownership_and_quota(web):
    assert web.get('/api/auth/me').status_code==401
    a=signup(web,'web-alice');z=signup(web,'web-other')
    me=web.get('/api/auth/me',headers=a);assert me.status_code==200
    assert me.json()['user_budget']=={'limit':100,'used':0,'remaining':100}
    with b.connect() as db:
        uid=db.execute("SELECT id FROM users WHERE username='web-alice'").fetchone()[0]
        db.execute("INSERT INTO runs(id,owner_id,concept,status,mode,created_at) VALUES('web-run',?,'private','completed','live','2026-09-14')",(uid,))
    assert len(web.get('/api/runs',headers=a).json())==1
    assert web.get('/api/runs',headers=z).json()==[]
    for suffix in ['', '/report', '/report.docx']:
        assert web.get('/api/runs/web-run'+suffix,headers=z).status_code==404
    assert web.post('/api/runs/web-run/challenge',headers=z,json={'variable':'price','value':'free'}).status_code==404
    assert web.post('/api/auth/logout',headers=a).status_code==200
    assert web.get('/api/auth/me',headers=a).status_code==401
