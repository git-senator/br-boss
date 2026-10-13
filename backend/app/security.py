"""Login no sistema: senha mais o código do app autenticador.

São dois donos — o desenvolvedor e o dono do negócio —, ambos com acesso
total. Logins separados, e não um compartilhado: o registro tem que
mostrar quem fez o quê, e a passagem do projeto não exige trocar a senha
dos dois ao mesmo tempo.

A senha é guardada só como hash argon2; o código é verificado pelo padrão
TOTP — o mesmo do Google Authenticator.
"""

import hashlib
import time
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import Account, Rule, User

TOKEN_TTL = timedelta(days=7)
_ALGORITHM = "HS256"
_hasher = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)

_MISSING_SECRET = (
    'AUTH_SECRET não definido. Gere com: python -c "import secrets; '
    'print(secrets.token_urlsafe(48))" e coloque no .env'
)


def _secret() -> str:
    # Lemos na chamada, e não no import: senão um .env colocado na mudança
    # para outro servidor não seria visto pelo módulo já carregado.
    if not settings.auth_secret:
        raise ValueError(_MISSING_SECRET)
    return settings.auth_secret


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


# Hash de uma senha inexistente. Serve para que a resposta «esse login não
# existe» demore o mesmo que «senha incorreta»: senão, pelo tempo da
# resposta, dá para descobrir quais e-mails estão cadastrados no sistema.
_DUMMY_HASH = _hasher.hash("senha inexistente para igualar o tempo")


def waste_time_like_a_real_check() -> None:
    verify_password("qualquer coisa", _DUMMY_HASH)


def make_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    """String do QR code que o app autenticador escaneia."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="BR BOSS")


def totp_step(secret: str, code: str) -> int | None:
    """Em qual passo de tempo (janela de 30 s) este código vale. None — em nenhum.

    Aceitamos também o passo anterior e o seguinte: o relógio do celular
    quase sempre está um pouco fora do relógio do servidor. O passo volta
    para quem chama guardá-lo — um código já usado não pode entrar de novo.
    """
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset in (0, -1, 1):
        moment = now + offset * totp.interval
        if totp.verify(code, for_time=moment):
            return moment // totp.interval
    return None


def take_totp(user: User, secret: str, code: str | None) -> bool:
    """Conferir o código e gastá-lo: o mesmo código não serve duas vezes.

    Quem espiou o código por cima do ombro, ou o pegou no meio do caminho,
    tem até um minuto e meio em que ele ainda vale. Guardando o último passo
    aceito, só o primeiro uso passa. Quem chama grava a mudança (commit).
    """
    step = totp_step(secret, code) if code else None
    if step is None:
        return False
    if user.totp_last_step is not None and step <= user.totp_last_step:
        return False
    user.totp_last_step = step
    return True


def password_mark(password_hash: str) -> str:
    """Impressão digital da senha atual, que vai dentro do token.

    A senha é trocada quando se suspeita de vazamento. Sem a impressão, um
    login já emitido continuaria valendo por mais uma semana — ou seja,
    trocar a senha não protegeria de nada.
    """
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_token(user: User) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user.id),
            "pwd": password_mark(user.password_hash),
            # Versão das sessões: «Sair» e a troca de senha a aumentam, e
            # todo token emitido antes deixa de valer na hora.
            "ver": user.token_version or 0,
            "iat": now,
            "exp": now + TOKEN_TTL,
        },
        _secret(),
        algorithm=_ALGORITHM,
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        payload = jwt.decode(
            credentials.credentials,
            _secret(),
            algorithms=[_ALGORITHM],
            # sem o require, um token sem validade seria aceito como eterno
            options={"require": ["exp", "sub", "pwd"]},
        )
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _unauthorized() from None

    user = await session.get(User, user_id)
    if user is None:
        raise _unauthorized()
    if payload.get("pwd") != password_mark(user.password_hash):
        # a senha foi trocada depois que este login foi emitido
        raise _unauthorized()
    # Tokens de antes desta versão não têm "ver" — contam como 0 e seguem
    # valendo até o primeiro «Sair»: ninguém é expulso pela atualização.
    if payload.get("ver", 0) != (user.token_version or 0):
        raise _unauthorized()
    return user


# Quem é quem.
#
# owner — a equipe: o dono e o desenvolvedor, criados pela equipe no servidor
#   (python -m app.admin add). Compartilham uma caixa de entrada e a chave de
#   IA do servidor.
# member — cadastrou-se sozinho pelo link. Vê só o que é seu: suas caixas,
#   seus e-mails, suas regras. O e-mail dos outros fica inacessível, seja
#   pela lista, seja por link direto — toda consulta a um e-mail passa por
#   estes filtros.
OWNER = "owner"
MEMBER = "member"

_OWNERS = select(User.id).where(User.role == OWNER)


def visible_accounts(user: User):
    """Quais caixas este login enxerga.

    Os donos veem as caixas um do outro: o dono e o desenvolvedor
    trabalham com uma só caixa de entrada. Mas só as caixas dos donos — o
    e-mail de quem se cadastrou sozinho a equipe não vê, assim como eles
    não veem o da equipe.
    """
    if user.role == OWNER:
        return Account.user_id.in_(_OWNERS)
    return Account.user_id == user.id


def visible_rules(user: User):
    """Quais regras este login enxerga — pelas mesmas leis das caixas."""
    if user.role == OWNER:
        return Rule.user_id.in_(_OWNERS)
    return Rule.user_id == user.id
