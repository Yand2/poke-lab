"""Run the independent UI and authenticated API in one server process."""
import os,sys

def main():
    if os.environ.get('REQUIRE_POSTGRES')=='1' and not os.environ.get('DATABASE_URL'):
        raise RuntimeError('Configure DATABASE_URL before deployment')
    os.execv(sys.executable,[sys.executable,'-m','uvicorn','web_app:app','--host','0.0.0.0','--port',os.getenv('PORT','8501')])
if __name__=='__main__':main()
