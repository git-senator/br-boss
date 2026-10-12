import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gemini, keys
from app.config import settings
from app.crypto import encrypt_secret
from app.db import get_session
from app.models import User
from app.ratelimit import forget, note_failure, seconds_until_allowed
from app.security import (
    MEMBER,
    hash_password,
    create_token,
    current_user,
    make_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
    waste_time_like_a_real_check,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str
    code: str | None = None


class RegisterRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class AiKey(BaseModel):
    key: str = Field(min_length=1, max_length=200)


class TotpConfirm(BaseModel):
    secret: str = Field(min_length=16)
    code: str
    # só é exigido se a verificação em duas etapas já estiver ativada
    current_code: str | None = None


def _rejected(reason: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=reason)


@router.post("/login")
async def login(data: LoginRequest, session: AsyncSession = Depends(get_session)) -> dict:
    email = data.email.strip().lower()

    wait = seconds_until_allowed(email)
    if wait:
        # O bloqueio vale até para a senha certa. Senão a força bruta
        # chega lá exatamente no momento em que acerta.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_attempts",
            headers={"Retry-After": str(wait)},
        )

    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        waste_time_like_a_real_check()
        note_failure(email)
        raise _rejected("invalid_credentials")

    if not verify_password(data.password, user.password_hash):
        note_failure(email)
        raise _rejected("invalid_credentials")

    if user.totp_secret:
        if not data.code:
            raise _rejected("totp_required")
        if not verify_totp(user.totp_secret, data.code):
            note_failure(email)
            raise _rejected("invalid_code")

    forget(email)
    return {"access_token": create_token(user), "token_type": "bearer"}


# O cadastro está aberto para quem tem o link — então é preciso protegê-lo
# de quem criaria mil contas por script. Do mesmo endereço, algumas por
# hora; de todos juntos, no máximo cem por dia. Contador em memória, como
# no login (app.ratelimit): o processo é um só.
REGISTER_PER_ADDRESS = 5
REGISTER_ADDRESS_WINDOW = 3600
REGISTER_PER_DAY = 100
_registered: dict[str, list[float]] = {}

MIN_PASSWORD = 10
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _too_many(address: str) -> bool:
    now = time.time()
    for key, window, limit in (
        (f"ip:{address}", REGISTER_ADDRESS_WINDOW, REGISTER_PER_ADDRESS),
        ("all", 86400, REGISTER_PER_DAY),
    ):
        recent = [moment for moment in _registered.get(key, []) if now - moment < window]
        _registered[key] = recent
        if len(recent) >= limit:
            return True
    return False


def _count(address: str) -> None:
    now = time.time()
    for key in (f"ip:{address}", "all"):
        _registered.setdefault(key, []).append(now)


def _bad_request(text: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=text)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    session: AsyncSession = Depends(get_session),
    # O endereço da pessoa vem do site: o navegador não fala direto com a API,
    # e a API não é visível de fora — não há quem falsifique o cabeçalho.
    x_client_ip: str | None = Header(default=None),
) -> dict:
    """Conta própria pelo link. Essa pessoa é member: vê só os próprios
    e-mails e usa a própria chave de IA (app.security, app.ai.keys)."""
    if not settings.registration_open:
        raise HTTPException(status_code=403, detail="O cadastro está fechado. Peça um acesso ao administrador.")

    address = (x_client_ip or "?").split(",")[0].strip()
    if _too_many(address):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Cadastros demais. Tente de novo daqui a uma hora.",
        )

    email = data.email.strip().lower()
    if not _EMAIL.match(email):
        raise _bad_request("Isso não parece um endereço de e-mail.")
    if len(data.password) < MIN_PASSWORD:
        raise _bad_request(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres.")
    if data.password.strip().lower() == email:
        raise _bad_request("A senha não pode ser igual ao e-mail.")

    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este e-mail já está cadastrado — faça login.",
        )

    _count(address)
    user = User(email=email, password_hash=hash_password(data.password), role=MEMBER)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return {"access_token": create_token(user), "token_type": "bearer"}


@router.get("/me")
async def me(user: User = Depends(current_user)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "totp_enabled": bool(user.totp_secret),
        "role": user.role,
        # A chave inteira nunca sai daqui — só o final, para reconhecê-la.
        "ai_key_hint": keys.hint(user),
        # Se a chave do servidor vale para ele, caso não tenha a própria.
        "ai_shared_key": keys.may_use_server_key(user),
    }


@router.put("/ai-key")
async def set_ai_key(
    data: AiKey,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Chave própria do Gemini: daqui em diante a triagem dos e-mails dessa
    pessoa sai por conta dela.

    Primeiro conferimos a chave com o Google: um erro de digitação não pode
    parar em silêncio a triagem de todos os e-mails. Se não deu para conferir
    (rede, falha no Google), salvamos assim mesmo: a checagem é um cuidado
    com a pessoa, não uma tranca.
    """
    key = "".join(data.key.split())
    if not key.isascii() or len(key) < 20:
        raise HTTPException(status_code=400, detail="Isso não parece uma chave do Gemini.")
    if await gemini.check_key(key) is False:
        raise HTTPException(
            status_code=400,
            detail="O Google não aceitou esta chave. Confira se ela foi copiada por inteiro.",
        )
    user.ai_key_ciphertext = encrypt_secret(key)
    await session.commit()
    return {"ai_key_hint": keys.hint(user)}


@router.delete("/ai-key")
async def delete_ai_key(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user.ai_key_ciphertext = None
    await session.commit()
    return {"ai_key_hint": None}


@router.post("/totp/setup")
async def totp_setup(user: User = Depends(current_user)) -> dict:
    """Gerar um novo segredo — mas ainda sem salvar.

    Só salvamos depois do confirm: se a pessoa fechar a página sem
    escanear o QR code, ela não pode perder o acesso à conta.
    """
    secret = make_totp_secret()
    return {"secret": secret, "otpauth_url": totp_uri(secret, user.email)}


@router.post("/totp/confirm")
async def totp_confirm(
    data: TotpConfirm,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Não dá para trocar a verificação já ativa sem mostrar o código atual:
    # senão, quem roubou a sessão vincula o próprio celular e tranca o dono.
    if user.totp_secret and not (
        data.current_code and verify_totp(user.totp_secret, data.current_code)
    ):
        raise HTTPException(status_code=400, detail="current_code_required")
    if not verify_totp(data.secret, data.code):
        raise HTTPException(status_code=400, detail="invalid_code")
    user.totp_secret = data.secret
    await session.commit()
    return {"status": "ok"}
