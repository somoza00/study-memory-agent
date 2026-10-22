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

# Usuário non-root fixo (UID/GID 10001), mesmo padrão do Dockerfile do
# frontend (`USER node`) e do backend do evaluation-framework (`appuser`).
# Sem isto a API rodava como root: qualquer RCE na aplicação virava root no
# container. O diretório de cache já nasce com dono do appuser, para que um
# volume NOVO herde a permissão certa.
RUN addgroup --system --gid 10001 appuser \
    && adduser --system --uid 10001 --ingroup appuser --no-create-home --disabled-password appuser \
    && mkdir -p /app/.cache/fastembed \
    && chown -R appuser:appuser /app/.cache \
    && chmod -R a+rX /app \
    && chmod 755 /app/docker-entrypoint.sh

# O entrypoint começa como root apenas para acertar o dono do volume de cache
# (um volume criado por uma versão anterior, que rodava como root, fica
# root-owned — e aí o appuser não conseguiria gravar os pesos do embedding) e
# imediatamente reexecuta o CMD como `appuser`, sem deixar processo root.
ENTRYPOINT ["/app/docker-entrypoint.sh"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
