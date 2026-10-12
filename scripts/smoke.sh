#!/usr/bin/env sh
# Teste do sistema no ar, de fora: login pelo formulário comum, páginas, saída.
#
# O formulário é enviado sem JavaScript — como um navegador com scripts
# desligados ou com conexão ruim enviaria. Se isso parar de funcionar,
# é aqui que vai quebrar.
#
#   sh scripts/smoke.sh <e-mail> <senha> [endereço]
set -eu

EMAIL="${1:?informe o e-mail}"
PASSWORD="${2:?informe a senha}"
WEB="${3:-http://localhost}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

check() {
    printf '%s' "$3" | grep -qF "$2" && echo "  ok: $1" || {
        echo "  FALHA: $1 — não encontrei «$2»"
        exit 1
    }
}

echo "Página de login"
page="$(curl -sS "$WEB/login")"
check "formulário de login" "Entrar" "$page"

action="$(printf '%s' "$page" | grep -o 'ACTION_ID_[A-Za-z0-9_]*' | head -1)"
[ -n "$action" ] || { echo "  FALHA: o formulário não é enviado sem JavaScript"; exit 1; }

echo "Login"
curl -sS -c "$JAR" -o /dev/null -X POST "$WEB/login" \
    -F "\$$action=" -F "email=$EMAIL" -F "password=$PASSWORD" -F "code="
grep -q boss_token "$JAR" || { echo "  FALHA: o login não deu certo"; exit 1; }
echo "  ok: token recebido e guardado no cookie"

echo "Caixa de entrada"
page="$(curl -sS -b "$JAR" "$WEB/")"
check "a lista abriu" "Caixa de entrada" "$page"

echo "Resumo"
page="$(curl -sS -b "$JAR" "$WEB/brief")"
check "o resumo abriu" "Exigem atenção" "$page"

echo "Caixas de e-mail"
page="$(curl -sS -b "$JAR" "$WEB/accounts")"
check "página das caixas" "Caixas de e-mail" "$page"
check "formulário de conexão" "Adicionar e-mail" "$page"
check "campo para a lista de caixas" "uma por linha" "$page"

echo "Sem login"
code="$(curl -sS -o /dev/null -w '%{http_code}' "$WEB/accounts")"
[ "$code" = "307" ] || { echo "  FALHA: sem login recebeu $code em vez de redirecionamento"; exit 1; }
echo "  ok: sem login as páginas ficam fechadas"

echo "Tudo certo."
