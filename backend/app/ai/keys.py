"""De quem é a chave que paga a requisição ao modelo.

O servidor tem a própria chave (no .env), e cada usuário pode ter uma
chave pessoal do Gemini. A regra é uma só: paga quem é dono do e-mail ou
da ação. Os e-mails de uma caixa são analisados com a chave do dono da
caixa; rascunho e regra, com a chave de quem apertou o botão. Sem chave
pessoal, vale a chave do servidor, se o servidor a compartilha
(AI_SHARED_KEY).

A chave não é passada pela cadeia de chamadas: fica no contexto da
tarefa. Triagem, rascunho e resumo não precisam saber de onde ela veio.
Cada tarefa asyncio tem seu próprio contexto, então as chaves de tarefas
paralelas não se misturam.
"""

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import decrypt_secret
from app.models import User

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIKey:
    # Chave pessoal do Gemini; None — vale a chave do servidor.
    personal: str | None = None
    # De quem é a pausa: "" — da chave do servidor, "user:7:…" — da chave
    # pessoal do usuário 7. Se a cota de uma chave acaba, as outras seguem.
    scope: str = ""
    # False — não há chave pessoal e é proibido usar a do servidor.
    allowed: bool = True


SERVER = AIKey()
_NONE = AIKey(allowed=False)

_current: ContextVar[AIKey] = ContextVar("ai_key", default=SERVER)


def current() -> AIKey:
    return _current.get()


def use(key: AIKey) -> None:
    _current.set(key)


@contextmanager
def using(key: AIKey) -> Iterator[AIKey]:
    """Usar a chave durante o bloco e depois devolver a anterior. Para
    trechos que rodam numa tarefa longa (o ciclo do worker): lá a chave
    não pode ficar pendurada."""
    token = _current.set(key)
    try:
        yield key
    finally:
        _current.reset(token)


def scope_of(user: User | None) -> str:
    """De quem é a cota que o e-mail desta pessoa consome. Sem descriptografar.

    O nome leva a impressão digital da chave salva: se a cota da pessoa
    acabou e ela cola uma chave nova, a pausa da antiga não a segura.
    """
    if user is not None and user.ai_key_ciphertext:
        mark = hashlib.sha256(user.ai_key_ciphertext.encode()).hexdigest()[:8]
        return f"user:{user.id}:{mark}"
    return ""


def may_use_server_key(user: User | None) -> bool:
    """A chave do servidor vale sempre para a equipe; para quem se cadastrou
    sozinho, só se o servidor permitir (AI_SHARED_KEY). Senão qualquer
    desconhecido com o link gastaria as requisições do dono do servidor."""
    if user is not None and user.role == "owner":
        return True
    return settings.ai_shared_key


def key_of(user: User | None) -> AIKey:
    if user is not None and user.ai_key_ciphertext:
        try:
            return AIKey(personal=decrypt_secret(user.ai_key_ciphertext), scope=scope_of(user))
        except ValueError:
            # A chave de criptografia do servidor mudou — a chave pessoal
            # fica ilegível. A pessoa verá «sem chave» e vai cadastrá-la de novo.
            log.warning("não foi possível descriptografar a chave de IA pessoal do usuário %s", user.id)
    return SERVER if may_use_server_key(user) else _NONE


async def use_key_of(session: AsyncSession, user_id: int | None) -> AIKey:
    """Seguir nesta tarefa usando a chave desta pessoa."""
    user = await session.get(User, user_id) if user_id is not None else None
    key = key_of(user)
    use(key)
    return key


def hint(user: User) -> str | None:
    """Os quatro últimos caracteres da chave — para a pessoa reconhecer a
    própria chave sem vê-la inteira."""
    if not user.ai_key_ciphertext:
        return None
    try:
        return "…" + decrypt_secret(user.ai_key_ciphertext)[-4:]
    except ValueError:
        return None
