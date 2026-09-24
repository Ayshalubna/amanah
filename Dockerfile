FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -m amanah.synth && python -m scripts.train_model
EXPOSE 8000 8501
CMD ["uvicorn", "amanah.api:api", "--host", "0.0.0.0", "--port", "8000"]
