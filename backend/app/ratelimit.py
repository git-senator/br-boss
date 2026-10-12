"""Limite de tentativas de login.

Sem ele, a senha pode ser testada por força bruta a umas seis tentativas
por segundo — o argon2 é lento, mas nem tanto. Numa noite são meio milhão
de combinações.

O contador fica na memória do processo. Para um sistema de dois donos
isso basta, e é mais honesto do que criar um armazenamento externo com
seus próprios jeitos de quebrar. Se um dia surgir uma segunda instância
da aplicação, o contador terá que ir para um armazenamento compartilhado.
"""

import time

MAX_ATTEMPTS = 10
WINDOW_SECONDS = 300

# chave -> lista de horários das tentativas que falharam
attempts: dict[str, list[float]] = {}


def _recent(key: str, now: float) -> list[float]:
    fresh = [moment for moment in attempts.get(key, []) if now - moment < WINDOW_SECONDS]
    if fresh:
        attempts[key] = fresh
    else:
        attempts.pop(key, None)
    return fresh


def seconds_until_allowed(key: str) -> int:
    """0 — pode tentar. Maior que zero — quanto tempo esperar."""
    now = time.time()
    recent = _recent(key, now)
    if len(recent) < MAX_ATTEMPTS:
        return 0
    return max(1, int(WINDOW_SECONDS - (now - recent[0])))


def note_failure(key: str) -> None:
    now = time.time()
    attempts.setdefault(key, []).append(now)
    _recent(key, now)


def forget(key: str) -> None:
    """Um login bem-sucedido apaga o histórico de erros."""
    attempts.pop(key, None)
