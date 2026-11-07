FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências primeiro, para aproveitar o cache de camadas
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY frontend ./frontend
COPY data ./data
COPY scripts ./scripts
COPY tests ./tests

# logs/ e docs/ graváveis pelo usuário da aplicação (logs da API e relatório do scripts.avaliar)
RUN useradd --create-home --uid 1000 aurora && mkdir -p /app/logs /app/docs && chown -R aurora /app/logs /app/docs
USER aurora

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
