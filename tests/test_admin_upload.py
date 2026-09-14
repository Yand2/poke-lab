import sys,hashlib,os,json,io,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
import backend as b
from web_app import app
from document_extract import extract
@pytest.fixture
def web(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'DB',tmp_path/'admin.sqlite3')
    salt='12'*16;hashed=hashlib.scrypt(b'test-admin-pass',salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    monkeypatch.setenv('ADMIN_BOOTSTRAP_SALT',salt);monkeypatch.setenv('ADMIN_BOOTSTRAP_HASH',hashed)
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'username':'admin','password':'test-admin-pass'}).json()['token']
        c.headers['Authorization']='Bearer '+token;yield c

def test_admin_access_and_password_secrecy(web):
    r=web.get('/api/admin/users');assert r.status_code==200
    assert 'password_hash' not in r.text and 'salt' not in r.text and 'test-admin-pass' not in r.text
    assert web.get('/api/auth/me').json()['is_admin']
    assert web.post('/api/auth/register',json={'username':'ADMIN','password':'user-test-pass'}).status_code==409
    token=web.post('/api/auth/register',json={'username':'regular','password':'user-test-pass'}).json()['token']
    for method,path in [('GET','/api/admin/users'),('GET','/api/admin/overview'),('DELETE','/api/admin/users/x'),('PATCH','/api/admin/runs/x')]:
        assert web.request(method,path,headers={'Authorization':'Bearer '+token},json={}).status_code==403

def test_user_edit_reset_delete_and_admin_protection(web):
    admin=web.get('/api/admin/users').json()['items'][0]
    assert web.delete('/api/admin/users/'+admin['id']).status_code==409
    token=web.post('/api/auth/register',json={'username':'regular','password':'user-test-pass'}).json()['token']
    uid=next(u['id'] for u in web.get('/api/admin/users').json()['items'] if u['username']=='regular')
    assert web.patch('/api/admin/users/'+uid,json={'username':'renamed','password':'new-test-pass'}).status_code==200
    assert web.get('/api/auth/me',headers={'Authorization':'Bearer '+token}).status_code==401
    assert web.post('/api/auth/login',json={'username':'renamed','password':'new-test-pass'}).status_code==200
    with b.connect() as db:
        row=db.execute('SELECT password_hash FROM users WHERE id=?',(uid,)).fetchone();assert row[0]!='new-test-pass' and len(row[0])==128
    assert web.delete('/api/admin/users/'+uid).status_code==200
    assert web.get('/api/admin/audit').json()['items']

def seed(web):
    with b.connect() as db:
        uid=db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        db.execute("INSERT INTO runs(id,owner_id,status,concept,raw_text,diagnosis_json) VALUES('r',?,'completed','old','old text','{}')",(uid,))
        db.execute("INSERT INTO tasks(id,run_id,persona_id,status,result_json) VALUES('t','r','R1','completed','{}')")

def test_edit_invalidation_and_delete_dependencies(web):
    seed(web)
    assert web.patch('/api/admin/runs/r',json={'text':'new idea'}).status_code==200
    r=web.get('/api/admin/runs/r').json();assert r['raw_text']=='new idea' and not r['results'] and r['diagnosis_json'] is None and r['status']=='failed'
    with b.connect() as db:db.execute("INSERT INTO runs(id,parent_id,status) VALUES('child','r','completed')")
    assert web.patch('/api/admin/runs/r',json={'text':'changed'}).status_code==409
    assert web.delete('/api/admin/runs/r').status_code==200
    assert web.get('/api/admin/runs/child').status_code==404

def test_running_and_chat_edit_guard(web):
    seed(web)
    with b.connect() as db:
        db.execute("UPDATE runs SET status='running' WHERE id='r'")
        db.execute("INSERT INTO conversations(id,title) VALUES('c','chat')")
        db.execute("INSERT INTO chat_turns(id,conversation_id,message,status,created_at,replies_json) VALUES('a','c','old','completed','1','[]')")
        db.execute("INSERT INTO chat_turns(id,conversation_id,message,status,created_at,replies_json) VALUES('z','c','new','completed','2','[]')")
    assert web.delete('/api/admin/runs/r').status_code==409
    assert web.patch('/api/admin/conversations/c/turns/a',json={'message':'change'}).status_code==409
    assert web.patch('/api/admin/conversations/c/turns/z',json={'message':'change'}).status_code==200
    assert web.get('/api/admin/conversations/c').json()['turns'][-1]['status']=='failed'
    assert web.delete('/api/admin/conversations/c').status_code==200

def test_document_extraction_and_bounds():
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>创新点子</w:t></w:r></w:p></w:body></w:document>')
    assert extract(out.getvalue(),'docx')=='创新点子'
    assert extract('一段想法'.encode(),'txt')=='一段想法'
    with pytest.raises(ValueError):extract(b'bad','docx')
    with pytest.raises(ValueError):extract(b'a'*30001,'txt')
    from pypdf import PdfWriter
    pdf=io.BytesIO();w=PdfWriter();w.add_blank_page(width=300,height=300);w.write(pdf)
    with pytest.raises(ValueError,match='未提取'):extract(pdf.getvalue(),'pdf')

def test_upload_requires_login_and_no_ai_quota(web):
    before=web.get('/api/auth/me').json()['user_budget']['used']
    r=web.post('/api/documents/extract?filename=idea.txt',content='我的创新想法'.encode());assert r.status_code==200 and r.json()['text']=='我的创新想法'
    assert web.get('/api/auth/me').json()['user_budget']['used']==before
    assert web.post('/api/documents/extract?filename=x.exe',content=b'abc').status_code==415
    assert web.post('/api/documents/extract?filename=x.txt',content=b'a'*(5*1024*1024+1)).status_code==413
    assert web.post('/api/documents/extract?filename=x.txt',content=b'abc',headers={'Authorization':'Bearer bad'}).status_code==401
