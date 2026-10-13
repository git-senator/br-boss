"""Caixa de entrada: a lista de decisões e um e-mail completo.

Aqui a ordem é tudo. O usuário não deve ver mensagens, e sim
decisões: no topo, o que mais custa deixar para depois.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import quota, translator
from app.ai import keys
from app.ai.provider import AIError, AINotConfigured
from app.ai.schemas import ADS, CATEGORIES, SPAM, UNSORTED
from app.ai.translate import translate
from app.api.replies import answer_address, reply_dict
from app.config import settings
from app.db import get_session
from app.mail.providers import profile_for
from app.models import Account, Message, Reply, User
from app.security import MEMBER, current_user, visible_accounts

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _short(message: Message) -> dict:
    """Linha da lista. Sem o corpo do e-mail: a lista é visão geral, não leitura."""
    return {
        "id": message.id,
        "provider_message_id": message.provider_message_id,
        "sender": message.sender,
        "sender_name": message.sender_name,
        "subject": message.subject,
        "summary": message.summary,
        "category": message.category,
        "priority": message.priority,
        "sent_at": message.sent_at,
        "is_read": message.is_read,
        "folder": message.folder,
        "deadline": message.deadline,
        # O valor vai como texto, não como número: dinheiro não pode passar
        # por ponto flutuante, que arredonda sem avisar. A interface só
        # precisa dele para exibir.
        "amount": str(message.amount) if message.amount is not None else None,
        "currency": message.currency,
        "action_required": message.action_required,
        "handled_at": message.handled_at,
        "snoozed_until": message.snoozed_until,
        "account": {
            "id": message.account.id,
            "email": message.account.email,
            "service": profile_for(message.account.email).label,
        },
    }


# Quantas palavras da busca levamos em conta. Cada palavra são cinco
# comparações no texto dos e-mails; uma busca do tamanho de um parágrafo
# viraria centenas de comparações.
SEARCH_WORDS = 8


def _search_words(query: str | None) -> list[str]:
    return [word for word in (query or "").split() if word][:SEARCH_WORDS]


def _like(word: str) -> str:
    """A palavra como trecho de texto: «%» e «_» da busca são caracteres, não curinga."""
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches(word: str):
    pattern = _like(word)
    return or_(
        *(
            column.ilike(pattern, escape="\\")
            for column in (
                Message.subject,
                Message.sender,
                Message.sender_name,
                Message.summary,
                Message.body_text,
            )
        )
    )


def _visible(
    user: User,
    *,
    query: str | None = None,
    category: str | None = None,
    min_priority: int | None = None,
    account_id: int | None = None,
    unread_only: bool = False,
    include_ads: bool = False,
    with_money: bool = False,
) -> list:
    """Filtros dos e-mails — os mesmos para a lista e para os contadores.

    Eles não podem divergir: se a lista conta «Tudo» de um jeito e o
    contador da aba de outro, o número no botão vai mentir, e quem vai
    perceber é só o usuário.
    """
    where = [visible_accounts(user)]

    words = _search_words(query)
    if words:
        # A busca percorre todos os e-mails: a pessoa procura um e-mail
        # específico, e escondê-lo porque a IA achou que era propaganda ou
        # a caixa jogou no spam seria mentir «não encontrado». Cada palavra
        # precisa aparecer em algum lugar: no assunto, no remetente, no
        # resumo ou no texto.
        where.extend(_matches(word) for word in words)
    everywhere = bool(words) and category is None

    # Spam fica numa prateleira à parte. Nas outras abas, inclusive «Tudo»,
    # ele não aparece: senão dilui a lista de decisões, que é a razão de ser
    # do sistema. Mas também não se perde: um e-mail importante que caiu no
    # spam aparece na aba dele, e no topo vale a mesma regra — o que mais
    # custa deixar para depois.
    if category == SPAM:
        where.append(Message.folder == SPAM)
    elif not everywhere:
        where.append(Message.folder.is_distinct_from(SPAM))

    if category == SPAM:
        # Dentro do spam mostramos tudo o que houver: esconder propaganda
        # dentro da pasta de spam é esconder spam dentro do spam.
        category = None
        include_ads = True

    if category == UNSORTED:
        where.append(Message.category.is_(None))
    elif category:
        where.append(Message.category == category)
    elif not include_ads and not everywhere:
        # Propaganda fica na aba dela e não dilui a lista geral.
        #
        # is_distinct_from, e não «!=»: em SQL, comparar com NULL não dá
        # «verdadeiro», dá «desconhecido», e a linha não passa no filtro.
        # Com «!=» sumiriam de «Tudo» todos os e-mails ainda não triados — e
        # hoje são 747 de 775, ou seja, a caixa de entrada ficaria vazia com
        # o banco cheio.
        where.append(Message.category.is_distinct_from(ADS))

    if not words:
        # «Lembrar depois»: o e-mail adiado some das listas até a hora marcada
        # e volta sozinho quando ela chega. A busca encontra ele mesmo assim.
        where.append(
            or_(Message.snoozed_until.is_(None), Message.snoozed_until <= func.now())
        )

    if min_priority is not None:
        where.append(Message.priority >= min_priority)
    if account_id:
        where.append(Message.account_id == account_id)
    if unread_only:
        where.append(Message.is_read.is_(False))
    if with_money:
        # Tela «Dinheiro e prazos»: e-mails que citam um valor ou um prazo.
        where.append(or_(Message.amount.is_not(None), Message.deadline.is_not(None)))

    return where


def _order(by_deadline: bool, searching: bool = False) -> tuple:
    """Como medimos «o importante no topo».

    Normalmente é a prioridade. Mas na tela de dinheiro e prazos o prazo
    pesa mais: ali o que está vencido tem que vir primeiro, mesmo que a IA
    tenha dado uma nota média.

    nulls_last nos dois casos: senão o e-mail não triado e o e-mail sem
    prazo subiriam para o topo e empurrariam para baixo os realmente urgentes.
    """
    if searching:
        # Normalmente se busca algo recente: «o que o João escreveu sobre o
        # boleto». A prioridade não ajuda aqui — o e-mail procurado pode
        # muito bem ser pouco importante.
        return (Message.sent_at.desc().nulls_last(), Message.id.desc())
    # O que já foi resolvido — respondido ou marcado como «Ignorar» — desce
    # para baixo do pendente: a prioridade continua a mesma, mas não há
    # mais nada a fazer com ele.
    done = Message.handled_at.is_not(None)
    if by_deadline:
        return (
            done,
            Message.deadline.asc().nulls_last(),
            Message.priority.desc().nulls_last(),
            Message.id.desc(),
        )
    return (
        done,
        Message.priority.desc().nulls_last(),
        Message.sent_at.desc().nulls_last(),
        Message.id.desc(),
    )


@router.get("")
async def list_messages(
    category: str | None = None,
    min_priority: int | None = None,
    account_id: int | None = None,
    unread_only: bool = False,
    include_ads: bool = False,
    with_money: bool = False,
    by_deadline: bool = False,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    where = _visible(
        user,
        category=category,
        min_priority=min_priority,
        account_id=account_id,
        unread_only=unread_only,
        include_ads=include_ads,
        with_money=with_money,
        query=q,
    )

    total = await session.scalar(
        select(func.count()).select_from(Message).join(Account).where(*where)
    )
    items = await session.scalars(
        select(Message)
        .join(Account)
        .options(selectinload(Message.account))
        .where(*where)
        .order_by(*_order(by_deadline, searching=bool(_search_words(q))))
        .limit(limit)
        .offset(offset)
    )
    return {"total": total, "items": [_short(message) for message in items]}


# Declarado antes de «/{message_id}» — e tem que ficar aí. As rotas são
# testadas em ordem, e mais abaixo «counts» seria lido como id de e-mail.
@router.get("/counts")
async def message_counts(
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """Quantos e-mails há em cada aba — numa consulta só, e não em dez.

    Cada grupo devolve os dois números de uma vez: total e não lidos. Assim
    o seletor «não lidos» não exige uma segunda ida ao banco — a interface
    só pega o outro campo.

    Os contadores dependem da caixa selecionada, mas de propósito não
    dependem da categoria selecionada: senão todas as abas, menos a aberta,
    mostrariam zero. Se um dia surgir filtro por prioridade, ele vai ter que
    entrar aqui também, senão os números vão divergir da lista.
    """
    # Os filtros não separam por pasta: o spam é contado aqui mesmo,
    # só que no grupo dele.
    # Os adiados («Lembrar depois») não entram na conta, assim como não
    # aparecem: senão o número da aba não bateria com a lista embaixo dela.
    where = [
        visible_accounts(user),
        or_(Message.snoozed_until.is_(None), Message.snoozed_until <= func.now()),
    ]
    if account_id:
        where.append(Message.account_id == account_id)

    rows = await session.execute(
        select(
            Message.category,
            Message.folder,
            func.count().label("total"),
            func.count().filter(Message.is_read.is_(False)).label("unread"),
        )
        .select_from(Message)
        .join(Account)
        .where(*where)
        .group_by(Message.category, Message.folder)
    )

    # As chaves sempre existem, mesmo vazias: a interface não precisa
    # distinguir «zero e-mails» de «essa categoria não existe».
    buckets = {name: {"total": 0, "unread": 0} for name in (*CATEGORIES, UNSORTED, SPAM)}
    everything = {"total": 0, "unread": 0}

    for category, folder, total, unread in rows:
        if folder == SPAM:
            # O spam vai inteiro para o grupo dele, seja qual for a
            # categoria do e-mail: ele não aparece nas abas de categoria.
            buckets[SPAM]["total"] += total
            buckets[SPAM]["unread"] += unread
            continue

        name = category or UNSORTED
        if name in buckets:
            buckets[name] = {"total": total, "unread": unread}
        # Uma regra do usuário pode gravar qualquer coisa na categoria.
        # Esse e-mail não entra em grupo nenhum (o grupo não existe), mas
        # entra em «Tudo» — ele aparece na lista, então tem que ser contado.
        if name != ADS:
            everything["total"] += total
            everything["unread"] += unread

    return {"all": everything, "categories": buckets}


async def _owned_message(message_id: int, session: AsyncSession, user: User) -> Message:
    message = await session.scalar(
        select(Message)
        .join(Account)
        .options(selectinload(Message.account), selectinload(Message.attachments))
        .where(Message.id == message_id, visible_accounts(user))
    )
    if message is None:
        raise HTTPException(status_code=404, detail="E-mail não encontrado")
    return message


@router.get("/{message_id}")
async def get_message(
    message_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    message = await _owned_message(message_id, session, user)
    replies = await session.scalars(
        select(Reply).where(Reply.message_id == message.id).order_by(Reply.id)
    )
    return _short(message) | {
        "body_text": message.body_text,
        "recipients": message.recipients,
        "thread_id": message.thread_id,
        "reply_to": message.reply_to,
        "subject_translated": message.subject_translated,
        "body_translated": message.body_translated,
        "answer_to": answer_address(message),
        "replies": [reply_dict(reply) for reply in replies],
        "attachments": [
            {
                "id": item.id,
                "filename": item.filename,
                "content_type": item.content_type,
                "size_bytes": item.size_bytes,
            }
            for item in message.attachments
        ],
    }


async def _deepl_allowed(session: AsyncSession, user: User, message: Message) -> bool:
    """Este e-mail ainda cabe no teto diário do DeepL da pessoa?

    A cota do DeepL é uma só para o servidor inteiro. A equipe não tem teto;
    quem se cadastrou sozinho tem DEEPL_MEMBER_DAILY_CHARS por dia. Passou
    disso — traduz o tradutor próprio, e a pessoa nem percebe a troca.
    """
    if not settings.deepl_api_key or user.role != MEMBER:
        return True
    return await quota.take(
        session,
        f"deepl:chars:{user.id}:",
        quota.today(),
        translator.deepl_chars(message),
        settings.deepl_member_daily_chars,
    )


@router.post("/{message_id}/translate")
async def translate_message(
    message_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """Traduzir o e-mail para o idioma do usuário (português). Se já foi
    traduzido, devolvemos o que está salvo — não pagamos duas vezes pela
    mesma tradução. Os campos continuam se chamando subject_translated/body_translated."""
    message = await _owned_message(message_id, session, user)
    if message.body_translated is None:
        try:
            if settings.translator == "ai":
                # A tradução sai pela chave de quem apertou o botão.
                with keys.using(keys.key_of(user)):
                    done = await translate(message)
            else:
                # DeepL primeiro (se houver chave e couber no teto da pessoa),
                # depois o tradutor próprio no servidor, sem limites.
                done = await translator.translate(
                    message, use_deepl=await _deepl_allowed(session, user, message)
                )
        except translator.TranslatorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except AINotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except AIError as exc:
            raise HTTPException(
                status_code=502, detail="A IA não respondeu agora. Tente de novo em um minuto."
            ) from exc
        # Dois cliques seguidos viram dois pedidos ao mesmo tempo. Se o outro
        # já salvou a tradução enquanto este esperava o tradutor, fica a dele.
        await session.refresh(message, ["subject_translated", "body_translated"])
        if message.body_translated is None:
            message.subject_translated = done.subject
            message.body_translated = done.body
            await session.commit()
    return {"subject_translated": message.subject_translated, "body_translated": message.body_translated}


@router.post("/{message_id}/read")
async def mark_read(
    message_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    message = await _owned_message(message_id, session, user)
    message.is_read = True
    await session.commit()
    return {"status": "ok"}
