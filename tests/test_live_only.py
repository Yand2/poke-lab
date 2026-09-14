import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import backend as b
from fastapi.testclient import TestClient

def test_no_demo_creation(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'DB',tmp_path/'test.sqlite3')
    with TestClient(b.app) as c:
        assert c.post('/conversations',json={'message':'点子','mode':'demo'}).status_code==422
        assert c.post('/runs',json={'concept':'共享会议助手','pain_point':'记录会议很麻烦','alternative':'人工记录','mode':'demo'}).status_code==422

def test_live_default():
    from chat_service import Message
    assert Message(message='点子').mode=='live'
    assert b.Input(concept='共享会议助手',pain_point='记录会议很麻烦',alternative='人工记录').mode=='live'

def test_history_hides_rules_without_deleting(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'DB',tmp_path/'history.sqlite3')
    with TestClient(b.app) as c:
        with b.connect() as db:
            db.execute('INSERT INTO conversations VALUES (?,?,?,?)',('old','旧记录','demo','2026-01-01'))
            db.execute('INSERT INTO conversations VALUES (?,?,?,?)',('new','真实记录','live','2026-01-02'))
        assert [r['id'] for r in c.get('/conversations').json()]==['new']
        with b.connect() as db: assert db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0]==2

def test_missing_config_is_error(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'DB',tmp_path/'missing.sqlite3')
    monkeypatch.delenv('LLM_API_KEY',raising=False)
    with TestClient(b.app) as c:
        assert c.post('/conversations',json={'message':'点子'}).status_code==503

def test_guide_and_ui_no_mode():
    root=Path(__file__).resolve().parents[1]
    for file in ['app.py','chat_ui.py']:
        s=(root/file).read_text(encoding='utf8')
        assert '演示模式' not in s and 'mode_label' not in s
