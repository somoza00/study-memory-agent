FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# curl é exigido pelo healthcheck do Docker Compose
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Camada de dependências cacheada (pyproject + pacote presente p/ `pip install .`)
COPY pyproject.toml ./
COPY README.md ./
COPY app ./app
# `local-embeddings` instala o fastembed/onnxruntime: sem ele o provedor de
# embeddings local (EMBEDDING_PROVIDER=local) não sobe no container.
RUN pip install --no-cache-dir ".[local-embeddings]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
