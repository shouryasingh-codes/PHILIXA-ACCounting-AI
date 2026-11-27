# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

WORKDIR /app

# Force UTF-8 encoding for Python (fixes garbled emoji in Docker/Gunicorn)
ENV PYTHONUTF8=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN sed -i 's/http:/https:/g' /etc/apt/sources.list.d/debian.sources && apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt requirements-documents.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir python-jose[cryptography] passlib[bcrypt] itsdangerous && \
    pip install --no-cache-dir -r requirements-documents.txt
ENV TIKTOKEN_CACHE_DIR=/opt/philixa-tokenizers
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')"

COPY README.md .
COPY app ./app

# ENV vars are provided via docker-compose env_file (.env) at runtime

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["gunicorn", "app.main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "60", "--graceful-timeout", "30"]
