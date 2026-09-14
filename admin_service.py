"""Explicit administrator capabilities with server-side role checks and audit events."""
import os,hashlib,secrets,time,sqlite3,uuid
from fastapi import HTTPException,Query
from pydantic import BaseModel,Field,ConfigDict
from accounts import user_id
from typing import Literal

def bootstrap_admin():
    import backend as b
    salt=os.getenv('ADMIN_BOOTSTRAP_SALT');hashed=os.getenv('ADMIN_BOOTSTRAP_HASH')
    if not salt or not hashed:return
    with b.connect() as db:
        old=db.execute('SELECT id FROM users WHERE username=? COLLATE NOCASE',('admin',)).fetchone()
        if old:
            if not db.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(old['id'],)).fetchone():
                raise RuntimeError('Reserved admin account already exists without administrator role')
            return
        uid=secrets.token_hex(16)
        db.execute('INSERT INTO users(id,username,salt,password_hash,created_at) VALUES(?,?,?,?,?)',(uid,'admin',salt,hashed,time.time()))
        db.execute('INSERT INTO admin_roles(user_id) VALUES(?)',(uid,))

class UserEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=3,max_length=40,pattern=r'^[A-Za-z0-9_\-\u4e00-\u9fff]+$')
    password:str|None=Field(default=None,min_length=8,max_length=128)
class UserCreate(UserEdit):
    password:str=Field(min_length=8,max_length=128)
    role:Literal['user','admin']='user'

class RunEdit(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    text:str=Field(min_length=1,max_length=30000)
class ChatEdit(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title:str=Field(min_length=1,max_length=120)
class TurnEdit(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    message:str=Field(min_length=1,max_length=30000)

def require_admin(db):
    if not db.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(user_id.get(),)).fetchone():raise HTTPException(403,'仅管理员可以访问。')
def audit(db,action,target):db.execute('INSERT INTO admin_audit VALUES(?,?,?,?,?)',(str(uuid.uuid4()),user_id.get(),action,target,time.time()))
def require_row(db,table,rid):
    r=db.execute(f'SELECT * FROM {table} WHERE id=?',(rid,)).fetchone()
    if not r:raise HTTPException(404,'记录不存在。')
    return r

def run_family(db,rid):
    return [r['id'] for r in db.execute('WITH RECURSIVE family(id) AS (SELECT id FROM runs WHERE id=? UNION ALL SELECT runs.id FROM runs JOIN family ON runs.parent_id=family.id) SELECT id FROM family',(rid,))]
def remove_runs(db,ids):
    for rid in ids:
        r=require_row(db,'runs',rid)
        if r['status']=='running':raise HTTPException(409,'分析仍在进行，请完成后再删除。')
    for rid in reversed(ids):
        db.execute('DELETE FROM tasks WHERE run_id=?',(rid,));db.execute('DELETE FROM runs WHERE id=?',(rid,))
def remove_chat(db,cid):
    if db.execute("SELECT 1 FROM chat_turns WHERE conversation_id=? AND status='running'",(cid,)).fetchone():raise HTTPException(409,'对话仍在回复，请完成后再删除。')
    db.execute('DELETE FROM chat_turns WHERE conversation_id=?',(cid,));db.execute('DELETE FROM conversations WHERE id=?',(cid,))

def install_admin(app):
    import backend as b
    @app.get('/admin/overview')
    def overview():
        with b.connect() as db:
            require_admin(db)
            return {t:db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['users','runs','conversations']}
    @app.get('/admin/users')
    def users(q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
        with b.connect() as db:
            require_admin(db)
            return {'items':[dict(r,password_status='已加密（scrypt）') for r in db.execute('SELECT u.id,u.username,u.created_at,CASE WHEN a.user_id IS NULL THEN 0 ELSE 1 END AS is_admin FROM users u LEFT JOIN admin_roles a ON a.user_id=u.id WHERE lower(u.username) LIKE lower(?) ORDER BY u.created_at DESC LIMIT ? OFFSET ?',('%'+q+'%',limit,offset))]}
    @app.post('/admin/users',status_code=201)
    def create_user(data:UserCreate):
        with b.connect() as db:
            require_admin(db)
            if data.username.casefold()=='admin':raise HTTPException(409,'admin 为系统保留账号名，请使用其他名称。')
            uid=secrets.token_hex(16);salt=secrets.token_hex(16)
            hashed=hashlib.scrypt(data.password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
            try:db.execute('INSERT INTO users(id,username,salt,password_hash,created_at) VALUES(?,?,?,?,?)',(uid,data.username,salt,hashed,time.time()))
            except sqlite3.IntegrityError:raise HTTPException(409,'用户名已存在。')
            if data.role=='admin':db.execute('INSERT INTO admin_roles(user_id) VALUES(?)',(uid,))
            audit(db,'create_admin' if data.role=='admin' else 'create_user',uid)
        return {'id':uid,'username':data.username,'is_admin':data.role=='admin'}
    @app.patch('/admin/users/{uid}')
    def edit_user(uid:str,data:UserEdit):
        with b.connect() as db:
            require_admin(db);old=require_row(db,'users',uid)
            is_admin=bool(db.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(uid,)).fetchone())
            if is_admin and data.username!=old['username']:raise HTTPException(409,'管理员账号名不可修改。')
            if data.username.casefold()=='admin' and not is_admin:raise HTTPException(409,'管理员名称不可用于普通账号。')
            try:db.execute('UPDATE users SET username=? WHERE id=?',(data.username,uid))
            except sqlite3.IntegrityError:raise HTTPException(409,'用户名已存在。')
            if data.password:
                salt=secrets.token_hex(16);hashed=hashlib.scrypt(data.password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
                db.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(salt,hashed,uid))
                db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            db.execute('DELETE FROM login_attempts WHERE name=?',(old['username'].casefold(),))
            audit(db,'update_user',uid)
        return {'ok':True,'session_revoked':bool(data.password)}
    @app.delete('/admin/users/{uid}')
    def delete_user(uid:str):
        with b.connect() as db:
            require_admin(db);old=require_row(db,'users',uid)
            if db.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(uid,)).fetchone():raise HTTPException(409,'不能删除管理员账号。')
            roots=[r['id'] for r in db.execute('SELECT id FROM runs WHERE owner_id=? AND parent_id IS NULL',(uid,))]
            for rid in roots:remove_runs(db,run_family(db,rid))
            for c in db.execute('SELECT id FROM conversations WHERE owner_id=?',(uid,)).fetchall():remove_chat(db,c['id'])
            db.execute('DELETE FROM planning_jobs WHERE owner_id=?',(uid,));db.execute('DELETE FROM sessions WHERE user_id=?',(uid,));db.execute('DELETE FROM ai_budgets WHERE bucket=?',('user:'+uid,))
            db.execute('DELETE FROM login_attempts WHERE name=?',(old['username'].casefold(),));db.execute('DELETE FROM users WHERE id=?',(uid,));audit(db,'delete_user_and_data',uid)
        return {'ok':True}
    @app.get('/admin/runs')
    def runs(q:str='',owner:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
        with b.connect() as db:
            require_admin(db)
            return {'items':[dict(r) for r in db.execute('SELECT r.id,r.concept,r.status,r.created_at,r.owner_id,r.parent_id,u.username FROM runs r LEFT JOIN users u ON r.owner_id=u.id WHERE (lower(r.concept) LIKE lower(?) OR lower(u.username) LIKE lower(?)) AND (?=\'\' OR r.owner_id=?) ORDER BY r.created_at DESC LIMIT ? OFFSET ?',('%'+q+'%','%'+q+'%',owner,owner,limit,offset))]}
    @app.get('/admin/runs/{rid}')
    def read_run(rid:str):
        with b.connect() as db:require_admin(db)
        return b.get_run(rid)
    @app.get('/admin/runs/{rid}/report')
    def report(rid:str):
        with b.connect() as db:require_admin(db)
        return b.report(rid)
    @app.get('/admin/runs/{rid}/report.docx')
    def word(rid:str):
        with b.connect() as db:require_admin(db)
        return b.word_report(rid)
    @app.patch('/admin/runs/{rid}')
    def edit_run(rid:str,data:RunEdit):
        with b.connect() as db:
            require_admin(db);r=require_row(db,'runs',rid)
            if r['status']=='running':raise HTTPException(409,'分析中不能编辑。')
            if r['parent_id'] or len(run_family(db,rid))>1:raise HTTPException(409,'存在单变量对照关系，不能改写基线；请新建实验。')
            db.execute("UPDATE runs SET raw_text=?,concept=?,pain_point='未说明',alternative='未说明',structured_json=NULL,profiles_json=NULL,diagnosis_json=NULL,diagnosis_error=NULL,status='failed',error='管理员修改了输入，请重新分析。' WHERE id=?",(data.text,data.text[:160],rid))
            db.execute('DELETE FROM tasks WHERE run_id=?',(rid,));audit(db,'edit_run_invalidate_results',rid)
        return {'ok':True}
    @app.delete('/admin/runs/{rid}')
    def delete_run(rid:str):
        with b.connect() as db:require_admin(db);require_row(db,'runs',rid);remove_runs(db,run_family(db,rid));audit(db,'delete_run_and_challenges',rid)
        return {'ok':True}
    @app.get('/admin/conversations')
    def chats(q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
        with b.connect() as db:
            require_admin(db)
            return {'items':[dict(r) for r in db.execute('SELECT c.id,c.title,c.created_at,u.username FROM conversations c LEFT JOIN users u ON c.owner_id=u.id WHERE lower(c.title) LIKE lower(?) OR lower(u.username) LIKE lower(?) ORDER BY c.created_at DESC LIMIT ? OFFSET ?',('%'+q+'%','%'+q+'%',limit,offset))]}
    @app.get('/admin/conversations/{cid}')
    def read_chat(cid:str):
        import json
        with b.connect() as db:
            require_admin(db);c=dict(require_row(db,'conversations',cid));c['turns']=[dict(t,replies=json.loads(t['replies_json'] or '[]')) for t in db.execute('SELECT * FROM chat_turns WHERE conversation_id=? ORDER BY created_at,id',(cid,))];return c
    @app.patch('/admin/conversations/{cid}')
    def rename_chat(cid:str,data:ChatEdit):
        with b.connect() as db:require_admin(db);require_row(db,'conversations',cid);db.execute('UPDATE conversations SET title=? WHERE id=?',(data.title,cid));audit(db,'rename_conversation',cid)
        return {'ok':True}
    @app.delete('/admin/conversations/{cid}')
    def delete_chat(cid:str):
        with b.connect() as db:require_admin(db);require_row(db,'conversations',cid);remove_chat(db,cid);audit(db,'delete_conversation',cid)
        return {'ok':True}
    @app.patch('/admin/conversations/{cid}/turns/{tid}')
    def edit_turn(cid:str,tid:str,data:TurnEdit):
        with b.connect() as db:
            require_admin(db)
            latest=db.execute('SELECT id,status FROM chat_turns WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(cid,)).fetchone()
            if not latest or latest['id']!=tid:raise HTTPException(409,'只支持编辑最新一轮，避免更改后续对话的依据。')
            if latest['status']=='running':raise HTTPException(409,'回复中不能编辑。')
            db.execute("UPDATE chat_turns SET message=?,structured_json=NULL,replies_json='[]',status='failed',error='管理员修改了本轮问题，请重试本轮。' WHERE id=?",(data.message,tid));audit(db,'edit_turn_invalidate_replies',tid)
        return {'ok':True}
    @app.get('/admin/audit')
    def events():
        with b.connect() as db:require_admin(db);return {'items':[dict(r) for r in db.execute('SELECT id,action,target_id,created_at FROM admin_audit ORDER BY created_at DESC LIMIT 100')]}
