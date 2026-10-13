"""Erros de conexão com o e-mail, prontos para mostrar ao usuário.

As 25 caixas vão ser conectadas à mão. Uma mensagem como
«[AUTHENTICATIONFAILED] Invalid credentials» não diz nada para a pessoa —
é preciso explicar o que fazer e dar o link direto para onde isso se faz.
"""


class MailError(Exception):
    """Erro base de e-mail. O texto pode ser mostrado como está."""

    def __init__(self, message: str, hint: str = "", help_url: str = "") -> None:
        super().__init__(message)
        self.hint = hint
        self.help_url = help_url


class MailAuthError(MailError):
    """Acesso negado: a senha não funcionou ou o IMAP está desativado nas configurações."""


class MailHostError(MailError):
    """Não chegamos ao servidor: endereço errado, sem rede, servidor sem resposta."""


BAD_PASSWORD = (
    "A senha de app não funcionou. Confira se a verificação em duas etapas está "
    "ativada nas configurações do e-mail e crie uma nova senha de app — a senha "
    "normal da caixa de e-mail não funciona aqui."
)

IMAP_DISABLED = (
    "O provedor de e-mail não permitiu o acesso por IMAP. Ative o IMAP nas configurações "
    "da caixa de e-mail — normalmente na seção «Encaminhamento e POP/IMAP» ou «Acesso ao e-mail»."
)


PASSWORD_LOGIN_OFF = (
    "Este provedor não aceita mais conexão por senha — só pelo login da conta "
    "(a Microsoft desligou isso no Outlook e no Hotmail). Por enquanto, ative o "
    "encaminhamento automático dos e-mails para um Gmail e conecte o Gmail aqui."
)


def unreachable(host: str) -> str:
    return (
        f"Não foi possível conectar ao servidor {host}. Confira o endereço do servidor — "
        "em e-mails com domínio próprio ele pode ser diferente do padrão."
    )
