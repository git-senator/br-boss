"""Esquemas das respostas do modelo.

O modelo responde estritamente pelo esquema — não é um pedido no prompt,
e sim uma restrição no nível da API. Portanto, a leitura da resposta não
pode quebrar porque o modelo resolveu de repente escrever em prosa.
"""

# Categorias da especificação. A ordem só importa para a interface.
CATEGORIES = [
    "urgent",  # justiça, órgãos públicos, bloqueios, prazo estourando
    "payments",  # faturas, boleto, invoice, contas de consumo
    "banks",  # bancos: transferências, pedidos de documentos, KYC
    "legal",  # advogados, contratos, notificações extrajudiciais
    "renewals",  # domínios, licenças, assinaturas, seguros
    "business",  # correspondência de trabalho sem urgência
    "personal",  # pessoal
    "low",  # notificações de serviços, e-mails automáticos
    "ads",  # envios em massa e marketing: para muita gente, sem esperar resposta
    "security",  # login na conta, senhas, códigos, atividade suspeita
]

# Publicidade é a única categoria que a lista geral esconde. O nome fica
# numa constante para essa regra morar num lugar só, e não como a string
# "ads" espalhada por filtros e contadores.
ADS = "ads"

# A pasta de spam não é uma categoria, e sim um lugar. Um e-mail de lá
# pode ter qualquer conteúdo, por isso a aba é separada e não entra em "Tudo".
SPAM = "spam"

# Marca "e-mail ainda não triado" para o filtro e os contadores. De propósito
# não está em CATEGORIES: o modelo não pode ter a possibilidade de devolvê-la.
# No banco, corresponde a category IS NULL.
UNSORTED = "none"

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": CATEGORIES,
            "description": "Categoria do e-mail.",
        },
        "priority": {
            "type": "integer",
            "description": (
                "Importância 0-100. 95-100 mostrar imediatamente, 80-94 importante, "
                "50-79 normal, 20-49 baixa prioridade, 10-30 notificações de "
                "serviços, 0-9 envios em massa e publicidade."
            ),
        },
        "summary": {
            "type": "string",
            "description": "Essência do e-mail em uma frase, em português do Brasil.",
        },
        "deadline": {
            "type": ["string", "null"],
            "description": "Prazo no formato AAAA-MM-DD, se o e-mail o menciona. Senão, null.",
        },
        "amount": {
            "type": ["string", "null"],
            "description": "Valor a pagar como número, ponto como separador decimal. Senão, null.",
        },
        "currency": {
            "type": ["string", "null"],
            "description": "Moeda do valor: BRL, USD, EUR, RUB, AED. Senão, null.",
        },
        "action_required": {
            "type": "boolean",
            "description": "Se esperam do destinatário uma resposta ou uma ação.",
        },
    },
    "required": ["category", "priority", "summary", "action_required"],
    "additionalProperties": False,
}
