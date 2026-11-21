"""Step 1: validate input, fetch linked pages safely, turn HTML into plain text."""

import ipaddress
import json
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
MAX_LINKS = 2  # links fetched from one message
URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'„”«»]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}…"


class IngestError(Exception):
    def __init__(self, status: Status, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class IngestResult:
    text: str
    notes: list[str] = field(default_factory=list)  # limitations to show the user
    fetched_links: int = 0


def find_links(text: str) -> list[str]:
    """http(s) links mentioned anywhere in a message, in order, without trailing punctuation."""
    links = [m.group(0).rstrip(TRAILING_PUNCTUATION) for m in URL_IN_TEXT.finditer(text)]
    return list(dict.fromkeys(link for link in links if len(link) > len("https://")))


def ingest(req: CheckRequest, settings: Settings) -> IngestResult:
    """Accept anything the user sends: a message, a question, a link, or text with links.

    Code (not the model) finds links and fetches their pages through the SSRF guard; the
    model later decides what kind of input it is and which claims it contains.
    """
    text = (req.text or "").strip()
    explicit = (req.url or "").strip()

    if not text and not explicit:
        if req.image:  # an image alone is fine: it is read in the next step
            return IngestResult(text="")
        raise IngestError(Status.needs_clarification, "Wyślij treść doniesienia, pytanie, link albo zrzut ekranu.")
    if len(text) > settings.max_input_chars:
        raise IngestError(
            Status.needs_clarification,
            f"Wiadomość jest za długa. Wyślij najwyżej {settings.max_input_chars} znaków "
            "albo sam fragment, który chcesz sprawdzić.",
        )

    links = list(dict.fromkeys(([explicit] if explicit else []) + find_links(text)))
    if not links:
        return IngestResult(text=text)

    # The message is only a link (or links): the page content is all there is to check.
    remainder = text
    for link in links:
        remainder = remainder.replace(link, " ")
    only_links = not remainder.strip(" \n\t" + TRAILING_PUNCTUATION)

    notes: list[str] = []
    if len(links) > MAX_LINKS:
        notes.append(f"Wiadomość zawierała {len(links)} linki — sprawdzono tylko pierwsze {MAX_LINKS}.")
        links = links[:MAX_LINKS]
    per_page = settings.max_fetched_chars // len(links)
    pages: list[str] = []
    for link in links:
        try:
            _title, page_text = fetch_url(link)
        except IngestError as e:
            if only_links and len(links) == 1:
                raise  # nothing else to check
            notes.append(f"Nie udało się pobrać strony {link}: {e.message}")
            continue
        if len(page_text) > per_page:
            page_text = page_text[:per_page]
            notes.append(f"Strona {link} była długa — przeanalizowano tylko jej początek.")
        if page_text.strip():
            pages.append(f"Treść strony {link}:\n{page_text}")

    parts = ([] if only_links else [text]) + pages
    combined = "\n\n".join(parts).strip()
    if not combined:
        raise IngestError(Status.needs_clarification, "Na podanej stronie nie znaleziono tekstu do sprawdzenia.")
    return IngestResult(text=combined, notes=notes, fetched_links=len(pages))


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


MIN_VISIBLE_TEXT = 300  # below this, the page probably renders its article with JavaScript


def _structured_article_text(soup: BeautifulSoup) -> str:
    """Article text from schema.org JSON-LD (articleBody) or meta descriptions.

    Many news sites render the article with JavaScript but publish the full text for search
    engines as JSON-LD; this is the publisher's own data, not a workaround of any protection.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("articleBody"):
                return BeautifulSoup(str(item["articleBody"]), "html.parser").get_text(" ", strip=True)
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content", "").strip():
            return meta["content"].strip()
    return ""


def html_to_text(raw: str, content_type: str = "text/html") -> tuple[str | None, str]:
    if "html" not in content_type:
        return None, raw.strip()
    soup = BeautifulSoup(raw, "html.parser")
    structured = _structured_article_text(soup)  # read before scripts are removed
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\n{3,}", "\n\n", root.get_text("\n", strip=True))
    if len(text) < MIN_VISIBLE_TEXT and len(structured) > len(text):
        text = structured
    return title, text
