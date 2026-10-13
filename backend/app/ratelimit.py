"""Limite de tentativas de login.

Sem ele, a senha pode ser testada por força bruta a umas seis tentativas
por segundo — o argon2 é lento, mas nem tanto. Numa noite são meio milhão
de combinações.

O contador fica na memória do processo. Para um sistema de dois donos
isso basta, e é mais honesto do que criar um armazenamento externo com
seus próprios jeitos de quebrar. Se um dia surgir uma segunda instância
da aplicação, o contador terá que ir para um armazenamento compartilhado.

As chaves são escolhidas por quem chama (app.api.auth): por endereço IP e
por par e-mail + IP. Contar só pelo e-mail deixaria qualquer desconhecido
trancar o dono fora da própria conta, errando a senha dele de propósito.
"""

import time

MAX_ATTEMPTS = 10
WINDOW_SECONDS = 300
# Quantas chaves cabem na memória. Um script mandando e-mails inventados a
# cada tentativa faria o dicionário crescer sem fim; passou disto, saem
# primeiro as chaves vencidas, depois as mais antigas.
MAX_KEYS = 10_000
# A maior janela em uso — para saber quando uma chave já não vale nada.
LONGEST_WINDOW = 900

# chave -> lista de horários das tentativas que falharam
attempts: dict[str, list[float]] = {}


def _recent(key: str, now: float, window: int) -> list[float]:
    fresh = [moment for moment in attempts.get(key, []) if now - moment < window]
    if fresh:
        attempts[key] = fresh
    else:
        attempts.pop(key, None)
    return fresh


def seconds_until_allowed(
    key: str, limit: int = MAX_ATTEMPTS, window: int = WINDOW_SECONDS
) -> int:
    """0 — pode tentar. Maior que zero — quanto tempo esperar."""
    now = time.time()
    recent = _recent(key, now, window)
    if len(recent) < limit:
        return 0
    return max(1, int(window - (now - recent[-limit])))


def _prune(now: float) -> None:
    for key in [key for key, moments in attempts.items() if now - moments[-1] >= LONGEST_WINDOW]:
        attempts.pop(key, None)
    if len(attempts) > MAX_KEYS:
        by_age = sorted(attempts, key=lambda key: attempts[key][-1])
        for key in by_age[: len(attempts) - MAX_KEYS]:
            attempts.pop(key, None)


def note_failure(key: str) -> None:
    now = time.time()
    attempts.setdefault(key, []).append(now)
    if len(attempts) > MAX_KEYS:
        _prune(now)


def forget(key: str) -> None:
    """Um login bem-sucedido apaga o histórico de erros."""
    attempts.pop(key, None)
