"""Crawler framework and adapter tests. No network: adapters get saved HTML snippets.

To test a new adapter, copy a small piece of the real page's HTML into a string here
(only the parts your selectors use) and assert on what parse_* returns.
"""

from datetime import datetime

import pytest

from app.store import text_sources
from crawlers import REGISTRY
from crawlers.base import ArticleLink, Document, ListingCrawler
from crawlers.dates import WARSAW, parse_polish_date
from crawlers.fetch import FetchError
from crawlers.rcb import RcbDailyReport


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("21 listopada 2026 r.", datetime(2026, 11, 21, tzinfo=WARSAW)),
        ("Opublikowano 3 maja 2025 r., godz. 14:05", datetime(2025, 5, 3, 14, 5, tzinfo=WARSAW)),
        ("20.11.2026", datetime(2026, 11, 20, tzinfo=WARSAW)),
        ("2026-11-21T08:30", datetime(2026, 11, 21, 8, 30, tzinfo=WARSAW)),
        ("bez daty", None),
    ],
)
def test_parse_polish_date(text, expected):
    assert parse_polish_date(text) == expected


class FakeFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def get_html(self, url: str) -> str:
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError(f"{url}: HTTP 404")
        return self.pages[url]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirect text_sources to a temporary folder so tests never touch the real corpus."""
    for fn in ("save", "load", "iter_all"):
        original = getattr(text_sources, fn)
        monkeypatch.setattr(text_sources, fn, lambda *a, _f=original, **k: _f(*a, root=tmp_path, **k))
    return tmp_path


RCB_HTML = """
<html><body><main><article class="article-area__article">
  <h2>Raport dobowy</h2>
  <p>RAPORT DOBOWY powstaje w Rządowym Centrum Bezpieczeństwa, w Krajowym Centrum Zarządzania Kryzysowego.</p>
  <p>21 listopada 2026 r.</p>
  <h3>Ostrzeżenia meteorologiczne</h3><p>​​</p><p>brak</p>
  <h3>Alert RCB</h3>
  <p>Wczoraj do użytkowników sieci komórkowych w województwie podkarpackim wysłano wiadomość SMS o treści:
  „UWAGA! Rosyjski atak powietrzny na Ukrainie. Sytuacja jest monitorowana.”</p>
  <script>trackingCode()</script>
</article></main></body></html>
"""


def test_rcb_parses_report():
    crawler = RcbDailyReport(FakeFetcher({}))
    doc = crawler.parse_snapshot(RCB_HTML)
    assert doc.published_at == datetime(2026, 11, 21, tzinfo=WARSAW)
    assert doc.title == "Raport dobowy RCB z dnia 21.11.2026"
    assert "RAPORT DOBOWY powstaje" not in doc.text  # boilerplate intro removed
    assert "​" not in doc.text and "trackingCode" not in doc.text
    assert "Rosyjski atak powietrzny" in doc.text


def test_rcb_snapshot_saved_once_per_day(store):
    fetcher = FakeFetcher({RcbDailyReport.page_url: RCB_HTML})
    stats = RcbDailyReport(fetcher).run()
    assert stats.saved == 1
    saved = list(text_sources.iter_all())
    assert saved[0]["url"] == RcbDailyReport.page_url + "#2026-11-21"
    assert saved[0]["publisher"] == "Rządowe Centrum Bezpieczeństwa" and saved[0]["catalog_id"] == 4


def test_rcb_layout_change_is_reported_not_saved(store):
    stats = RcbDailyReport(FakeFetcher({RcbDailyReport.page_url: "<html><body>nowy układ</body></html>"})).run()
    assert stats.saved == 0 and stats.failed == 1 and "layout" in stats.errors[0]


class TinyListing(ListingCrawler):
    name = "tiny"
    catalog_id = 5
    listing_urls = ["https://www.gov.pl/web/kgpsp/aktualnosci"]

    def parse_listing(self, html, page_url):
        return [ArticleLink(url=f"https://www.gov.pl/web/kgpsp/{slug}") for slug in html.split()]

    def parse_article(self, html, link):
        return Document(url=link.url, title=link.url, text=html * 20, published_at=None)


def test_listing_crawler_skips_saved_articles_and_survives_errors(store):
    pages = {
        "https://www.gov.pl/web/kgpsp/aktualnosci": "a b missing",
        "https://www.gov.pl/web/kgpsp/a": "Strażacy ugasili pożar. ",
        "https://www.gov.pl/web/kgpsp/b": "Ćwiczenia ratownicze. ",
    }
    first = TinyListing(FakeFetcher(pages)).run()
    assert (first.saved, first.failed) == (2, 1)  # "missing" -> 404, others saved
    fetcher = FakeFetcher(pages)
    second = TinyListing(fetcher).run()
    assert second.saved == 0 and second.skipped_fresh == 2
    assert "https://www.gov.pl/web/kgpsp/a" not in fetcher.requested  # not downloaded again


def test_registry_names_and_catalog_ids_are_valid():
    for name, cls in REGISTRY.items():
        crawler = cls(FakeFetcher({}))  # raises if catalog_id is not in sources.csv
        assert crawler.name == name
