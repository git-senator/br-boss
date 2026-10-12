#!/usr/bin/env bash
# Testes do backend em contêiner, em banco separado, com o código do disco.
#
# Quatro motivos para este script existir:
#
# 1. Banco próprio. O conftest faz drop_all/create_all a cada teste — no
#    banco de produção isso apagaria todos os e-mails.
# 2. Senha vinda do .env, não do padrão. Senão, depois de trocar a senha,
#    os testes falham na autenticação e parecem um defeito do código.
# 3. Código do disco, não da imagem. No docker-compose o api não monta o
#    código-fonte: ele é copiado no build. Sem trocar a pasta, os testes
#    verificariam em silêncio a versão anterior.
# 4. Saída por arquivo. O Docker no Windows perde o último pedaço da saída
#    do contêiner ao sair — junto com a linha final do pytest. Por isso a
#    saída vai para um arquivo na pasta montada e é lida do disco.
#
# Tudo o que for passado ao script vai para o pytest:
#   scripts/test.sh                    — todos os testes
#   scripts/test.sh tests/api -x       — só a API, até o primeiro erro
set -uo pipefail
cd "$(dirname "$0")/.."

export MSYS_NO_PATHCONV=1  # senão o Git Bash reescreve os caminhos dentro do contêiner

password=$(grep -E '^DB_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
: "${password:?não há DB_PASSWORD no .env}"

here=$(pwd -W 2>/dev/null || pwd)   # caminho no formato que o Docker entende
report=backend/.pytest-last.log

docker compose exec -T db psql -U boss -c "CREATE DATABASE boss_test" >/dev/null 2>&1 || true

# --user root: na imagem o sistema roda como o usuário sem privilégios boss,
# e no servidor Linux a pasta do código pertence ao root — o relatório do
# pytest não seria gravado. Este contêiner é só para testes, não fica exposto.
docker compose run --rm --no-deps -T --user root \
  -v "${here}/backend:/app" \
  -e TEST_DATABASE_URL="postgresql+asyncpg://boss:${password}@db:5432/boss_test" \
  api sh -c 'pytest -p no:cacheprovider "$@" > /app/.pytest-last.log 2>&1; echo "código de saída: $?" >> /app/.pytest-last.log' sh "$@" \
  >/dev/null 2>&1

tr -d '\r' < "$report"
grep -qE '^código de saída: 0$' "$report"
