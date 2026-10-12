# BR BOSS

Central inteligente de e-mails: conecta todas as suas caixas de entrada
(Gmail, Outlook/Hotmail, UOL, BOL, Terra, Yahoo, iCloud e qualquer e-mail com
IMAP), a IA analisa cada mensagem e mostra tudo em uma única lista — no topo,
o que é mais caro deixar para depois.

## O que o BR BOSS faz

- **Resumo diário** — toda manhã: o que exige atenção, quem espera resposta,
  o que pagar nesta semana, e uma introdução curta escrita pela IA.
- **Caixa de entrada unificada** — todas as caixas em uma lista, com índice de
  importância (0–100), categoria, resumo em uma linha, valor e prazo.
- **Abas por categoria** — Urgente, Pagamentos, Bancos, Jurídico, Renovações,
  Tarefas, Pessoal, Publicidade, Segurança, Spam.
- **Resposta inteligente** — a IA prepara um rascunho no idioma do remetente;
  você revisa e envia direto do site, pela mesma caixa que recebeu o e-mail.
- **Lembrar / Ignorar** — o e-mail some da lista e volta amanhã, em 3 dias ou
  em uma semana; ou é marcado como resolvido.
- **Dinheiro e prazos** — todas as faturas e vencimentos em uma tabela por data.
- **Regras em linguagem natural** — «Tudo de advogados é importante»,
  «Esconder anúncios de imóveis»; a IA transforma a frase em regra.
- **Busca** em todas as caixas ao mesmo tempo (Ctrl+K).
- **Tradução para o português** — e-mails em outros idiomas são traduzidos
  pelo DeepL (ou pelo tradutor próprio do servidor, sem custo).
- **Cadastro pelo link** — cada pessoa vê apenas os próprios e-mails.
- **Chave de IA própria** — cada usuário pode usar a própria chave Gemini.

## Como rodar

```bash
cp .env.example .env
docker compose run --rm api python -c "from app.crypto import generate_key; print(generate_key())"
# coloque a chave em SECRET_ENCRYPTION_KEY e invente DB_PASSWORD e S3_PASSWORD
docker compose up -d
docker compose exec api alembic upgrade head
curl http://127.0.0.1:8080/health
```

Interface: http://localhost (ou a porta definida em `WEB_PORT`). API na 8080.

## Acessos

Há dois tipos de acesso.

- **Equipe (owner)** — criados manualmente pelo comando abaixo; a senha é
  mostrada uma única vez. Compartilham a mesma caixa, as regras e a chave de
  IA do servidor.
- **Cadastrados pelo link (member)** — pelo link «Criar conta» na página de
  login (desligue com `REGISTRATION_OPEN=false`). Veem apenas as próprias
  caixas, e-mails, regras e resumo; a equipe não vê os e-mails deles, nem eles
  os da equipe. Usam a própria chave Gemini (página «Chave de IA»), a não ser
  que `AI_SHARED_KEY=true`.

```bash
docker compose exec api python -m app.admin add voce@exemplo.com.br
docker compose exec api python -m app.admin password voce@exemplo.com.br   # nova senha
docker compose exec api python -m app.admin drop-totp voce@exemplo.com.br  # celular perdido
```

O código de verificação (Google Authenticator ou similar) é ativado dentro do
sistema e só é salvo depois que a pessoa digita o primeiro código.

## Testes

```bash
bash scripts/test.sh                       # backend, em banco de testes separado
docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine npm test   # frontend
sh scripts/smoke.sh <e-mail> <senha>       # sistema no ar, de fora
```

## Importante

**`SECRET_ENCRYPTION_KEY` é a única coisa que não pode ser perdida.** Com ela
são criptografadas as senhas de todas as caixas conectadas e as chaves de IA
dos usuários. Sem ela, será preciso criar de novo as senhas de app de todas as
caixas. Guarde uma cópia fora do servidor. (`AUTH_SECRET` pode ser perdido —
basta todos entrarem de novo.)

O projeto é isolado do resto do servidor: rede própria, volumes próprios,
prefixo de nomes próprio (`name: brboss`). Para fora fica só `127.0.0.1` —
quem publica na internet é um reverse proxy externo (nginx) com https.

## Mudança de servidor

Dois comandos; detalhes em [docs/MIGRACAO.md](docs/MIGRACAO.md).

```bash
sh scripts/backup.sh                                   # no servidor antigo
sh scripts/restore.sh backups/br-boss-....tar.gz       # no novo
```

**O arquivo de backup é um segredo.** Dentro dele está o `.env` com a chave
de criptografia, ou seja, acesso a todos os e-mails. Guarde como uma senha.

## Segurança

Antes de publicar na internet: senha forte, código de verificação ativado,
`COOKIE_SECURE=true`, https na frente e nenhuma porta do projeto aberta
diretamente para fora.
