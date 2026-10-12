"""Sincronização das caixas: baixar os e-mails, salvar, triar.

Aqui todo o resto se encontra. Duas regras explicam por que este arquivo
foi escrito exatamente assim:

1. Uma caixa quebrada não para as outras. Uma senha vencida entre
   vinte e cinco não pode derrubar o resumo da manhã.
2. O e-mail não se perde, mesmo que a IA não o tenha triado. Melhor um
   e-mail sem categoria do que um e-mail ausente.
"""

import asyncio
import logging
import time
from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.ai import keys
from app.ai.provider import AINotConfigured, AIQuotaExhausted
from app.ai.triage import triage
from app.config import settings
from app.mail.errors import MailError
from app.mail.normalize import store_messages
from app.mail.registry import get_source
from app.models import Account, Message, Rule, User, WorkerState
from app.priority.engine import apply_rules
from app.security import visible_rules

log = logging.getLogger(__name__)


def _short_reason() -> str:
    """Um motivo curto em vez de um paredão de traceback.

    A triagem pode falhar em todos os e-mails seguidos — centenas de
    tracebacks no log escondem todo o resto.
    """
    import sys

    problem = sys.exc_info()[1]
    return f"{type(problem).__name__}: {problem}"[:200]


# Quantas caixas consultamos ao mesmo tempo. Mais do que isso esbarra nos
# limites dos serviços de e-mail e rende bloqueios temporários.
CONCURRENCY = 5

# Quantos e-mails não triados recuperamos por volta. A triagem é o único
# ponto que custa dinheiro e pode estar fora do ar, por isso pegamos
# aos poucos e não atrapalhamos o e-mail novo.
PENDING_LIMIT = 200

# Quantos e-mails novos da caixa triamos já na coleta. Uma volta normal
# traz um ou dois e-mails — eles são triados na hora. A primeira visita à
# caixa traz centenas — essas ficam com a recuperação, em paralelo e sem
# segurar a coleta.
INLINE_CLASSIFY = 20

# Quantos e-mails triamos ao mesmo tempo. Triar é esperar a resposta de
# outro serviço, não trabalho: um por um, setecentos e-mails levariam horas.
# Mais de uma dezena não pegamos — esbarra nos limites do modelo.
CLASSIFY_CONCURRENCY = 6

# Até quando não mexemos na triagem: a cota de requisições acabou até amanhã.
# Enquanto a pausa vale, os e-mails se acumulam e serão triados depois da
# renovação — exatamente como em qualquer outra indisponibilidade do modelo.
#
# Cada chave tem sua própria pausa: "" — chave do servidor, "user:7:…" — chave
# pessoal do sétimo usuário. Se a cota de um acabou, o e-mail dos demais
# continua sendo triado.
_paused: dict[str, float] = {}

# Se o horário da renovação é desconhecido, esperamos uma hora e tentamos de novo.
BLIND_PAUSE_SECONDS = 3600

# Com este nome a pausa fica no banco e sobrevive a um reinício. A pausa de
# uma chave pessoal fica sob um nome com sufixo: classification_paused_until:user:7:…
PAUSE_KEY = "classification_paused_until"


def pause_name(scope: str) -> str:
    return f"{PAUSE_KEY}:{scope}" if scope else PAUSE_KEY


def _as_time(value: str | None) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0


async def sync_pause(session: AsyncSession) -> None:
    """Conciliar a pausa em memória com a que está gravada no banco.

    A pausa tem que sobreviver a um reinício. Enquanto ela vivia só na
    memória do processo, cada rebuild a apagava, e o worker voltava a
    bater na porta fechada, gastando o resto da cota diária em recusas.
    Pego no e-mail real: numa única noite foram embora todas as cinquenta
    requisições gratuitas.
    """
    rows = await session.execute(
        select(WorkerState.key, WorkerState.value).where(
            or_(WorkerState.key == PAUSE_KEY, WorkerState.key.like(f"{PAUSE_KEY}:%"))
        )
    )
    remembered = {
        ("" if name == PAUSE_KEY else name[len(PAUSE_KEY) + 1 :]): _as_time(value)
        for name, value in rows
    }

    for scope in set(remembered) | set(_paused):
        # max, e não atribuição: lembrar a pausa pode, encurtá-la não.
        # Senão um banco vazio derrubaria a pausa definida um segundo atrás.
        _paused[scope] = max(_paused.get(scope, 0.0), remembered.get(scope, 0.0))
        if _paused[scope] > remembered.get(scope, 0.0):
            statement = pg_insert(WorkerState).values(
                key=pause_name(scope), value=str(_paused[scope])
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["key"], set_={"value": statement.excluded.value}
                )
            )


def classify_since() -> datetime | None:
    """A partir de que data triar os e-mails. Vazio — triar todos.

    A caixa traz anos de correspondência. Ela não pede decisões, e triar
    cada e-mail custa tempo e limites do modelo.
    """
    if not settings.classify_since:
        return None
    try:
        return datetime.combine(
            date.fromisoformat(settings.classify_since), datetime.min.time()
        ).replace(tzinfo=UTC)
    except ValueError:
        log.warning("CLASSIFY_SINCE não parece uma data: %s", settings.classify_since)
        return None


def worth_classifying(message: Message) -> bool:
    since = classify_since()
    if since is None or message.sent_at is None:
        return True
    return message.sent_at >= since


def _pause_until(reset_at: float | None, scope: str = "") -> None:
    _paused[scope] = reset_at or (time.time() + BLIND_PAUSE_SECONDS)


def classification_paused(scope: str = "") -> bool:
    return time.time() < _paused.get(scope, 0.0)


def _pause_left(scope: str = "") -> int:
    return max(0, int(_paused.get(scope, 0.0) - time.time()))


async def _classify(message: Message, rules: list[Rule]) -> None:
    """Triar o e-mail. Se não der certo, o e-mail fica e a triagem é refeita depois.

    Pegamos qualquer problema, não só o nosso erro: por baixo há uma
    biblioteca de terceiros, e ela lança o que bem entende. Pego no e-mail
    real — sem chave da Anthropic vinha de lá um TypeError, a rodada inteira
    caía e os e-mails nem eram salvos. A triagem não é motivo para perder
    um e-mail.
    """
    if not worth_classifying(message):
        return

    try:
        result = apply_rules(await triage(message), message, rules)
    except AIQuotaExhausted as exc:
        # A cota de hoje acabou. Pausa até a renovação — senão o worker
        # bate a cada minuto com centenas de requisições na porta fechada.
        # Pausa só da chave usada na requisição, não de todas.
        _pause_until(exc.reset_at, keys.current().scope)
        raise
    except AINotConfigured:
        # Sem chave — os e-mails se acumulam e serão triados quando ela aparecer.
        # Ficamos quietos: senão o log enche com a mesma linha para cada e-mail.
        return
    except Exception:  # noqa: BLE001 — biblioteca de terceiros, lança qualquer coisa
        log.warning(
            "e-mail %s ainda sem triagem: %s",
            message.provider_message_id,
            _short_reason(),
        )
        return
    message.category = result.category
    message.priority = result.priority
    message.summary = result.summary
    # Valores e prazos. A triagem já os extraía antes, mas não havia onde
    # guardá-los, e eles se perdiam — e é o que há de mais valioso no e-mail.
    message.deadline = result.deadline
    message.amount = result.amount
    message.currency = result.currency
    message.action_required = result.action_required


async def sync_account(session: AsyncSession, account: Account) -> int:
    """Baixar os e-mails novos de uma caixa. Devolve quantos foram adicionados."""
    source = get_source(account)
    try:
        raws, cursor = await source.fetch_since(account.cursor)
    except MailError as exc:
        account.last_error = str(exc)
        await session.commit()
        raise

    stored = await store_messages(session, account, raws)

    # E-mails no banco na hora, antes da triagem. A triagem espera a resposta
    # do modelo, e na primeira visita à caixa (centenas de e-mails) isso leva
    # dezenas de minutos: todo esse tempo a pessoa via a caixa de entrada vazia
    # e «aguardando a primeira verificação». Pego na primeira conexão de uma
    # caixa no servidor.
    account.cursor = cursor
    account.last_error = None
    account.last_synced_at = datetime.now(UTC)
    await session.commit()

    # Poucos e-mails novos — triar na hora. O resto fica com a recuperação
    # (classify_pending): ela roda em paralelo e em lotes.
    rules = await _rules_for(session, account.user_id, {})
    # Os e-mails da caixa são triados com a chave do dono dela.
    key = await keys.use_key_of(session, account.user_id)
    await sync_pause(session)
    freshest = sorted(
        stored, key=lambda m: m.sent_at or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    for message in freshest[:INLINE_CLASSIFY]:
        if classification_paused(key.scope) or not key.allowed:
            break
        try:
            await _classify(message, rules)
        except AIQuotaExhausted:
            break  # a cota acabou — os demais serão triados depois da renovação
    await sync_pause(session)
    await session.commit()
    return len(stored)


async def sync_all(session_factory: async_sessionmaker[AsyncSession]) -> dict[int, int]:
    """Consultar todas as caixas conectadas. As quebradas não atrapalham as outras.

    Cada caixa tem sua própria sessão do banco: a sessão não foi feita para
    uso simultâneo por várias tarefas, e com uma sessão compartilhada a
    conexão cairia assim que duas caixas respondessem ao mesmo tempo.

    No retorno: id da caixa -> quantos e-mails novos, ou -1 se a caixa não respondeu.
    """
    async with session_factory() as session:
        account_ids = list(
            await session.scalars(select(Account.id).where(Account.is_active.is_(True)))
        )

    results: dict[int, int] = {}
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(account_id: int) -> None:
        async with limit, session_factory() as session:
            account = await session.get(Account, account_id)
            try:
                results[account_id] = await sync_account(session, account)
            except Exception:
                log.exception("a caixa %s não sincronizou", account.email)
                results[account_id] = -1

    await asyncio.gather(*(one(account_id) for account_id in account_ids))
    return results


async def _rules_for(session: AsyncSession, user_id: int, cache: dict) -> list[Rule]:
    """As regras que valem para o e-mail deste dono.

    Os donos compartilham caixas e regras: uma regra criada pelo dono vale
    também para a caixa que o desenvolvedor conectou. Senão parte do e-mail
    seguiria umas leis e parte, outras.
    """
    if user_id not in cache:
        owner = await session.get(User, user_id)
        cache[user_id] = list(
            await session.scalars(
                select(Rule).where(
                    Rule.is_active.is_(True),
                    visible_rules(owner) if owner else Rule.user_id == user_id,
                )
            )
        )
    return cache[user_id]


async def classify_pending(
    session_factory: async_sessionmaker[AsyncSession], limit: int = PENDING_LIMIT
) -> int:
    """Recuperar os e-mails que ficaram sem triagem.

    O e-mail é salvo mesmo se a IA estava indisponível — mas sem esta
    passada ele ficaria sem categoria para sempre: a triagem só acontecia
    no momento do recebimento. Agora a indisponibilidade do modelo
    (a chave acabou, o computador com o modelo local está desligado)
    significa atraso, não perda.

    Devolve quantos e-mails foi possível triar.
    """
    since = classify_since()
    async with session_factory() as session:
        # Primeiro lembrar a pausa, depois decidir se trabalha: depois de
        # um reinício ela não está na memória, mas está no banco.
        await sync_pause(session)

        # De quem o e-mail pode ser triado agora: de quem tem chave e não está em pausa.
        # O filtro vai na consulta, não no laço: senão os e-mails de quem está
        # em pausa ocupariam o lote inteiro, e a vez dos outros nunca chegaria.
        users = list(await session.scalars(select(User)))
        ready = {
            user.id: key
            for user in users
            if (key := keys.key_of(user)).allowed and not classification_paused(key.scope)
        }
        if not ready:
            await session.commit()
            return 0

        conditions = [
            Message.category.is_(None),
            Account.is_active.is_(True),
            Account.user_id.in_(ready),
        ]
        if since is not None:
            # Filtro direto na consulta: senão os e-mails antigos ficariam
            # rodando em círculos para sempre, tirando os novos do lote.
            conditions.append(Message.sent_at >= since)

        messages = list(
            await session.scalars(
                select(Message)
                .join(Account)
                .options(selectinload(Message.account))
                .where(*conditions)
                .order_by(Message.sent_at.desc().nulls_last())
                .limit(limit)
            )
        )
        if not messages:
            return 0

        cache: dict[int, list[Rule]] = {}
        for message in messages:
            await _rules_for(session, message.account.user_id, cache)

        # Esperamos as respostas dos modelos ao mesmo tempo, e gravamos no banco
        # depois, um por vez: a conexão com o banco é uma só, não dá para dividi-la
        # entre tarefas.
        gate = asyncio.Semaphore(CLASSIFY_CONCURRENCY)

        async def one(message: Message) -> None:
            # Tarefa própria, contexto próprio: a chave de um e-mail não
            # se confunde com a do vizinho.
            key = ready[message.account.user_id]
            keys.use(key)
            if classification_paused(key.scope):
                return
            async with gate:
                try:
                    await _classify(message, cache[message.account.user_id])
                except AIQuotaExhausted:
                    # A pausa já foi definida — os demais e-mails do lote
                    # simplesmente não começam.
                    pass

        await asyncio.gather(*(one(message) for message in messages))

        # Se a cota acabou agora mesmo, a pausa tem que ir para o banco
        # no mesmo commit que os e-mails triados.
        await sync_pause(session)

        done = sum(1 for message in messages if message.category)
        await session.commit()
        return done
