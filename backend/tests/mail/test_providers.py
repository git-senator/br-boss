import pytest

from app.mail.providers import known_services, profile_for


@pytest.mark.parametrize(
    ("email", "host", "label"),
    [
        ("boss@gmail.com", "imap.gmail.com", "Google"),
        ("boss@googlemail.com", "imap.gmail.com", "Google"),
        ("boss@outlook.com", "outlook.office365.com", "Microsoft"),
        ("boss@hotmail.com", "outlook.office365.com", "Microsoft"),
        ("boss@live.com", "outlook.office365.com", "Microsoft"),
        ("boss@mail.ru", "imap.mail.ru", "Mail.ru"),
        ("boss@bk.ru", "imap.mail.ru", "Mail.ru"),
        ("boss@inbox.ru", "imap.mail.ru", "Mail.ru"),
        ("boss@yandex.ru", "imap.yandex.ru", "Yandex"),
        ("boss@ya.ru", "imap.yandex.ru", "Yandex"),
        ("boss@uol.com.br", "imap.uol.com.br", "UOL"),
        ("boss@bol.com.br", "imap.bol.com.br", "BOL"),
        ("boss@terra.com.br", "imap.terra.com.br", "Terra"),
        ("boss@yahoo.com.br", "imap.mail.yahoo.com", "Yahoo"),
        ("boss@hotmail.com.br", "outlook.office365.com", "Microsoft"),
    ],
)
def test_known_domains_resolve(email, host, label):
    profile = profile_for(email)
    assert profile.imap_host == host
    assert profile.label == label
    assert profile.imap_port == 993


def test_unknown_domain_falls_back_to_imap_subdomain():
    profile = profile_for("boss@firma.com.br")
    assert profile.imap_host == "imap.firma.com.br"
    assert profile.label == "Outro e-mail"


def test_domain_case_is_ignored():
    assert profile_for("Boss@Gmail.COM").imap_host == "imap.gmail.com"


def test_every_known_service_explains_where_to_get_the_password():
    for profile in known_services():
        assert profile.help_url.startswith("https://")
        assert profile.password_hint


def test_microsoft_uses_starttls_port_for_sending():
    assert profile_for("a@outlook.com").smtp_port == 587
    assert profile_for("a@gmail.com").smtp_port == 465


def test_known_services_are_unique_and_sorted_for_the_ui():
    labels = [profile.label for profile in known_services()]
    assert labels == sorted(set(labels), key=labels.index)
    assert "Outro e-mail" not in labels
