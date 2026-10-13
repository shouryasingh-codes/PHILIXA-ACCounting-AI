# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

WORKDIR /app

# Force UTF-8 encoding for Python (fixes garbled emoji in Docker/Gunicorn)
ENV PYTHONUTF8=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN sed -i 's/http:/https:/g' /etc/apt/sources.list.d/debian.sources && apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY README.md .

# ENV vars are provided via docker-compose env_file (.env) at runtime

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["gunicorn", "app.main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "60", "--graceful-timeout", "30"]

RUN pip install --no-cache-dir python-jose[cryptography] passlib[bcrypt] itsdangerous
COPY requirements-documents.txt .
RUN pip install --no-cache-dir -r requirements-documents.txt
