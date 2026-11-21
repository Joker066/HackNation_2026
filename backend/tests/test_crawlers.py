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
        ("19-11-2026", datetime(2026, 11, 19, tzinfo=WARSAW)),  # cert.pl
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


# --- policja.pl ------------------------------------------------------------------

from crawlers.policjaCrawler import PolicjaCrawler  # noqa: E402

POLICJA_LISTING = """
<div class="okno"><ul>
 <li class="nnews"><a href="https://podlaska.policja.gov.pl/pod/aktualnosci/114728,PODLASKI-POLICJANT.html">
   <h3>PODLASKI POLICJANT TO NAJLEPSZY DYŻURNY W POLSCE</h3>
   <time class="data" datetime="2026-11-21">21.11.2026</time></a></li>
 <li class="nnews"><a href="/pol/aktualnosci/284115,Operacja-TOR.html"><h3>Operacja TOR</h3>
   <time class="data" datetime="2026-11-21">21.11.2026</time></a></li>
 <li class="nnews"><a href="https://www.csp.edu.pl/news/1"><h3>Szkoła Policji</h3></a></li>
</ul></div>
"""

POLICJA_ARTICLE = """
<html><body>
<h1 id="header-logo"><a href="/"><strong><span class="hide">PODLASKI POLICJANT - Aktualności</span>Policja Podlaska</strong></a></h1>
<article>
 <div class="head">
  <div class="head-title"><h2>PODLASKI POLICJANT TO NAJLEPSZY DYŻURNY W POLSCE</h2></div>
  <div id="drukuj"><span class="data">Data publikacji  20.11.2026</span>
   <div class="button"><a class="wstecz" href="#">Powrót</a></div><div class="button"><a href="#">Drukuj</a></div></div>
  <p class="intro"><strong>Dziś w Szkole Policji w Katowicach odbył się finał turnieju służby dyżurnej.</strong></p>
 </div>
 <p>Funkcjonariusz reprezentujący garnizon podlaski okazał się najlepszy w Polsce.</p>
 <div class="zdjecia"><img src="x.jpg"> Zdjęcie 1</div>
</article></body></html>
"""


def test_policja_listing_resolves_links_and_drops_other_sites():
    crawler = PolicjaCrawler(FakeFetcher({}))
    links = crawler.parse_listing(POLICJA_LISTING, "https://policja.pl/pol/aktualnosci")
    assert [l.url for l in links] == [
        "https://podlaska.policja.gov.pl/pod/aktualnosci/114728,PODLASKI-POLICJANT.html",
        "https://policja.pl/pol/aktualnosci/284115,Operacja-TOR.html",  # relative link resolved
    ]  # csp.edu.pl (police academy) dropped
    assert links[0].title.startswith("PODLASKI POLICJANT")
    assert links[0].published_at == datetime(2026, 11, 21, tzinfo=WARSAW)


def test_policja_article():
    crawler = PolicjaCrawler(FakeFetcher({}))
    link = ArticleLink(url="https://podlaska.policja.gov.pl/pod/aktualnosci/114728,PODLASKI-POLICJANT.html")
    doc = crawler.parse_article(POLICJA_ARTICLE, link)
    assert doc.title == "PODLASKI POLICJANT TO NAJLEPSZY DYŻURNY W POLSCE"
    assert doc.published_at == datetime(2026, 11, 20, tzinfo=WARSAW)
    assert doc.extra == {"unit": "Policja Podlaska"}
    assert "finał turnieju" in doc.text and "najlepszy w Polsce" in doc.text
    assert "Powrót" not in doc.text and "Drukuj" not in doc.text and "Zdjęcie" not in doc.text


def test_policja_article_without_date_uses_listing_date():
    crawler = PolicjaCrawler(FakeFetcher({}))
    listing_date = datetime(2026, 11, 19, tzinfo=WARSAW)
    html = POLICJA_ARTICLE.replace('<span class="data">Data publikacji  20.11.2026</span>', "")
    doc = crawler.parse_article(html, ArticleLink(url="https://x.policja.gov.pl/a", published_at=listing_date))
    assert doc.published_at == listing_date


# --- robots.txt (RFC 9309) ---------------------------------------------------------

from crawlers.fetch import RobotsRules  # noqa: E402

CERT_ROBOTS = """User-agent: *
Disallow: /

Allow: /$
Allow: /static/img/favicon*
Allow: /faq/
Allow: /komunikaty/
"""


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/komunikaty/", True),  # longer Allow beats "Disallow: /" (robotparser says False)
        ("/komunikaty/2026/218/falszywe-informacje/", True),
        ("/", True),  # "Allow: /$"
        ("/static/img/favicon.ico", True),  # wildcard
        ("/login/", False),
        ("/static/js/app.js", False),
    ],
)
def test_robots_most_specific_rule_wins(path, allowed):
    assert RobotsRules(CERT_ROBOTS).can_fetch("https://moje.cert.pl" + path) is allowed


def test_robots_agent_specific_group_and_tie():
    rules = RobotsRules("User-agent: *\nDisallow: /\n\nUser-agent: TapCheck\nDisallow: /a\nAllow: /a\n")
    assert rules.can_fetch("https://x.pl/b")  # our own group applies, not "*"
    assert rules.can_fetch("https://x.pl/a")  # equal length: Allow wins
    assert not RobotsRules("User-agent: *\nDisallow: /private\n").can_fetch("https://x.pl/private/1")


# --- moje.cert.pl ------------------------------------------------------------------

from crawlers.base import Crawler  # noqa: E402
from crawlers.cert import CertCrawler  # noqa: E402

CERT_LISTING = """
<main id="main-content" class="container my-4">
<a class="text-decoration-none d-flex h-100" href=" /komunikaty/2026/218/falszywe-informacje-o-zwrocie-za-energie-elektryczna/ ">
  <div id="alert-advisory-317 " class="alert advisory-card  h-100 d-flex flex-column w-100">
    <div class="d-flex flex-wrap gap-2 mb-3 mt-1"><span class="badge rounded-pill">Dla użytkowników</span></div>
    <h2 data-advisory-title="317" class="mb-1 h3">
        ⚠️ Fałszywe informacje o zwrocie za energię elektryczną
    </h2>
    <p>📩 Ponownie obserwujemy kampanię phishingową.</p>
    <div class="d-flex justify-content-between subtitle fw-semibold mt-auto">
      <div> 19-11-2026 </div><div> [218/2026] </div>
    </div>
  </div>
</a>
</main>
"""

CERT_ARTICLE = """
<main class="container my-4" id="main-content">
<nav><ol class="breadcrumb"><li>Strona główna</li><li>Komunikaty</li></ol></nav>
<div class="" id="alert-advisory-317">
  <div class="d-flex flex-wrap gap-2 mb-3"><span class="badge rounded-pill">Dla użytkowników</span></div>
  <h1 data-advisory-title="317">⚠️ Fałszywe informacje o zwrocie za energię elektryczną</h1>
  <div class="d-flex justify-content-between subtitle fw-semibold mt-auto mb-3">
    <div> 19-11-2026 </div><div> [218/2026] </div>
  </div>
  <p>📩 Ponownie obserwujemy kampanię phishingową, w której cyberprzestępcy podszywają się pod Polską Grupę Energetyczną.</p>
  <p>💰 Wiadomości zawierają link do fałszywej strony.</p>
  <figure><a href="/advisories/attachment/x/419/">obraz</a><figcaption>Treść fałszywej wiadomości e-mail</figcaption></figure>
</div>
<div class="alert alert-light">Zgłoś incydent</div>
</main>
"""


def test_cert_listing():
    links = CertCrawler(FakeFetcher({})).parse_listing(CERT_LISTING, "https://moje.cert.pl/komunikaty/?page=2")
    assert len(links) == 1
    assert links[0].url == "https://moje.cert.pl/komunikaty/2026/218/falszywe-informacje-o-zwrocie-za-energie-elektryczna/"
    assert links[0].title == "Fałszywe informacje o zwrocie za energię elektryczną"  # emoji removed
    assert links[0].published_at == datetime(2026, 11, 19, tzinfo=WARSAW)


def test_cert_article():
    link = ArticleLink(url="https://moje.cert.pl/komunikaty/2026/218/x/")
    doc = CertCrawler(FakeFetcher({})).parse_article(CERT_ARTICLE, link)
    assert doc.title == "Fałszywe informacje o zwrocie za energię elektryczną"
    assert doc.published_at == datetime(2026, 11, 19, tzinfo=WARSAW)
    assert doc.extra == {"advisory_number": "218/2026", "categories": ["Dla użytkowników"]}
    assert doc.text.startswith("Fałszywe informacje o zwrocie")
    assert "podszywają się pod Polską Grupę Energetyczną" in doc.text
    for junk in ("📩", "💰", "⚠", "Treść fałszywej wiadomości", "Zgłoś incydent", "Komunikaty", "19-11-2026"):
        assert junk not in doc.text


def test_strip_emoji_keeps_polish_text_and_punctuation():
    assert Crawler.strip_emoji("⚠️ Uwaga – „fałszywy” SMS! 📲\n\n💰 Zwrot 100 zł") == "Uwaga – „fałszywy” SMS!\nZwrot 100 zł"


# --- kgsok.pl ------------------------------------------------------------------------

from crawlers.kgsok import KgsokCrawler  # noqa: E402

KGSOK_LISTING = """
<div class="news-list">
 <div class="news-list-post"><div class="news-list-post-content">
  <a href="https://kgsok.pl/uroczysty-apel/" class="news-list-post-img"><img src="x.jpg" alt=""></a>
  <div class="news-list-post-content-text">
   <div class="news-list-post-category"><a href="https://kgsok.pl/category/aktualnosci/obchody-swieta/">Obchody święta</a></div>
   <h3 class="news-list-post-title"><a href="https://kgsok.pl/uroczysty-apel/">
        Uroczysty apel z okazji 108. rocznicy powołania Straży Ochrony Kolei</a></h3>
   <div class="post-date-link"><div class="news-list-post-date"> 18/11/2026 </div>
    <a href="https://kgsok.pl/uroczysty-apel/" class="read-more-link">Czytaj więcej</a></div>
  </div></div></div>
</div>
"""

KGSOK_ARTICLE = """
<article class="post-type-post">
 <div class="single-header">
  <div class="breadcrumbs">Straż Ochrony Kolei &gt; Aktualności &gt; Obchody święta</div>
  <h1>Uroczysty apel z okazji 108. rocznicy powołania Straży Ochrony Kolei</h1>
  <div class="single-date">Data dodania 18 listopada 2026</div>
 </div>
 <div class="single-new-img"><img src="x.jpg"></div>
 <div class="single-new-body"><p>Obchody 108-lecia Straży Ochrony Kolei rozpoczęła uroczysta Msza Święta.</p>
  <p>Podczas uroczystości wręczono odznaczenia.</p><script>gallery()</script></div>
</article>
"""


def test_kgsok_listing():
    links = KgsokCrawler(FakeFetcher({})).parse_listing(KGSOK_LISTING, "https://kgsok.pl/category/aktualnosci/")
    assert len(links) == 1  # image, title and "read more" links are one post
    assert links[0].url == "https://kgsok.pl/uroczysty-apel/"
    assert links[0].title == "Uroczysty apel z okazji 108. rocznicy powołania Straży Ochrony Kolei"
    assert links[0].published_at == datetime(2026, 11, 18, tzinfo=WARSAW)


def test_kgsok_article():
    doc = KgsokCrawler(FakeFetcher({})).parse_article(KGSOK_ARTICLE, ArticleLink(url="https://kgsok.pl/uroczysty-apel/"))
    assert doc.title.startswith("Uroczysty apel")
    assert doc.published_at == datetime(2026, 11, 18, tzinfo=WARSAW)
    assert "Msza Święta" in doc.text and "wręczono odznaczenia" in doc.text
    assert "Aktualności" not in doc.text and "gallery()" not in doc.text  # breadcrumb and script dropped


# --- umgdy.gov.pl ------------------------------------------------------------------

from crawlers.umgdy import UmgdyCrawler  # noqa: E402

UMGDY_URL = "https://www.umgdy.gov.pl/aktualnosc/150-milionow-zlotych-na-ochrone-wybrzeza/"
UMGDY_LISTING = f"""
<div class="row my-n3 masonry">
 <div class="card shadow-sm overflow-hidden">
  <div class="ratio ratio-16-9"><a href="{UMGDY_URL}">
   <img src="x.jpg" alt="150 milionów złotych na ochronę wybrzeża! Urząd Morski w Gdyni podpisał umowę"></a></div>
  <div class="card-body">
   <ul class="list-inline mb-2"><li class="list-inline-item">5 listopada 2026</li><li class="list-inline-item">Magdalena K.</li></ul>
   <h3 class="card-title fw-bold h4"><a href="{UMGDY_URL}">150 milionów złotych na ochronę wybrzeża! Urząd Morski w Gd…</a></h3>
  </div>
 </div>
 <div class="card"><div class="card-body">Newsletter</div></div>
</div>
"""
UMGDY_ARTICLE = """
<main>
 <div class="bg--image"><div class="bg--image--content"><h1>150 milionów złotych na ochronę wybrzeża!</h1></div></div>
 <div class="pb-5"><div class="pt--70"><div class="container"><div class="row">
  <div class="col py-4 pe-xl-4">
   <ul class="list-inline"><li class="list-inline-item">5 listopada 2026</li><li class="list-inline-item"></li></ul>
   <p>Bezpieczniejsze wybrzeże i skuteczniejsza ochrona mieszkańców.</p>
  </div>
  <div class="col-xl-4 py-4 ps-xl-4">2 listopada 2026 Ruszają badania geologiczne Klifu Orłowskiego</div>
 </div></div></div></div>
</main>
"""


def test_umgdy_listing_uses_full_title_and_skips_other_cards():
    links = UmgdyCrawler(FakeFetcher({})).parse_listing(UMGDY_LISTING, "https://www.umgdy.gov.pl/")
    assert len(links) == 1  # the newsletter card has no article link
    assert links[0].url == UMGDY_URL
    assert links[0].title.endswith("podpisał umowę")  # from img alt, not the truncated heading
    assert links[0].published_at == datetime(2026, 11, 5, tzinfo=WARSAW)


def test_umgdy_article_excludes_sidebar():
    doc = UmgdyCrawler(FakeFetcher({})).parse_article(UMGDY_ARTICLE, ArticleLink(url=UMGDY_URL))
    assert doc.title == "150 milionów złotych na ochronę wybrzeża!"
    assert doc.published_at == datetime(2026, 11, 5, tzinfo=WARSAW)
    assert "skuteczniejsza ochrona mieszkańców" in doc.text
    assert "Klifu Orłowskiego" not in doc.text  # sidebar dropped
    assert doc.extra == {}  # empty author not stored
