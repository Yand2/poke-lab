"""Persistent daily AI-request budgets for a public demo."""
import os
from datetime import datetime,timezone
class QuotaExceeded(Exception):pass

def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS ai_budgets (bucket TEXT, day TEXT, count INTEGER NOT NULL, PRIMARY KEY(bucket,day))')

def reserve(uid):
    import backend as b
    day=datetime.now(timezone.utc).date().isoformat()
    limits=[('user:'+uid,int(os.getenv('AI_DAILY_USER_LIMIT','0'))),('global',int(os.getenv('AI_DAILY_GLOBAL_LIMIT','0')))]
    with b.connect() as db:
        for bucket,limit in limits:
            if limit<=0:continue
            row=db.execute('INSERT INTO ai_budgets(bucket,day,count) VALUES (?,?,1) ON CONFLICT(bucket,day) DO UPDATE SET count=ai_budgets.count+1 WHERE ai_budgets.count<? RETURNING count',(bucket,day,limit)).fetchone()
            if not row:raise QuotaExceeded('今日AI使用额度已用完，请明天再试。')
