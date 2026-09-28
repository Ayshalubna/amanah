# Production image: builds data, model and caches at build time so the container starts in seconds.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    AMANAH_LLM=none AMANAH_EMBEDDINGS=off AMANAH_DB=/tmp/amanah.db PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user

WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=user . .
USER user

# Synthetic data, risk model, feature cache and screening cache are all built into the image.
RUN python -m scripts.train_model \
    && python -c "from amanah import graph, overview; graph.ctx(); overview.screening_all()"

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"

# One worker on purpose: the human-in-the-loop graph keeps paused cases in process memory.
CMD ["sh", "-c", "uvicorn amanah.api:api --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 30"]
