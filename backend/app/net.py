"""Shared HTTP client factory.

Why force IPv4: many hosts (Google APIs, gov.pl, api.anthropic.com) list IPv6 addresses
first. On networks where IPv6 is advertised but broken (common on WSL2 and some home
routers), Python tries each IPv6 address in turn before falling back to IPv4, adding
3-6 s per address to every request (Google returns 8 of them: ~40 s per call). Browsers and
curl race both families ("happy eyeballs"); httpx does not. Binding to 0.0.0.0 makes every
connection IPv4, which costs nothing where IPv6 works. Set FORCE_IPV4=false to disable.
"""

import httpx

from app.config import get_settings

IPV4_ANY = "0.0.0.0"


def _force_ipv4() -> bool:
    return get_settings().force_ipv4


def http_client(**kwargs) -> httpx.Client:
    if _force_ipv4():
        kwargs.setdefault("transport", httpx.HTTPTransport(local_address=IPV4_ANY))
    return httpx.Client(**kwargs)


def async_http_client(**kwargs) -> httpx.AsyncClient:
    if _force_ipv4():
        kwargs.setdefault("transport", httpx.AsyncHTTPTransport(local_address=IPV4_ANY))
    return httpx.AsyncClient(**kwargs)
