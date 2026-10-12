"""Caixa de entrada comum para os testes da API.

As fixtures ficam aqui, e não em um dos arquivos: tanto a lista de e-mails
quanto os contadores das abas precisam contar os mesmos e-mails. Mantenha-os
em lugares diferentes e um dia eles divergem, sem que os testes percebam.
"""

from datetime import UTC, datetime

import pytest

from app.crypto import encrypt_secret
from app.models import Account, Message


@pytest.fixture
async def inbox(session, account):
    second = Account(
        user_id=account.user_id,
        email="boss@gmail.com",
        secret_ciphertext=encrypt_secret("p"),
    )
    session.add(second)
    await session.flush()

    letters = [
        ("m1", account, "payments", 91, datetime(2026, 8, 15, tzinfo=UTC)),
        ("m2", account, "low", 12, datetime(2026, 8, 17, tzinfo=UTC)),
        ("m3", second, "payments", 74, datetime(2026, 8, 16, tzinfo=UTC)),
        ("m4", second, "urgent", 91, datetime(2026, 8, 17, tzinfo=UTC)),
        ("m5", second, None, None, datetime(2026, 8, 14, tzinfo=UTC)),
    ]
    for msg_id, box, category, priority, sent_at in letters:
        session.add(
            Message(
                account_id=box.id,
                provider_message_id=msg_id,
                sender="ana@fornecedor.com.br",
                subject=f"E-mail {msg_id}",
                body_text="Pague até sexta",
                summary="Cobrança a pagar",
                category=category,
                priority=priority,
                sent_at=sent_at,
            )
        )
    await session.flush()
    return {"first": account, "second": second}


@pytest.fixture
async def with_ads(session, inbox):
    """Duas newsletters de propaganda em cima da caixa de entrada comum.

    Fixture separada, e não acréscimo em `inbox`: três testes estão presos
    àqueles cinco e-mails (ordem, total, caixa compartilhada pelos dois donos).
    Coloque e-mails ali e quebra o que nada tem a ver com propaganda.
    """
    for msg_id in ("ad1", "ad2"):
        session.add(
            Message(
                account_id=inbox["first"].id,
                provider_message_id=msg_id,
                sender="promo@loja.com.br",
                subject=f"Ofertas {msg_id}",
                body_text="50% de desconto",
                summary="Newsletter de ofertas",
                category="ads",
                priority=5,
                sent_at=datetime(2026, 8, 18, tzinfo=UTC),
            )
        )
    await session.flush()
    return inbox
