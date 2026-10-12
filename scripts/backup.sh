#!/usr/bin/env sh
# Cópia completa do sistema em um único arquivo: banco, anexos e configurações.
#
# ATENÇÃO: dentro do arquivo está o .env, e nele a chave que criptografa as
# senhas de todas as caixas. O backup é tão secreto quanto as próprias senhas.
# Não suba para a nuvem sem senha e não envie por e-mail.
#
#   sh scripts/backup.sh [pasta]
set -eu

# No Git Bash do Windows, sem isto os caminhos dentro do contêiner são
# reescritos (/data vira C:/Program Files/Git/data). No Linux não atrapalha.
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")/.."
OUT_DIR="${1:-backups}"
STAMP="$(date +%Y-%m-%d-%H%M)"
ARCHIVE="$OUT_DIR/br-boss-$STAMP.tar.gz"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$OUT_DIR"
# No servidor vivem outros projetos. O arquivo contém a chave de
# criptografia, ou seja, acesso a todos os e-mails — só o dono pode ler.
chmod 700 "$OUT_DIR" 2>/dev/null || true

echo "Banco de dados..."
docker compose exec -T db pg_dump -U boss -Fc boss > "$WORK/db.dump"

echo "Anexos..."
# O arquivo sai pelo stdout, não por uma pasta montada: assim o mesmo
# comando funciona no Linux e no Windows.
docker run --rm -v brboss_minio_data:/data alpine tar czf - -C /data . > "$WORK/attachments.tar.gz"

echo "Configurações..."
cp .env "$WORK/.env"

# Marca de versão: mostra de qual estado do código a cópia foi feita.
git rev-parse HEAD > "$WORK/commit.txt" 2>/dev/null || echo "desconhecida" > "$WORK/commit.txt"

tar czf "$ARCHIVE" -C "$WORK" .
chmod 600 "$ARCHIVE" 2>/dev/null || true
echo "Pronto: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
