from test_api import client
import backend as b

def test_chat_one_word_and_missing_fields(client):
    r=client.post('/conversations',json={'message':'伞','mode':'demo'})
    assert r.status_code==202
    c=client.get('/conversations/'+r.json()['id']).json()
    t=c['turns'][0]
    assert t['status']=='completed' and len(t['replies'])==5
    assert t['structured']['alternative']=={'value':None,'evidence':[]}
    assert t['structured']['concept']['evidence']==['伞']

def test_chat_followup_history(client):
    cid=client.post('/conversations',json={'message':'校园共享伞','mode':'demo'}).json()['id']
    assert client.post('/conversations/'+cid+'/messages',json={'message':'改成免费借用','mode':'demo'}).status_code==202
    c=client.get('/conversations/'+cid).json()
    assert len(c['turns'])==2 and c['turns'][1]['structured']['concept']['evidence']==['校园共享伞','改成免费借用']
    assert client.get('/conversations').json()[0]['id']==cid

def test_chat_invalid_and_missing(client):
    assert client.post('/conversations',json={'message':' ','mode':'demo'}).status_code==422
    assert client.get('/conversations/absent').status_code==404
    assert client.post('/conversations',json={'message':'想法','mode':'live'}).status_code==503

def test_chat_running_and_mode_guard(client):
    cid=client.post('/conversations',json={'message':'校园共享伞','mode':'demo'}).json()['id']
    with b.connect() as db: db.execute("UPDATE chat_turns SET status='running' WHERE conversation_id=?",(cid,))
    assert client.post('/conversations/'+cid+'/messages',json={'message':'补充','mode':'demo'}).status_code==409
    assert client.post('/conversations/'+cid+'/retry').status_code==409

def test_chat_retry(client):
    cid=client.post('/conversations',json={'message':'共享伞','mode':'demo'}).json()['id']
    with b.connect() as db: db.execute("UPDATE chat_turns SET status='failed' WHERE conversation_id=?",(cid,))
    assert client.post('/conversations/'+cid+'/retry').status_code==202
    assert client.get('/conversations/'+cid).json()['turns'][0]['status']=='completed'

def test_chat_restart_recovery(client):
    cid=client.post('/conversations',json={'message':'共享伞','mode':'demo'}).json()['id']
    with b.connect() as db: db.execute("UPDATE chat_turns SET status='running' WHERE conversation_id=?",(cid,))
    b.init_db()
    assert client.get('/conversations/'+cid).json()['turns'][0]['status']=='failed'
