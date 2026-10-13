from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Os e-mails chegam de fusos horários diferentes — do Brasil, de Dubai, de
# Lisboa. Todo registro de horário é guardado com fuso e convertido para
# UTC; senão os prazos e o «hoje» do resumo vão mentir.
Timestamp = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Usuário do sistema. role: owner — a equipe (criada no servidor,
    compartilha a caixa de entrada), member — cadastrou-se sozinho e vê
    só o que é seu. Detalhes em app.security."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64), default=None)
    # Último passo de tempo (janela de 30 s) em que um código foi aceito.
    # Um código já usado não entra de novo, nem dentro da própria janela.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, default=None)
    # Versão das sessões, vai dentro do token. «Sair» e a troca de senha a
    # aumentam — e todos os tokens emitidos antes param de valer.
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")
    role: Mapped[str] = mapped_column(String(16), default="owner")
    # Chave pessoal do Gemini, criptografada com a mesma chave das senhas
    # das caixas. Se existe, o e-mail desta pessoa é analisado por conta
    # dela; se não, com a chave do servidor (se o servidor permitir, veja
    # AI_SHARED_KEY).
    ai_key_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")


class Account(Base):
    """Caixa de e-mail conectada. secret_ciphertext — a senha de app
    criptografada; a senha em texto puro nunca fica no banco."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_user_account_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(16), default="imap")
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    cursor: Mapped[str | None] = mapped_column(String(255), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(Timestamp, default=None)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="accounts")
    messages: Mapped[list["Message"]] = relationship(back_populates="account")


class Message(Base):
    """E-mail. category/priority/summary são preenchidos pela triagem de IA (Task 9)."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("account_id", "provider_message_id", name="uq_account_message"),
        # Para os contadores das abas. As três colunas que a agregação usa
        # estão no próprio índice, então o banco lê o índice, e não a
        # tabela pesada com os corpos dos e-mails. account_id vem primeiro:
        # cobre tanto a escolha de uma caixa quanto a contagem de todas.
        Index("ix_messages_account_category_read", "account_id", "category", "is_read"),
        # Para a fila de triagem: o worker procura, a cada ciclo, e-mails
        # sem categoria. Índice parcial — quando a IA alcançar a caixa,
        # sobram nele poucas linhas em vez de dezenas de milhares.
        Index(
            "ix_messages_unsorted",
            "sent_at",
            postgresql_where=text("category IS NULL"),
        ),
        # Para a tela «Dinheiro e prazos». E-mails com prazo são sempre
        # minoria, por isso o índice é parcial — pequeno e não atrasa a escrita.
        Index(
            "ix_messages_deadline",
            "deadline",
            postgresql_where=text("deadline IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    provider_message_id: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[str | None] = mapped_column(String(255), default=None)
    sender: Mapped[str] = mapped_column(String(320))
    sender_name: Mapped[str] = mapped_column(String(255), default="")
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    subject: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(Timestamp, default=None)
    # De onde veio o e-mail: "inbox" ou "spam". Buscamos o spam também — um
    # e-mail importante que caiu no spam o sistema tem que mostrar, não perder.
    folder: Mapped[str] = mapped_column(String(16), default="inbox")
    category: Mapped[str | None] = mapped_column(String(32), default=None)
    priority: Mapped[int | None] = mapped_column(default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    is_read: Mapped[bool] = mapped_column(default=False)
    # Dinheiro e prazos. A triagem extrai isso do e-mail e antes jogava
    # fora: simplesmente não havia lugar no banco. E é justamente para isso
    # que o sistema existe — não «chegou um e-mail», e sim «pagar R$ 47 mil
    # até sexta».
    deadline: Mapped[date | None] = mapped_column(Date, default=None)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)
    # Se o destinatário precisa responder ou tomar alguma ação.
    action_required: Mapped[bool] = mapped_column(default=False)
    # Para onde responder. Faturas e newsletters muitas vezes saem de
    # noreply@ e pedem resposta em outro endereço — o cabeçalho Reply-To.
    # Vazio — responder ao remetente.
    reply_to: Mapped[str | None] = mapped_column(String(320), default=None)
    # E-mail resolvido: foi respondido ou considerado sem necessidade de
    # resposta («Ignorar»). O que está resolvido não fica no topo da lista
    # de pendências.
    handled_at: Mapped[datetime | None] = mapped_column(Timestamp, default=None)
    # «Lembrar depois»: até este horário o e-mail não aparece na lista,
    # depois volta para o seu lugar.
    snoozed_until: Mapped[datetime | None] = mapped_column(Timestamp, default=None)
    # Tradução para o português feita pelo botão «Traduzir». Fica salva para
    # não pagar pela mesma tradução a cada abertura.
    subject_translated: Mapped[str | None] = mapped_column(Text, default=None)
    body_translated: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

    account: Mapped[Account] = relationship(back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="message", order_by="Attachment.id"
    )
    replies: Mapped[list["Reply"]] = relationship(
        back_populates="message", order_by="Reply.id"
    )


class Rule(Base):
    """Regra do usuário. Vale mais que a avaliação da IA: se a pessoa disse
    «tudo dos advogados é importante», o sistema não deve discutir."""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), default="")
    condition_kind: Mapped[str] = mapped_column(String(32))
    condition_value: Mapped[str] = mapped_column(Text)
    action_kind: Mapped[str] = mapped_column(String(32))
    action_value: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Reply(Base):
    """Resposta a um e-mail: o rascunho da IA e o que de fato foi enviado.

    Também é o registro de auditoria (especificação, seção 30): o que a IA
    sugeriu, o que a pessoa mudou, o que foi enviado, por quem e quando.
    Por isso a linha não é apagada e o texto da IA não é sobrescrito — a
    edição vai para final_text, ao lado.
    """

    __tablename__ = "replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    # draft — rascunho aguardando decisão; sent — enviado; failed — o
    # serviço recusou, o texto está intacto e dá para tentar de novo;
    # dropped — a pessoa escolheu «Ignorar» ou pediu um rascunho novo no
    # lugar deste.
    status: Mapped[str] = mapped_column(String(16), default="draft")
    to_address: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(Text, default="")
    ai_text: Mapped[str] = mapped_column(Text, default="")
    final_text: Mapped[str | None] = mapped_column(Text, default=None)
    language: Mapped[str] = mapped_column(String(32), default="")
    # Observação da IA para a pessoa: «provavelmente não precisa responder».
    note: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # Message-ID do e-mail enviado: é por ele que a resposta do outro lado entra na conversa.
    sent_message_id: Mapped[str | None] = mapped_column(String(255), default=None)
    # O que foi anexado: [{"filename": ..., "size": ...}]. Só nomes e
    # tamanhos — para o histórico. Os arquivos não ficam com a gente: foram
    # com o e-mail, e a cópia está em «Enviados» da caixa. Se não foi, eles
    # são anexados de novo.
    attachments: Mapped[list[dict]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(Timestamp, default=None)

    message: Mapped[Message] = relationship(back_populates="replies")


class Brief(Base):
    """Resumo matinal do dia: a introdução da IA e a marca de envio.

    As listas do resumo são montadas a partir do banco a cada abertura —
    estão sempre atualizadas. Só fica salvo o que custa dinheiro ou é
    feito uma vez por dia: o texto da IA e o fato de o e-mail com o resumo
    já ter saído.
    """

    __tablename__ = "briefs"

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_brief_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Cada um tem o seu resumo: com os seus e-mails e a introdução gerada com a sua chave.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    intro: Mapped[str] = mapped_column(Text, default="")
    generated_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    emailed_at: Mapped[datetime | None] = mapped_column(Timestamp, default=None)


class Attachment(Base):
    """Anexo de um e-mail — só a descrição. Os bytes ficam na caixa
    e são buscados de lá no clique (app.api.attachments): guardar arquivos
    dos outros é responder por eles, e eles ocupariam mais espaço do que
    todo o resto do banco."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(default=0)
    # Posição entre os anexos do e-mail — na ordem em que a leitura os lista
    # (imap_source.attachment_parts). É por ela que o anexo é achado no
    # e-mail no download. Vazio — linha mais antiga que esta coluna: aí
    # procuramos pelo nome e pelo tamanho.
    part_index: Mapped[int | None] = mapped_column(default=None)
    # Pensada para uma cópia num armazenamento de arquivos. Não fazemos
    # cópias; a coluna ficou vazia, caso um dia seja necessária.
    s3_key: Mapped[str | None] = mapped_column(String(500), default=None)

    message: Mapped[Message] = relationship(back_populates="attachments")


class WorkerState(Base):
    """Memória do worker entre reinícios. Um valor, uma linha.

    No banco, e não num arquivo dentro do contêiner: o estado tem que
    sobreviver não só ao reinício, mas também à mudança para outro
    servidor. O banco se muda junto com o projeto; o conteúdo do
    contêiner, não.
    """

    __tablename__ = "worker_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
