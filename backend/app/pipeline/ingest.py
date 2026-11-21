"""Step 1: validate input, fetch a URL safely, turn HTML into plain text."""

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.net import http_client
from app.schemas import CheckRequest, Status

MAX_DOWNLOAD_BYTES = 2_000_000
MAX_REDIRECTS = 3
URL_ONLY = re.compile(r"^\s*(https?://\S+)\s*$", re.IGNORECASE)


class IngestError(Exception):
    def __init__(self, status: Status, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class IngestResult:
    text: str
    source_url: str | None = None
    page_title: str | None = None
    notes: list[str] = field(default_factory=list)  # limitations to show the user


def ingest(req: CheckRequest, settings: Settings) -> IngestResult:
    text = (req.text or "").strip()
    url = (req.url or "").strip() or None

    # A message that is only a link is treated as a URL check.
    if url is None and (m := URL_ONLY.match(text)):
        url, text = m.group(1), ""

    if not text and not url:
        raise IngestError(Status.needs_clarification, "Wyślij treść doniesienia albo link do niego.")
    if len(text) > settings.max_input_chars:
        raise IngestError(
            Status.needs_clarification,
            f"Wiadomość jest za długa. Wyślij najwyżej {settings.max_input_chars} znaków "
            "albo sam fragment, który chcesz sprawdzić.",
        )

    if url is None:
        return IngestResult(text=text)

    title, page_text = fetch_url(url)
    notes = []
    if len(page_text) > settings.max_fetched_chars:
        page_text = page_text[: settings.max_fetched_chars]
        notes.append("Strona była długa — przeanalizowano tylko jej początek.")
    combined = f"{text}\n\n{page_text}".strip() if text else page_text
    if not combined:
        raise IngestError(Status.needs_clarification, "Na podanej stronie nie znaleziono tekstu do sprawdzenia.")
    return IngestResult(text=combined, source_url=url, page_title=title, notes=notes)


def _assert_public_host(url: str) -> None:
    """Block requests to localhost / private networks (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise IngestError(Status.needs_clarification, "Obsługiwane są tylko linki http(s).")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise IngestError(Status.error, "Nie udało się odnaleźć podanej strony (błąd DNS).") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise IngestError(Status.out_of_scope, "Ten adres nie jest publiczną stroną internetową.")


def fetch_url(url: str) -> tuple[str | None, str]:
    current = url
    with http_client(timeout=10.0, follow_redirects=False, headers={"User-Agent": "TapCheck/0.1"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _assert_public_host(current)
            try:
                with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        current = urljoin(current, resp.headers.get("location", ""))
                        continue
                    if resp.status_code >= 400:
                        raise IngestError(Status.error, f"Strona zwróciła błąd {resp.status_code}; nie można jej sprawdzić.")
                    ctype = resp.headers.get("content-type", "")
                    if "html" not in ctype and "text/plain" not in ctype:
                        raise IngestError(Status.out_of_scope, "Ten link nie prowadzi do strony z tekstem.")
                    body = b""
                    for chunk in resp.iter_bytes():
                        body += chunk
                        if len(body) > MAX_DOWNLOAD_BYTES:
                            break
                    encoding = resp.encoding or "utf-8"
            except httpx.HTTPError as e:
                raise IngestError(Status.error, "Nie udało się pobrać strony (przekroczony czas lub błąd sieci).") from e
            return html_to_text(body.decode(encoding, errors="replace"), ctype)
    raise IngestError(Status.error, "Strona przekierowuje zbyt wiele razy.")


def html_to_text(raw: str, content_type: str = "text/html") -> tuple[str | None, str]:
    if "html" not in content_type:
        return None, raw.strip()
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\n{3,}", "\n\n", root.get_text("\n", strip=True))
    return title, text
