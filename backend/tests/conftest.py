import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.crypto import encrypt_secret, generate_key
from app.models import Account, Base, User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://boss:boss@db:5432/boss_test"
)


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    monkeypatch.setattr("app.crypto._key", generate_key().encode())


@pytest_asyncio.fixture
async def session_factory():
    """Banco limpo a cada teste, mais a fábrica de sessões.

    A fábrica é separada da sessão porque o código que consulta as caixas
    em paralelo precisa abrir uma conexão por tarefa.
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncSession:
    async with session_factory() as db_session:
        yield db_session


@pytest.fixture(autouse=True)
def default_ai(monkeypatch):
    """Nos testes valem as configurações padrão, seja o que for que esteja
    no .env desta máquina: senão o sentido dos testes muda conforme o
    servidor, e o que passa aqui quebra na máquina do dono."""
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "classify_since", "")
    monkeypatch.setattr(settings, "ai_shared_key", True)
    monkeypatch.setattr(settings, "translator", "libretranslate")
    monkeypatch.setattr(settings, "deepl_api_key", "")


@pytest.fixture(autouse=True)
def anthropic_key(monkeypatch):
    """A chave nos testes é falsa: nada chega à rede, as chamadas ao
    modelo estão substituídas em todo lugar. Ela só existe para que a
    checagem «chave configurada» não dispare onde se testa outra coisa."""
    monkeypatch.setattr(settings, "anthropic_api_key", "chave-de-teste")


@pytest.fixture(autouse=True)
def fresh_login_attempts():
    """O contador de erros de login vive na memória do processo. Sem limpá-lo,
    os erros de um teste somam com os do outro, e um teste qualquer bate no
    limite por endereço sem ter nada a ver com ele."""
    from app.ratelimit import attempts

    attempts.clear()
    yield
    attempts.clear()


@pytest.fixture(autouse=True)
def public_mail_hosts(monkeypatch):
    """Nos testes nenhum nome é resolvido de verdade: todo servidor de e-mail
    «está» num endereço público. Quem testa a própria checagem
    (tests/mail/test_guard.py) troca a resposta pela que quiser."""
    monkeypatch.setattr("app.mail.guard._addresses", lambda host, port: ["93.184.215.14"])


@pytest.fixture(autouse=True)
def auth_secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "chave-de-teste")


@pytest_asyncio.fixture
async def client(session) -> AsyncClient:
    """Cliente HTTP em cima do app, sem rede e sem servidor no ar.

    A sessão é a mesma do teste: o que a requisição gravou, o teste vê na hora.
    """
    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client, user) -> AsyncClient:
    from app.security import create_token

    client.headers["Authorization"] = f"Bearer {create_token(user)}"
    return client


@pytest_asyncio.fixture
async def user(session) -> User:
    record = User(email="boss@example.com", password_hash="x")
    session.add(record)
    await session.flush()
    return record


@pytest_asyncio.fixture
async def account(session, user) -> Account:
    record = Account(
        user_id=user.id,
        provider="imap",
        email="boss@mail.ru",
        secret_ciphertext=encrypt_secret("app-password-abcd"),
    )
    session.add(record)
    await session.flush()
    return record
