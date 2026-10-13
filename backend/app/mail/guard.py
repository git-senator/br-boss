"""Só servidores de e-mail de verdade, na internet.

O endereço do servidor IMAP/SMTP sai do domínio do e-mail que a pessoa
digitou (imap.<domínio>). Quem se cadastra pelo link escolhe esse domínio —
e o DNS dele pode apontar para 127.0.0.1, para o banco na rede interna do
Docker ou para o serviço de metadados da nuvem. Sem esta checagem, o
formulário «Adicionar e-mail» viraria uma porta para dentro do servidor.

Antes de conectar, resolvemos o nome e recusamos se qualquer um dos
endereços não for público. A mensagem é neutra de propósito: não conta a
quem sonda o que existe do lado de dentro.
"""

import ipaddress
import socket

from app.mail.errors import MailHostError, unreachable


def _addresses(host: str, port: int) -> list[str]:
    """Os endereços IP do nome. Separado para os testes trocarem pela resposta que quiserem."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    # ::ffff:127.0.0.1 é o 127.0.0.1 disfarçado de IPv6.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def ensure_public_host(host: str, port: int) -> None:
    """Lança MailHostError se o nome não resolve ou leva a um endereço interno."""
    try:
        addresses = _addresses(host, port)
    except (OSError, UnicodeError) as exc:
        raise MailHostError(unreachable(host)) from exc
    if not addresses or not all(_is_public(address) for address in addresses):
        raise MailHostError(unreachable(host))
