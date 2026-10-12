# Mudança de servidor

O sistema foi feito desde o primeiro dia para mudar de servidor: tudo roda em
Docker, todas as configurações ficam em um único arquivo `.env`, nada depende
de uma hospedagem específica. A mudança leva uns vinte minutos, a maior parte
esperando o build.

## O que o novo servidor precisa

- Docker e Docker Compose.
- 2 núcleos, 4 GB de memória, 40 GB de disco (mais ~2,5 GB se usar o
  tradutor próprio) — com folga para 25 caixas.
- A porta pública fica com um reverse proxy externo (nginx). O sistema escuta
  só em `127.0.0.1`: `WEB_PORT` — interface, 8080 — API.

Mais nada. Não é preciso instalar banco, Python nem Node no servidor.

## A mudança

No servidor antigo:

```bash
sh scripts/backup.sh
```

Sai um arquivo como `backups/br-boss-2026-10-12-1958.tar.gz`, com o banco,
os anexos e as configurações.

Leve a pasta do projeto e esse arquivo para o novo servidor e rode:

```bash
sh scripts/restore.sh backups/br-boss-2026-10-12-1958.tar.gz
```

O script sobe o banco, carrega os dados, faz o build, inicia o sistema e
espera ele responder. Depois disso tudo funciona como antes: as mesmas
caixas, os mesmos e-mails, os mesmos acessos e senhas.

## Teste antes da mudança de verdade

```bash
sh scripts/test-migration.sh --sim-destruir
```

O script grava uma marca no banco, faz o backup, **destrói o sistema por
completo** (`docker compose down -v`) e sobe tudo de novo a partir do backup;
no fim confere se a marca voltou e se a senha da caixa ainda é descriptografada.

## O backup é um segredo

Dentro do arquivo está o `.env`, e nele a `SECRET_ENCRYPTION_KEY` — a chave
que protege as senhas de todas as caixas. Quem tem o arquivo tem acesso a
todos os e-mails.

- Não suba para a nuvem sem senha, não envie por e-mail.
- Guarde como se guarda uma senha.
- A pasta `backups/` não entra no git — de propósito.

## O que não muda sozinho

Nenhum dado fica para trás. Mas duas coisas externas precisam ser
configuradas de novo:

1. **Reverse proxy e domínio** no novo servidor — o sistema não fica exposto
   sozinho.
2. **Backup agendado** — se no servidor antigo havia cron, no novo é uma linha:

```
30 3 * * * cd /caminho/do/projeto && sh scripts/backup.sh >> backups/log.txt 2>&1
```

## Se algo der errado

O `restore.sh` pode ser rodado de novo: ele apaga o conteúdo do banco por
inteiro em vez de somar ao que existe. Não sai mistura de antigo e novo.

Se o sistema não subiu, veja os logs:

```bash
docker compose logs --tail 50 api
docker compose logs --tail 50 web
```
