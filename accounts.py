import hashlib, hmac, secrets, time, sqlite3
from contextvars import ContextVar
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

user_id=ContextVar('user_id',default=None)
class Credentials(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=3,max_length=40,pattern=r'^[A-Za-z0-9_\-\u4e00-\u9fff]+$')
    password:str=Field(min_length=8,max_length=128)

def init(db):
    from usage_limits import init as init_limits
    init_limits(db)
    db.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, salt TEXT, password_hash TEXT, created_at REAL);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires REAL);
    CREATE TABLE IF NOT EXISTS login_attempts(name TEXT PRIMARY KEY,count INTEGER,until REAL);''')
    db.executescript('CREATE TABLE IF NOT EXISTS admin_roles(user_id TEXT PRIMARY KEY REFERENCES users(id)); CREATE TABLE IF NOT EXISTS admin_audit(id TEXT PRIMARY KEY,actor_id TEXT,action TEXT,target_id TEXT,created_at REAL);')
    for table in ['runs','conversations']:
        if 'owner_id' not in [r[1] for r in db.execute(f'PRAGMA table_info({table})')]: db.execute(f'ALTER TABLE {table} ADD COLUMN owner_id TEXT')
    for name in ['raw_text','structured_json']:
        if name not in [r[1] for r in db.execute('PRAGMA table_info(runs)')]: db.execute(f'ALTER TABLE runs ADD COLUMN {name} TEXT')

def install(app):
    import backend as b
    def digest(password,salt): return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    def session(db,uid,username):
        token=secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,time.time()+604800))
        return {'token':token,'username':username}
    @app.post('/auth/register',status_code=201)
    def register(data:Credentials):
        if data.username.casefold()=='admin': raise HTTPException(409,'该用户名保留给管理员，请使用其他用户名。')
        salt=secrets.token_hex(16); uid=secrets.token_hex(16)
        with b.connect() as db:
            try: db.execute('INSERT INTO users VALUES (?,?,?,?,?)',(uid,data.username,salt,digest(data.password,salt),time.time()))
            except sqlite3.IntegrityError: raise HTTPException(409,'用户名已存在，请登录或更换用户名。')
            return session(db,uid,data.username)
    @app.post('/auth/login')
    def login(data:Credentials):
        name=data.username.casefold()
        with b.connect() as db:
            a=db.execute('SELECT * FROM login_attempts WHERE name=?',(name,)).fetchone()
            if a and a['count']>=10 and a['until']>time.time(): raise HTTPException(429,'尝试过多，请15分钟后重试。')
            row=db.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(data.username,)).fetchone()
            valid=row and hmac.compare_digest(digest(data.password,row['salt']),row['password_hash'])
            if not valid:
                count=a['count']+1 if a and a['until']>time.time() else 1
                db.execute('INSERT OR REPLACE INTO login_attempts VALUES (?,?,?)',(name,count,time.time()+900))
                db.commit()
                raise HTTPException(401,'用户名或密码错误。')
            db.execute('DELETE FROM login_attempts WHERE name=?',(name,))
            return session(db,row['id'],row['username'])
    @app.get('/auth/me')
    def me():
        from datetime import datetime, timezone
        import os
        uid=user_id.get()
        day=datetime.now(timezone.utc).date().isoformat()
        with b.connect() as db:
            user=db.execute('SELECT username FROM users WHERE id=?',(uid,)).fetchone()
            def budget(bucket,setting):
                row=db.execute('SELECT count FROM ai_budgets WHERE bucket=? AND day=?',(bucket,day)).fetchone()
                limit=int(os.getenv(setting,'0')); used=row['count'] if row else 0
                return {'limit':limit,'used':used,'remaining':max(0,limit-used) if limit>0 else None}
            return {'username':user['username'],'is_admin':bool(db.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(uid,)).fetchone()),'user_budget':budget('user:'+uid,'AI_DAILY_USER_LIMIT'),'global_budget':budget('global','AI_DAILY_GLOBAL_LIMIT'),'reset_timezone':'UTC'}
    @app.post('/auth/logout')
    def logout(request:Request):
        with b.connect() as db: db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.headers.get('authorization','').removeprefix('Bearer ').encode()).hexdigest(),))
        return {'ok':True}
    @app.middleware('http')
    async def protect(request,call_next):
        path=request.url.path.removeprefix(request.scope.get('root_path',''))
        if path in ['/health','/auth/register','/auth/login','/docs','/openapi.json','/redoc']: return await call_next(request)
        token=request.headers.get('authorization','').removeprefix('Bearer ')
        with b.connect() as db:
            row=db.execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not row: return JSONResponse({'detail':'请先登录。'},status_code=401)
            uid=row['user_id']; parts=path.strip('/').split('/')
            if parts[0]=='admin' and not db.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(uid,)).fetchone():
                return JSONResponse({'detail':'仅管理员可以访问。'},status_code=403)
            if len(parts)>1 and parts[0] in ['runs','conversations']:
                table=parts[0]
                owned=db.execute(f'SELECT 1 FROM {table} WHERE id=? AND owner_id=?',(parts[1],uid)).fetchone()
                if not owned: return JSONResponse({'detail':'记录不存在或无权访问。'},status_code=404)
        if request.method=='POST' and (path in ['/runs','/experiments','/conversations'] or (parts[0] in ['runs','conversations'] and parts[-1] in ['challenge','messages','retry','diagnosis'])):
            from usage_limits import reserve,QuotaExceeded
            try: reserve(uid)
            except QuotaExceeded as exc:return JSONResponse({'detail':str(exc)},status_code=429)
        ctx=user_id.set(uid)
        try: return await call_next(request)
        finally: user_id.reset(ctx)
