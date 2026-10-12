"""Os modelos e para que serve cada um.

O único lugar do código onde aparecem nomes de modelos. Todo o resto se
refere a eles pelo papel — assim o modelo é trocado editando um só
arquivo, como pede a especificação.

Divisão por custo: o modelo barato faz a triagem do fluxo inteiro
(centenas de e-mails por dia); o inteligente só entra onde o erro sai
caro — rascunhos de resposta e análise de contratos.
"""

# Fluxo: categoria, prioridade, resumo. Centenas de chamadas por dia.
TRIAGE_MODEL = "claude-haiku-4-5"
TRIAGE_MAX_TOKENS = 1024

# Pontual: rascunhos de resposta, análise de faturas e contratos.
DRAFT_MODEL = "claude-sonnet-5"
DRAFT_MAX_TOKENS = 4000

# No botão: tradução do e-mail. A tradução é maior que o rascunho —
# é o e-mail inteiro, e não uma resposta curta.
TRANSLATE_MODEL = DRAFT_MODEL
TRANSLATE_MAX_TOKENS = 8000

# Quanto do texto do e-mail vai para a triagem. Depois disso vêm
# assinaturas e citações da conversa anterior — não acrescentam sentido,
# só gastam tokens.
BODY_CHARS_FOR_TRIAGE = 20_000
