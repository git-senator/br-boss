"""E-mails montados para travar o sistema: quem controla o texto é o remetente."""

import time

from app.mail.imap_source import TEXT_LIMIT, _html_to_text, _tidy, parse_email


def plain(text: str) -> bytes:
    return (
        "From: a@b.com.br\nSubject: Teste\nContent-Type: text/plain; charset=utf-8\n\n" + text
    ).encode()


def quick(work, *args) -> float:
    started = time.perf_counter()
    work(*args)
    return time.perf_counter() - started


def test_pathological_css_is_cleaned_quickly():
    """Expressão que volta atrás à vontade leva minutos num texto assim —
    e o worker para de buscar os e-mails de todas as caixas."""
    attacks = [
        "x{a:" + " " * 100_000 + "x",  # espaços sem fechar o bloco
        "{a:b;" * 20_000,  # declarações sem fim
        "a" * 100_000 + "{",  # seletor gigante antes da chave
        "/*" * 50_000,  # comentários sem fechamento
        "{" + "a" * 100_000,
    ]
    for text in attacks:
        assert quick(_tidy, text) < 2, f"lento demais: {text[:20]!r}…"


def test_pathological_html_is_cleaned_quickly():
    attacks = [
        "<!--" * 50_000,
        "<style>" * 30_000 + "</style>",
        "<script " * 30_000,
        "<" * 100_000,
    ]
    for html in attacks:
        assert quick(_html_to_text, html) < 2, f"lento demais: {html[:20]!r}…"


def test_style_blocks_still_go_away():
    """A troca da expressão não pode deixar o CSS voltar para o texto."""
    text = (
        ".btn { color: red; padding: 0 }\n"
        ".title { font-weight: bold; }\n"
        "@media screen { .a { margin: 0; } }\n"
        "Pague até sexta."
    )

    assert _tidy(text) == "Pague até sexta."


def test_braces_of_ordinary_text_survive():
    assert _tidy("Total {em reais}: 100") == "Total {em reais}: 100"


def test_a_monstrous_body_is_cut_before_cleaning():
    body = parse_email(plain("palavra " * 100_000), uid="1").body_text

    assert len(body) <= TEXT_LIMIT


def test_attachment_size_is_known_without_decoding_it():
    raw = (
        b"From: a@b.com.br\nSubject: Boleto\n"
        b'Content-Type: multipart/mixed; boundary="B"\n\n'
        b"--B\nContent-Type: text/plain\n\nSegue.\n"
        b'--B\nContent-Type: application/pdf\nContent-Disposition: attachment; filename="b.pdf"\n'
        b"Content-Transfer-Encoding: base64\n\nJVBERi0xLjQK\n--B--\n"
    )

    attachment = parse_email(raw, uid="1").attachments[0]

    assert attachment.size_bytes == 9, "doze letras de base64 são nove bytes"
