import pytest

from app.crypto import decrypt_secret, encrypt_secret, generate_key


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr("app.crypto._key", generate_key().encode())


def test_roundtrip_returns_original():
    token = encrypt_secret("app-password-123")
    assert token != "app-password-123"
    assert "app-password" not in token
    assert decrypt_secret(token) == "app-password-123"


def test_same_secret_encrypts_differently_each_time():
    assert encrypt_secret("igualzinho") != encrypt_secret("igualzinho")


def test_wrong_key_raises(monkeypatch):
    token = encrypt_secret("secret")
    monkeypatch.setattr("app.crypto._key", generate_key().encode())
    with pytest.raises(ValueError, match="cannot decrypt"):
        decrypt_secret(token)


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.setattr("app.crypto._key", b"")
    with pytest.raises(ValueError, match="SECRET_ENCRYPTION_KEY"):
        encrypt_secret("secret")


def test_non_ascii_secret_survives():
    assert decrypt_secret(encrypt_secret("senhaDeAppÇãõ")) == "senhaDeAppÇãõ"
