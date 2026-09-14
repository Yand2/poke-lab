import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import backend as b
import pytest
from fastapi.testclient import TestClient
@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'DB',tmp_path/'accounts.sqlite3')
    with TestClient(b.app) as client: yield client
def signup(c,name):
    r=c.post('/auth/register',json={'username':name,'password':'Strong-test-123'})
    assert r.status_code==201
    return {'Authorization':'Bearer '+r.json()['token']}
def test_register_login_logout(c):
    h=signup(c,'alice')
    assert c.get('/runs',headers=h).status_code==200
    assert c.post('/auth/register',json={'username':'ALICE','password':'Strong-test-123'}).status_code==409
    assert c.post('/auth/login',json={'username':'alice','password':'wrong-password'}).status_code==401
    assert c.post('/auth/login',json={'username':'alice','password':'Strong-test-123'}).status_code==200
    c.post('/auth/logout',headers=h)
    assert c.get('/runs',headers=h).status_code==401
def test_password_storage(c):
    signup(c,'alice')
    with b.connect() as db:
        r=db.execute('SELECT * FROM users').fetchone()
        assert r['password_hash']!='Strong-test-123' and len(r['salt'])==32
def test_anonymous_rejected(c):
    for path in ['/runs','/conversations']:
        assert c.get(path).status_code==401
    assert c.post('/experiments',json={'text':'想法'}).status_code==401
def test_account_isolation(c):
    a=signup(c,'alice'); z=signup(c,'bobby')
    with b.connect() as db:
        uid=db.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
        db.execute('INSERT INTO conversations (id,title,mode,created_at,owner_id) VALUES (?,?,?,?,?)',('owned','private','live','2026',uid))
        db.execute("INSERT INTO runs(id,concept,status,mode,owner_id) VALUES ('run-owned','private','completed','live',?)",(uid,))
    assert len(c.get('/conversations',headers=a).json())==1
    assert c.get('/conversations',headers=z).json()==[]
    for path in ['/conversations/owned','/runs/run-owned','/runs/run-owned/report']:
        assert c.get(path,headers=z).status_code==404
    assert c.post('/conversations/owned/messages',headers=z,json={'message':'test'}).status_code==404
    assert c.post('/conversations/owned/retry',headers=z).status_code==404
    assert c.post('/runs/run-owned/challenge',headers=z,json={'variable':'price','value':'free'}).status_code==404
def test_expired_and_weak(c):
    assert c.post('/auth/register',json={'username':'aa','password':'123'}).status_code==422
    h=signup(c,'alice')
    with b.connect() as db: db.execute('UPDATE sessions SET expires=0')
    assert c.get('/runs',headers=h).status_code==401
def test_long_text_pipeline(c,monkeypatch):
    h=signup(c,'alice')
    import httpx,json
    from chat_service import Brief,Fact
    original=httpx.Client
    text='给学生提供共享伞'
    brief=Brief(concept=Fact(value=text,evidence=[text]),pain_point=Fact(value=None,evidence=[]),alternative=Fact(value=None,evidence=[]),target_user=Fact(value='学生',evidence=['学生']),business_model=Fact(value=None,evidence=[]),user_question='',open_questions=[])
    def handler(req): return httpx.Response(200,json={'choices':[{'message':{'content':brief.model_dump_json()}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    def analysis(rid):
        r=b.get_run(rid)
        assert r['concept']==text and r['pain_point']=='未说明' and r['raw_text']==text
        with b.connect() as db: db.execute("UPDATE runs SET status='completed' WHERE id=?",(rid,))
    monkeypatch.setattr(b,'analyze',analysis)
    r=c.post('/experiments',headers=h,json={'text':text})
    assert r.status_code==202
    assert c.get('/runs/'+r.json()['id'],headers=h).json()['status']=='completed'
    assert c.post('/experiments',headers=h,json={'text':' '}).status_code==422
