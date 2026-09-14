FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 POKE_DB=/data/poke.sqlite3 PORT=8501
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt && useradd --create-home --uid 10001 poke && mkdir /data && chown poke:poke /data
COPY --chown=poke:poke *.py ./
COPY --chown=poke:poke style.css ./
COPY --chown=poke:poke .streamlit/config.toml .streamlit/config.toml
USER poke
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=3)"
CMD ["python", "deploy_start.py"]
