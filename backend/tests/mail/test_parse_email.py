from app.mail.imap_source import parse_email

PLAIN = b"""From: Joao Pereira <joao@uol.com.br>
To: boss@example.com
Subject: =?UTF-8?B?Q29icmFuw6dh?=
Date: Mon, 17 Aug 2026 10:00:00 -0300
Content-Type: text/plain; charset=utf-8

"""
PLAIN += "Pague o boleto até sexta-feira.\n".encode()

QUOTED_PRINTABLE = b"""From: billing@vendor.com
Subject: Invoice
Date: Mon, 17 Aug 2026 10:00:00 +0000
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: quoted-printable

Total: R$ 56=2E315=2C00
"""

MULTIPART = b"""From: Ana Silva <ana@fornecedor.com.br>
To: boss@example.com, copia@example.com
Subject: Boleto
Date: Mon, 17 Aug 2026 12:00:00 +0000
Content-Type: multipart/mixed; boundary="BOUND"

--BOUND
Content-Type: text/plain; charset=utf-8

Segue o boleto em anexo.
--BOUND
Content-Type: application/pdf; name="boleto.pdf"
Content-Disposition: attachment; filename="boleto.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK
--BOUND--
"""

HTML_ONLY = b"""From: news@shop.com
Subject: Sale
Date: Mon, 17 Aug 2026 10:00:00 +0000
Content-Type: text/html; charset=utf-8

<html><body><p>Big&nbsp;sale</p><p>Today only</p></body></html>
"""

NO_DATE = b"""From: someone@example.com
Subject: No date header

body
"""


def test_decodes_encoded_subject_and_utf8_body():
    msg = parse_email(PLAIN, uid="42")
    assert msg.provider_message_id == "42"
    assert msg.subject == "Cobrança"
    assert msg.sender == "joao@uol.com.br"
    assert msg.sender_name == "Joao Pereira"
    assert "Pague o boleto até sexta-feira" in msg.body_text
    assert msg.sent_at is not None
    assert msg.sent_at.year == 2026


def test_decodes_quoted_printable():
    assert "R$ 56.315,00" in parse_email(QUOTED_PRINTABLE, uid="1").body_text


def test_multipart_takes_text_part_and_lists_attachment():
    msg = parse_email(MULTIPART, uid="7")
    assert "Segue o boleto" in msg.body_text
    assert "JVBERi" not in msg.body_text
    assert [a.filename for a in msg.attachments] == ["boleto.pdf"]
    assert msg.attachments[0].content_type == "application/pdf"
    assert msg.attachments[0].size_bytes > 0


def test_multipart_collects_all_recipients():
    assert parse_email(MULTIPART, uid="7").recipients == [
        "boss@example.com",
        "copia@example.com",
    ]


def test_html_only_message_is_converted_to_text():
    body = parse_email(HTML_ONLY, uid="2").body_text
    assert "Big sale" in body
    assert "Today only" in body
    assert "<p>" not in body


def test_missing_date_gives_none_not_crash():
    assert parse_email(NO_DATE, uid="3").sent_at is None


def test_missing_subject_gives_empty_string():
    assert parse_email(NO_DATE, uid="3").subject == "No date header"
    assert parse_email(b"From: a@b.com\n\nbody", uid="4").subject == ""


async def test_attachment_fetch_returns_bytes():
    attachment = parse_email(MULTIPART, uid="7").attachments[0]
    assert (await attachment.fetch()).startswith(b"%PDF")

def build(plain: str) -> bytes:
    """E-mail bruto com a parte de texto informada."""
    head = (
        "From: EB/Hostinger <no-reply@ebanx.com>" + chr(10)
        + "To: boss@example.com" + chr(10)
        + "Subject: Pagamento" + chr(10)
        + "Date: Thu, 30 Jul 2026 15:57:00 +0000" + chr(10)
        + "Content-Type: text/plain; charset=utf-8" + chr(10) + chr(10)
    )
    return (head + plain).encode()


def build_html(html: str) -> bytes:
    """E-mail bruto que só tem a parte HTML."""
    head = (
        "From: Meta for Business <no-reply@business.facebook.com>" + chr(10)
        + "To: boss@example.com" + chr(10)
        + "Subject: Restricoes" + chr(10)
        + "Date: Thu, 06 Aug 2026 10:00:00 +0000" + chr(10)
        + "Content-Type: text/html; charset=utf-8" + chr(10) + chr(10)
    )
    return (head + html).encode()


def test_a_letter_laid_out_with_tabs_reads_as_text():
    """Pego em e-mail real: uma confirmação de pagamento de 139,99 se esticou
    por uma tela e meia de vazio, e achar o valor de olho era impossível.

    Os remetentes montam a parte de texto a partir do mesmo template da versão
    HTML, por isso nela sobram tabulações e dezenas de linhas vazias."""
    letter = build(
        plain=(
            "Oi Davud," + chr(10) * 6
            + "			" + chr(10)
            + "			Seu pagamento Hostinger de R$ 139,99 foi confirmado!" + chr(10) * 9
            + "   	  " + chr(10) * 4
            + "Em sua fatura aparecera o nome EBN*HOSTINGER." + chr(10) * 12
        )
    )

    body = parse_email(letter, "1").body_text

    assert body == (
        "Oi Davud,"
        + chr(10) + chr(10)
        + "Seu pagamento Hostinger de R$ 139,99 foi confirmado!"
        + chr(10) + chr(10)
        + "Em sua fatura aparecera o nome EBN*HOSTINGER."
    )


def test_paragraphs_stay_apart():
    """Não dá para juntar tudo: uma linha vazia separa as ideias."""
    letter = build(plain="Primeiro parágrafo." + chr(10) + chr(10) + "Segundo parágrafo.")

    body = parse_email(letter, "1").body_text

    assert body == "Primeiro parágrafo." + chr(10) + chr(10) + "Segundo parágrafo."


def test_a_plain_letter_is_left_alone():
    body = parse_email(build(plain="Mensagem curta, sem diagramação."), "1").body_text

    assert body == "Mensagem curta, sem diagramação."


CSS_LETTER = """Meta for Business
:root {
Color-scheme: light dark;
supported-color-schemes:light dark;
}
@font-face {
font-family: 'Optimistic Text Normal';
src: url(https://static.xx.fbcdn.net/rsrc.php/yd/r/vu9QUYy2ngT.woff2) format('woff2')
}
@media (prefers-color-scheme: dark ) {
a {
color: #FFF;
}
.tp_body {
background-color: #283943 !important;
color: #F1F4F7;
}
}
A conta Rossa Group recebeu restrições.
ID da empresa: 1655034588899240"""


def test_style_rules_do_not_leak_into_the_text():
    """Pego em e-mail real: uma mensagem da Meta sobre restrições na conta
    começava com duas telas de CSS, e a pessoa perguntava que código era aquele."""
    body = parse_email(build(plain=CSS_LETTER), "1").body_text

    assert "color" not in body
    assert "font-face" not in body
    assert body.startswith("Meta for Business")
    assert "A conta Rossa Group recebeu restrições." in body
    assert "ID da empresa: 1655034588899240" in body


def test_a_style_tag_takes_its_contents_with_it():
    html = (
        "<html><head><style>.a { color: red; }</style></head>"
        "<body><p>Boleto para pagamento</p></body></html>"
    )
    letter = build_html(html)

    assert parse_email(letter, "1").body_text == "Boleto para pagamento"


def test_entities_turn_back_into_letters():
    """No e-mail aparece tanto «&#064;» quanto «&mdash;» — um punhado de trocas não basta."""
    letter = build_html("<p>Enviado para boss&#064;example.com &mdash; boleto</p>")

    assert parse_email(letter, "1").body_text == "Enviado para boss@example.com — boleto"


def test_braces_in_ordinary_text_survive():
    """Só cortamos o que parece estilo. Texto comum com chaves e
    configurações num e-mail do desenvolvedor têm que ficar."""
    plain = 'Coloque nas configurações {"limit": 20, "retry": true} e reinicie.'
    body = parse_email(build(plain=plain), "1").body_text

    assert body == plain


def test_entities_in_the_plain_part_are_decoded_too():
    """«&#064;» no lugar da arroba aparece também na parte de texto: ela sai
    do mesmo template da versão HTML."""
    body = parse_email(build(plain="Enviado para ccrmbzl&#064;gmail.com"), "1").body_text

    assert body == "Enviado para ccrmbzl@gmail.com"
