# Hugging Face Space: builds Amanah straight from the GitHub repository.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    AMANAH_LLM=none AMANAH_EMBEDDINGS=off AMANAH_DB=/tmp/amanah.db PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user

USER user
WORKDIR /home/user
RUN git clone --depth 1 https://github.com/Ayshalubna/amanah.git app
WORKDIR /home/user/app
RUN pip install --user -r requirements.txt
ENV PATH=/home/user/.local/bin:$PATH
RUN python -m scripts.train_model \
    && python -c "from amanah import graph, overview; graph.ctx(); overview.screening_all()"

EXPOSE 7860
CMD ["sh", "-c", "uvicorn amanah.api:api --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
