FROM python:3.11.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /reader
COPY layout_reader/requirements.txt layout_reader/requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt -c requirements.lock && pip freeze > /reader/resolved-requirements.txt
COPY layout_reader/compat.py /reader/
RUN python compat.py
COPY layout_reader/prepare.py layout_reader/runtime.py /reader/
ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PADDLE_PDX_MODEL_SOURCE=BOS PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
RUN --mount=type=cache,target=/model-download-cache python prepare.py
COPY layout_reader/server.py /reader/
RUN useradd --uid 10001 --create-home reader && chmod -R a+rX /opt/philixa-models
USER reader
ENV HOME=/home/reader
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8097", "--workers", "1"]
