#!/bin/sh
# Entrypoint do backend: garante que o volume de cache do embedding pertence ao
# usuário non-root e então executa o comando como `appuser`.
#
# A imagem roda como `appuser` (UID 10001), mas um volume nomeado criado por
# uma versão anterior (que rodava como root) continua com dono root. Nesse
# caso o fastembed não consegue gravar os pesos do embedding local e o
# provedor `EMBEDDING_PROVIDER=local` quebra em runtime. O container começa
# como root só para corrigir a posse e cai para `appuser` no mesmo processo
# (setpriv), então nenhum processo da aplicação roda como root.
set -e

if [ "$(id -u)" = "0" ]; then
    cache_dir="${EMBEDDING_CACHE_DIR:-/app/.cache/fastembed}"
    mkdir -p "$cache_dir"
    if ! chown -R appuser:appuser /app/.cache 2>/dev/null; then
        echo "aviso: não foi possível ajustar o dono de /app/.cache (mount read-only?)" >&2
    fi
    exec setpriv --reuid=appuser --regid=appuser --clear-groups "$@"
fi

exec "$@"
