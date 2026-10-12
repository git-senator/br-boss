#!/usr/bin/env sh
# Restaurar o sistema a partir de um backup — aqui mesmo ou em outro servidor.
#
#   sh scripts/restore.sh backups/br-boss-2026-10-12-1930.tar.gz
#
# No servidor novo só é preciso ter o Docker instalado e a pasta do projeto.
# Todo o resto vem dentro do arquivo.
set -eu

export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/.."
ARCHIVE="${1:?informe o arquivo: sh scripts/restore.sh backups/br-boss-....tar.gz}"
[ -f "$ARCHIVE" ] || { echo "Arquivo não encontrado: $ARCHIVE"; exit 1; }

case "$ARCHIVE" in
    /*) ARCHIVE_PATH="$ARCHIVE" ;;
    *) ARCHIVE_PATH="$PWD/$ARCHIVE" ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar xzf "$ARCHIVE_PATH" -C "$WORK"

echo "Configurações..."
cp "$WORK/.env" .env

echo "Parando o sistema, o banco continua..."
docker compose stop api worker web 2>/dev/null || true
docker compose up -d db minio
until docker compose exec -T db pg_isready -U boss >/dev/null 2>&1; do sleep 1; done

echo "Banco de dados..."
# --clean --if-exists: o conteúdo antigo é apagado, então o comando pode ser
# repetido sem misturar o antigo com o novo.
docker compose exec -T db pg_restore -U boss -d boss --clean --if-exists < "$WORK/db.dump"

echo "Anexos..."
docker run --rm -i -v brboss_minio_data:/data alpine \
    sh -c 'rm -rf /data/..?* /data/.[!.]* /data/* 2>/dev/null; tar xzf - -C /data' \
    < "$WORK/attachments.tar.gz"

echo "Iniciando..."
docker compose up -d --build

echo "Verificando..."
API_PORT="$(grep -E '^API_PORT=' .env | cut -d= -f2 | tr -d '\r')"
until curl -sf "http://127.0.0.1:${API_PORT:-8080}/health" >/dev/null 2>&1; do sleep 1; done
echo "Sistema no ar. Backup feito da versão $(cat "$WORK/commit.txt")."
