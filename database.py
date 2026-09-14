"""SQLite locally, PostgreSQL in cloud; compatibility for the app's fixed SQL."""
import os,re,sqlite3
from threading import Lock
_pool=None
_pool_url=None
_pool_lock=Lock()
def get_pool(url):
    global _pool,_pool_url
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
    with _pool_lock:
        if _pool is None or _pool_url!=url:
            if _pool is not None:_pool.close()
            _pool=ConnectionPool(url,min_size=0,max_size=5,timeout=20,max_idle=60,max_lifetime=600,check=ConnectionPool.check_connection,kwargs={"connect_timeout":10,"row_factory":dict_row,"prepare_threshold":None},open=True)
            _pool_url=url
        return _pool
def close_pool():
    global _pool,_pool_url
    with _pool_lock:
        if _pool is not None:_pool.close()
        _pool=None;_pool_url=None
class Record(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)
class Cursor:
    def __init__(self,cur):self.cur=cur
    @property
    def rowcount(self):return self.cur.rowcount
    def fetchone(self):
        row=self.cur.fetchone();return Record(row) if row is not None else None
    def fetchall(self):return [Record(r) for r in self.cur.fetchall()]
    def __iter__(self):return iter(self.fetchall())
class MemoryCursor:
    def __init__(self,rows):self.rows=rows
    def __iter__(self):return iter(self.rows)
    def fetchall(self):return self.rows

def placeholders(sql):
    parts=re.split(r"('(?:''|[^'])*')",sql)
    return ''.join(p if i%2 else p.replace('%','%%').replace('?','%s') for i,p in enumerate(parts))
class Postgres:
    def __init__(self,url):
        self._connection=get_pool(url).connection()
        self.db=self._connection.__enter__()
    def __enter__(self):return self
    def __exit__(self,typ,value,tb):return self._connection.__exit__(typ,value,tb)
    def commit(self):self.db.commit()
    def execute(self,sql,params=()):
        import psycopg
        pragma=re.fullmatch(r'PRAGMA table_info\((\w+)\)',sql.strip(),re.I)
        if pragma:
            rows=self.db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position',(pragma[1],)).fetchall()
            return MemoryCursor([(i,r['column_name']) for i,r in enumerate(rows)])
        if sql.strip()=='BEGIN IMMEDIATE':
            return Cursor(self.db.execute('LOCK TABLE chat_turns IN SHARE ROW EXCLUSIVE MODE'))
        sql=sql.replace('username=? COLLATE NOCASE','lower(username)=lower(?)')
        sql=sql.replace('username TEXT UNIQUE COLLATE NOCASE','username TEXT')
        sql=sql.replace('created_at,rowid','created_at,id').replace('created_at DESC,rowid DESC','created_at DESC,id DESC')
        sql=re.sub(r'\bREAL\b','DOUBLE PRECISION',sql)
        if 'INSERT OR REPLACE INTO tasks' in sql:
            sql=sql.replace('INSERT OR REPLACE','INSERT')+' ON CONFLICT (run_id,persona_id) DO UPDATE SET stage=EXCLUDED.stage,status=EXCLUDED.status,result_json=EXCLUDED.result_json'
        elif 'INSERT OR REPLACE INTO login_attempts' in sql:
            sql=sql.replace('INSERT OR REPLACE','INSERT')+' ON CONFLICT (name) DO UPDATE SET count=EXCLUDED.count,until=EXCLUDED.until'
        try:
            return Cursor(self.db.execute(placeholders(sql),params))
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError('Database constraint violation') from exc
    def executescript(self,sql):
        for statement in sql.split(';'):
            if statement.strip():self.execute(statement)
        if 'CREATE TABLE IF NOT EXISTS users' in sql:
            self.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_unique ON users(lower(username))')

def connect(path):
    url=os.environ.get('DATABASE_URL')
    if url:return Postgres(url)
    if os.environ.get('REQUIRE_POSTGRES')=='1':raise RuntimeError('DATABASE_URL must be configured for cloud deployment')
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=20);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
