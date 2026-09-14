"""Bounded document text import. Original files are never persisted."""
import io,json,sys,zipfile,subprocess,asyncio
from pathlib import Path
from fastapi import HTTPException,Request
MAX_BYTES=5*1024*1024
MAX_CHARS=30000

def extract(data,ext):
    if not data:raise ValueError('文件为空，请选择包含文字的文件。')
    if len(data)>MAX_BYTES:raise ValueError('文件超过5MB，请缩小后重试。')
    if ext in ['txt','md']:
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:text=data.decode('gb18030')
            except UnicodeDecodeError:raise ValueError('文本编码无法识别，请保存为UTF-8。')
    elif ext=='docx':
        from defusedxml import ElementTree as ET
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(i.file_size for i in z.infolist())>20*1024*1024:raise ValueError('Word解压内容过大，请精简文档。')
                info=z.getinfo('word/document.xml')
                if info.file_size>10*1024*1024:raise ValueError('Word正文过大，请精简文档。')
                root=ET.fromstring(z.read(info))
                ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                text='\n'.join(''.join(n.text or '' for n in p.findall('.//w:t',ns)) for p in root.findall('.//w:p',ns))
        except (zipfile.BadZipFile,KeyError):raise ValueError('这不是有效的.docx文件，请用Word重新另存为.docx。')
    elif ext=='pdf':
        from pypdf import PdfReader
        try:
            reader=PdfReader(io.BytesIO(data))
            if reader.is_encrypted:raise ValueError('PDF有密码保护，请先解除保护再上传。')
            if len(reader.pages)>80:raise ValueError('PDF超过80页，请只上传与想法有关的部分。')
            parts=[];size=0
            for page in reader.pages:
                part=page.extract_text() or '';size+=len(part)
                if size>MAX_CHARS:raise ValueError('文件文字超过30,000字，请精简后上传。')
                parts.append(part)
            text='\n'.join(parts)
        except ValueError:raise
        except Exception:raise ValueError('PDF无法解析，请重新导出或改用Word文档。')
    else:raise ValueError('支持Word(.docx)、PDF、TXT和Markdown；旧版.doc请先另存为.docx。')
    text=text.replace('\x00','').strip()
    if not text:raise ValueError('未提取到文字。扫描件或图片PDF暂不支持OCR，请改用文字版PDF或Word。')
    if len(text)>MAX_CHARS:raise ValueError('文件文字超过30,000字，请精简后上传。')
    return text

def isolated_extract(data,ext):
    try:
        p=subprocess.run([sys.executable,str(Path(__file__).resolve()),ext],input=data,capture_output=True,timeout=20)
    except subprocess.TimeoutExpired:raise ValueError('文档解析超时，请精简文档或改用文字格式。')
    if p.returncode:raise ValueError('文档解析失败，请检查文件是否完整。')
    result=json.loads(p.stdout.decode('utf8'))
    if 'error' in result:raise ValueError(result['error'])
    return result['text']

def install_documents(app):
    @app.post('/documents/extract')
    async def import_document(request:Request,filename:str):
        ext=Path(filename).suffix.lower().lstrip('.')
        if ext not in ['pdf','docx','txt','md']:raise HTTPException(415,'支持Word(.docx)、PDF、TXT和Markdown；旧版.doc请先另存为.docx。')
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>MAX_BYTES:raise HTTPException(413,'单个文件不能超过5MB。')
            chunks.append(chunk)
        try:text=await asyncio.to_thread(isolated_extract,b''.join(chunks),ext)
        except ValueError as exc:raise HTTPException(422,str(exc))
        return {'filename':Path(filename).name,'text':text,'characters':len(text)}

if __name__=='__main__':
    try:result={'text':extract(sys.stdin.buffer.read(MAX_BYTES+1),sys.argv[1])}
    except Exception as exc:result={'error':str(exc) if isinstance(exc,ValueError) else '文档格式损坏或不支持，请重新导出。'}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf8'))
