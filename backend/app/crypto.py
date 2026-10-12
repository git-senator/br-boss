"""Criptografia das senhas das caixas de e-mail.

No banco fica só o texto cifrado. A chave mora na variável de ambiente
SECRET_ENCRYPTION_KEY e não entra no repositório.

IMPORTANTE: perder a chave significa que as senhas de todas as caixas
conectadas ficam ilegíveis e terão que ser digitadas de novo.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_key = settings.secret_encryption_key.encode()

_MISSING_KEY = (
    "SECRET_ENCRYPTION_KEY não definido. Gere uma chave e coloque no .env: "
    'python -c "from app.crypto import generate_key; print(generate_key())"'
)


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _cipher() -> Fernet:
    if not _key:
        raise ValueError(_MISSING_KEY)
    return Fernet(_key)


def encrypt_secret(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "cannot decrypt secret: a chave de criptografia não é a mesma usada para cifrar o segredo"
        ) from exc
