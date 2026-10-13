"""Configurações dos provedores de e-mail.

O usuário conecta duas dezenas e meia de caixas de e-mail na mão. A tarefa
deste arquivo é poupá-lo de procurar na internet qual é o servidor do UOL ou
onde o Google esconde as senhas de app: o sistema mostra a dica e o link direto.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    key: str
    label: str
    imap_host: str
    smtp_host: str
    help_url: str
    password_hint: str = ""
    imap_port: int = 993
    smtp_port: int = 465
    # Se o próprio provedor guarda a cópia do e-mail enviado por SMTP na pasta
    # «Enviados». Gmail e Outlook guardam, e uma cópia nossa seria duplicada.
    # Nos demais e no domínio próprio é incerto; lá guardamos a cópia nós
    # mesmos, senão a resposta não aparece na própria caixa.
    saves_sent: bool = False


_GOOGLE = ProviderProfile(
    key="google",
    label="Google",
    imap_host="imap.gmail.com",
    smtp_host="smtp.gmail.com",
    saves_sent=True,
    help_url="https://myaccount.google.com/apppasswords",
    password_hint=(
        "Ative a verificação em duas etapas e depois crie uma senha de app. "
        "Sem a verificação em duas etapas essa opção não aparece nas configurações."
    ),
)

_MICROSOFT = ProviderProfile(
    key="microsoft",
    label="Microsoft",
    imap_host="outlook.office365.com",
    smtp_host="smtp.office365.com",
    smtp_port=587,
    saves_sent=True,
    help_url="https://outlook.live.com/mail/0/options/mail/forwarding",
    # A Microsoft desligou o acesso por senha (IMAP) no Outlook e no Hotmail:
    # o servidor só aceita OAuth. Senha de app não resolve.
    password_hint=(
        "A Microsoft não aceita mais conexão por senha. Ative o encaminhamento "
        "automático do Outlook para um Gmail e conecte o Gmail."
    ),
)

_UOL = ProviderProfile(
    key="uol",
    label="UOL",
    imap_host="imap.uol.com.br",
    smtp_host="smtp.uol.com.br",
    smtp_port=587,
    help_url="https://email.uol.com.br",
    password_hint=(
        "Use a senha do UOL Mail. Se a verificação em duas etapas estiver ativa, "
        "crie uma senha de aplicativo nas configurações de segurança da conta UOL."
    ),
)

_BOL = ProviderProfile(
    key="bol",
    label="BOL",
    imap_host="imap.bol.com.br",
    smtp_host="smtps.bol.com.br",
    smtp_port=587,
    help_url="https://email.bol.uol.com.br",
    password_hint=(
        "Use a senha do BOL Mail. Se a verificação em duas etapas estiver ativa, "
        "crie uma senha de aplicativo nas configurações de segurança da conta."
    ),
)

_TERRA = ProviderProfile(
    key="terra",
    label="Terra",
    imap_host="imap.terra.com.br",
    smtp_host="smtp.terra.com.br",
    smtp_port=587,
    help_url="https://mail.terra.com.br",
    password_hint=(
        "Use a senha do Terra Mail e confira nas configurações do webmail "
        "se o acesso por IMAP está liberado."
    ),
)

_YAHOO = ProviderProfile(
    key="yahoo",
    label="Yahoo",
    imap_host="imap.mail.yahoo.com",
    smtp_host="smtp.mail.yahoo.com",
    help_url="https://login.yahoo.com/account/security",
    password_hint=(
        "Segurança da conta → Gerar senha de app. "
        "A senha normal do Yahoo não funciona em programas de e-mail."
    ),
)

_MAILRU = ProviderProfile(
    key="mailru",
    label="Mail.ru",
    imap_host="imap.mail.ru",
    smtp_host="smtp.mail.ru",
    help_url="https://account.mail.ru/user/2-step-auth/passwords",
    password_hint="Senhas para aplicativos externos — criar senha.",
)

_YANDEX = ProviderProfile(
    key="yandex",
    label="Yandex",
    imap_host="imap.yandex.ru",
    smtp_host="smtp.yandex.ru",
    help_url="https://id.yandex.ru/security/app-passwords",
    password_hint=(
        "Senhas de app → E-mail. Confira se o acesso por IMAP "
        "está permitido nas configurações do e-mail."
    ),
)

_BY_DOMAIN: dict[str, ProviderProfile] = {
    "gmail.com": _GOOGLE,
    "googlemail.com": _GOOGLE,
    "outlook.com": _MICROSOFT,
    "outlook.com.br": _MICROSOFT,
    "hotmail.com": _MICROSOFT,
    "hotmail.com.br": _MICROSOFT,
    "live.com": _MICROSOFT,
    "msn.com": _MICROSOFT,
    "uol.com.br": _UOL,
    "bol.com.br": _BOL,
    "terra.com.br": _TERRA,
    "yahoo.com": _YAHOO,
    "yahoo.com.br": _YAHOO,
    "mail.ru": _MAILRU,
    "bk.ru": _MAILRU,
    "inbox.ru": _MAILRU,
    "list.ru": _MAILRU,
    "internet.ru": _MAILRU,
    "yandex.ru": _YANDEX,
    "yandex.com": _YANDEX,
    "ya.ru": _YANDEX,
}


def known_services() -> list[ProviderProfile]:
    """Provedores que têm dica — para a lista na interface."""
    seen: dict[str, ProviderProfile] = {}
    for profile in _BY_DOMAIN.values():
        seen.setdefault(profile.key, profile)
    return list(seen.values())


def profile_for(email: str) -> ProviderProfile:
    domain = email.rsplit("@", 1)[-1].lower()
    known = _BY_DOMAIN.get(domain)
    if known is not None:
        return known
    # E-mail com domínio próprio: na grande maioria funciona imap.<domínio>.
    # Se não funcionar, o usuário verá um erro claro com o nome do servidor.
    return ProviderProfile(
        key="other",
        label="Outro e-mail",
        imap_host=f"imap.{domain}",
        smtp_host=f"smtp.{domain}",
        help_url="",
        password_hint=(
            "Pergunte ao administrador do e-mail qual é o endereço do servidor IMAP "
            "e crie uma senha para aplicativo externo."
        ),
    )
