import sys,json
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_diagnosis import c,create
from word_report import export_docx,W

def test_word_endpoint_matches_markdown(c):
    rid=create(c);r=c.get('/runs/'+rid+'/report.docx')
    assert r.status_code==200 and 'wordprocessingml' in r.headers['content-type']
    assert '.docx' in r.headers['content-disposition']
    with ZipFile(BytesIO(r.content)) as z:
        assert z.testzip() is None
        text=''.join(ET.fromstring(z.read('word/document.xml')).itertext())
        for heading in ['执行摘要','核心劝退因素','意外的爽点','方向','真人验证计划','需求理解']:assert heading in text
        assert 'recognition：' not in text
        assert 'fldSimple' in z.read('word/footer1.xml').decode()
    assert '需求理解：' in c.get('/runs/'+rid+'/report').text

def test_word_access_and_incomplete(c):
    import backend as b
    rid=create(c)
    with b.connect() as db:db.execute("UPDATE runs SET status='running' WHERE id=?",(rid,))
    assert c.get('/runs/'+rid+'/report.docx').status_code==409
    token=c.post('/auth/register',json={'username':'docx_other','password':'test-password-22'}).json()['token']
    assert c.get('/runs/'+rid+'/report.docx',headers={'Authorization':'Bearer '+token}).status_code==404
    c.headers.pop('Authorization')
    assert c.get('/runs/'+rid+'/report.docx').status_code==401

def test_word_special_chars_and_long_content():
    content='中文 <标签> & test\x00'+'很长的分析内容'*1000
    data=export_docx('# 报告\n\n## 测试\n\n'+content+'\n\n1. 第一步\n\n2. 第二步')
    with ZipFile(BytesIO(data)) as z:
        for name in z.namelist():ET.fromstring(z.read(name))
        text=''.join(ET.fromstring(z.read('word/document.xml')).itertext())
        assert content.replace('\x00','') in text
        assert '<w:tbl' not in text
        assert 'numbering.xml' in z.namelist()[-1] or 'word/numbering.xml' in z.namelist()
