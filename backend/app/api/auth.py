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
    take_totp,
    totp_step,
    totp_uri,
    verify_password,
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


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class AiKey(BaseModel):
    key: str = Field(min_length=1, max_length=200)


class TotpConfirm(BaseModel):
    secret: str = Field(min_length=16)
    code: str
    # só é exigido se a verificação em duas etapas já estiver ativada
    current_code: str | None = None


def _rejected(reason: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=reason)


def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="too_many_attempts",
        headers={"Retry-After": str(wait)},
    )


def _client_address(x_client_ip: str | None) -> str:
    return (x_client_ip or "?").split(",")[0].strip() or "?"


# Erros de login: por par e-mail + endereço, e por endereço. Só pelo e-mail,
# um desconhecido errando a senha do dono de propósito o trancaria fora da
# própria conta. Assim ele tranca só a si mesmo — e de um endereço não dá
# para testar muitas senhas, nem de muitas contas.
LOGIN_PER_PAIR = (10, 300)
LOGIN_PER_ADDRESS = (30, 900)


@router.post("/login")
async def login(
    data: LoginRequest,
    session: AsyncSession = Depends(get_session),
    # O endereço da pessoa vem do site, como no cadastro (veja register).
    x_client_ip: str | None = Header(default=None),
) -> dict:
    email = data.email.strip().lower()
    address = _client_address(x_client_ip)
    pair, per_address = f"login:{email}|{address}", f"login-ip:{address}"

    wait = max(
        seconds_until_allowed(pair, *LOGIN_PER_PAIR),
        seconds_until_allowed(per_address, *LOGIN_PER_ADDRESS),
    )
    if wait:
        # O bloqueio vale até para a senha certa. Senão a força bruta
        # chega lá exatamente no momento em que acerta.
        raise _too_many(wait)

    def failed() -> None:
        note_failure(pair)
        note_failure(per_address)

    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        waste_time_like_a_real_check()
        failed()
        raise _rejected("invalid_credentials")

    if not verify_password(data.password, user.password_hash):
        failed()
        raise _rejected("invalid_credentials")

    if user.totp_secret:
        if not data.code:
            raise _rejected("totp_required")
        if not take_totp(user, user.totp_secret, data.code):
            failed()
            raise _rejected("invalid_code")
        await session.commit()

    # Só o par: um login certo não pode zerar o contador do endereço, senão
    # quem tem conta própria apagaria o rastro dos chutes nas contas alheias.
    forget(pair)
    return {"access_token": create_token(user), "token_type": "bearer"}


@router.post("/logout")
async def logout(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Sair de verdade: o token deixa de valer no servidor, e não só some do
    cookie deste navegador. Um token copiado antes também morre.

    A versão é uma só por pessoa, então «Sair» encerra as sessões de todos
    os aparelhos — preço pequeno por um botão que de fato fecha a porta.
    """
    user.token_version = (user.token_version or 0) + 1
    await session.commit()
    return {"status": "ok"}


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


def _too_many_signups(address: str) -> bool:
    now = time.time()
    for key, window, limit in (
        (f"ip:{address}", REGISTER_ADDRESS_WINDOW, REGISTER_PER_ADDRESS),
        ("all", 86400, REGISTER_PER_DAY),
    ):
        recent = [moment for moment in _registered.get(key, []) if now - moment < window]
        # Endereço sem cadastros recentes sai da memória: senão cada visita
        # deixaria uma linha vazia para sempre.
        if recent:
            _registered[key] = recent
        else:
            _registered.pop(key, None)
        if len(recent) >= limit:
            return True
    return False


def _count(address: str) -> None:
    now = time.time()
    for key in (f"ip:{address}", "all"):
        _registered.setdefault(key, []).append(now)


def _bad_request(text: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=text)


def _check_new_password(password: str, email: str) -> None:
    """As mesmas regras no cadastro e na troca de senha."""
    if len(password) < MIN_PASSWORD:
        raise _bad_request(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres.")
    if password.strip().lower() == email:
        raise _bad_request("A senha não pode ser igual ao e-mail.")


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

    address = _client_address(x_client_ip)
    if _too_many_signups(address):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Cadastros demais. Tente de novo daqui a uma hora.",
        )

    email = data.email.strip().lower()
    if not _EMAIL.match(email):
        raise _bad_request("Isso não parece um endereço de e-mail.")
    _check_new_password(data.password, email)

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


# Erros da senha atual na troca de senha, por pessoa. Uma sessão roubada
# não pode virar um jeito de adivinhar a senha sem limite.
PASSWORD_CHANGE_LIMIT = (5, 900)


@router.post("/password")
async def change_password(
    data: PasswordChange,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trocar a senha. Pede a atual: quem pegou a sessão aberta não troca a
    senha e não tranca o dono fora.

    Todas as outras sessões caem (a versão do token aumenta), e esta recebe
    um token novo — a pessoa continua dentro sem precisar entrar de novo.
    """
    key = f"password:{user.id}"
    wait = seconds_until_allowed(key, *PASSWORD_CHANGE_LIMIT)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tentativas demais. Espere alguns minutos e tente de novo.",
            headers={"Retry-After": str(wait)},
        )
    if not verify_password(data.current_password, user.password_hash):
        note_failure(key)
        raise _bad_request("A senha atual não confere.")
    _check_new_password(data.new_password, user.email)

    forget(key)
    user.password_hash = hash_password(data.new_password)
    user.token_version = (user.token_version or 0) + 1
    await session.commit()
    return {"access_token": create_token(user), "token_type": "bearer"}


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


# Erros na confirmação do autenticador, por pessoa. Sem limite, quem tem a
# sessão aberta testaria o código atual — um milhão de combinações — até
# acertar e trocar o autenticador pelo próprio.
TOTP_CONFIRM_LIMIT = (10, 300)


@router.post("/totp/confirm")
async def totp_confirm(
    data: TotpConfirm,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    key = f"totp:{user.id}"
    wait = seconds_until_allowed(key, *TOTP_CONFIRM_LIMIT)
    if wait:
        raise _too_many(wait)

    # Não dá para trocar a verificação já ativa sem mostrar o código atual:
    # senão, quem roubou a sessão vincula o próprio celular e tranca o dono.
    if user.totp_secret and not take_totp(user, user.totp_secret, data.current_code):
        note_failure(key)
        raise HTTPException(status_code=400, detail="current_code_required")
    step = totp_step(data.secret, data.code)
    if step is None:
        note_failure(key)
        raise HTTPException(status_code=400, detail="invalid_code")
    forget(key)
    user.totp_secret = data.secret
    # O código que confirmou também já foi usado: não serve para o login.
    user.totp_last_step = step
    await session.commit()
    return {"status": "ok"}
