"""Interface da fonte de mensagens.

Tudo o que fica acima deste arquivo — normalização, triagem da IA, caixa
de entrada — não sabe de onde veio a mensagem. Este é o ponto de extensão:
na segunda fase o WhatsApp entra nesta mesma interface, sem reescrever nada.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class RawAttachment:
    filename: str
    content_type: str
    size_bytes: int
    fetch: Callable[[], Awaitable[bytes]]


@dataclass(slots=True)
class RawMessage:
    """A mensagem como a fonte entregou — antes da normalização e da triagem."""

    provider_message_id: str
    sender: str
    subject: str
    body_text: str
    sent_at: datetime | None = None
    thread_id: str | None = None
    sender_name: str = ""
    recipients: list[str] = field(default_factory=list)
    attachments: list[RawAttachment] = field(default_factory=list)
    # De onde veio o e-mail: "inbox" ou "spam". O spam também é baixado — um
    # e-mail importante que caiu no spam o sistema tem que mostrar, não perder.
    folder: str = "inbox"
    # Cabeçalho Reply-To: para onde pedem a resposta, se não for o remetente.
    reply_to: str | None = None


class MailSource(ABC):
    @abstractmethod
    async def verify(self) -> None:
        """Verificar se a conexão funciona.

        Lança MailAuthError ou MailHostError com um texto que pode ser
        mostrado ao usuário.
        """

    @abstractmethod
    async def fetch_since(self, cursor: str | None) -> tuple[list[RawMessage], str]:
        """Devolver as mensagens que surgiram depois de cursor, e o novo cursor.

        O cursor é opaco para quem chama: cada fonte guarda nele o que
        precisa. A primeira chamada chega com cursor=None.
        """
