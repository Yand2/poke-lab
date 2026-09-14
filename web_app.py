"""Independent browser UI served alongside the existing authenticated API."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import backend
ROOT=Path(__file__).resolve().parent
@asynccontextmanager
async def lifespan(app):
    async with backend.lifespan(backend.app):
        yield
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
@app.middleware('http')
async def security_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') or request.url.path=='/' else 'no-cache'
    return response
@app.get('/')
def index():return FileResponse(ROOT/'frontend/index.html')
@app.get('/_stcore/health')
def platform_health():return PlainTextResponse('ok')
app.mount('/assets',StaticFiles(directory=ROOT/'frontend'),name='assets')
app.mount('/api',backend.app)
