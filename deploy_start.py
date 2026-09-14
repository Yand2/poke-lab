"""Run the private API and public Streamlit process in one container."""
import os,signal,subprocess,sys,time,urllib.request
from pathlib import Path

def main():
    children=[]
    def stop(*_):
        for child in children:
            if child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    os.environ['POKE_API_URL']='http://127.0.0.1:8765'
    if os.environ.get('REQUIRE_POSTGRES')=='1' and not os.environ.get('DATABASE_URL'):
        raise RuntimeError('Configure DATABASE_URL before deployment')
    try:
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','backend:app','--host','127.0.0.1','--port','8765']))
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            if children[0].poll() is not None:raise RuntimeError('Backend failed to start')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=20):break
            except OSError:time.sleep(1)
        else:raise RuntimeError('Backend startup timeout')
        children.append(subprocess.Popen([sys.executable,'-m','streamlit','run','app.py','--server.address','0.0.0.0','--server.port',os.getenv('PORT','8501'),'--server.enableXsrfProtection','true','--server.enableCORS','true']))
        while all(c.poll() is None for c in children):time.sleep(.5)
    finally:
        stop()
        for c in children:
            try:c.wait(timeout=10)
            except subprocess.TimeoutExpired:c.kill();c.wait()
    return 1
if __name__=='__main__':sys.exit(main())
