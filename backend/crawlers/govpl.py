"""Generic crawler for gov.pl news and warnings sections.

All gov.pl sections share one CMS: a list of `.art-prev li` items (date, title, link) and
article pages with `article.article-area__article` (title in h2, date in p.event-date, text in
div.editor-content). One class therefore covers many catalogue rows; each section is defined
by three values in SECTIONS below.

Only links inside the section are kept: e.g. the Prime Minister's list also links to other
ministries' articles, which would otherwise be filed under the wrong publisher.
"""

from urllib.parse import urljoin, urlparse

from .base import ArticleLink, Document, ListingCrawler
from .dates import parse_polish_date

BASE = "https://www.gov.pl/web/"
PAGES = 3  # 10 items per page; later runs only fetch what is new
NOT_TEXT = ["div.main-photo", "div.gallery", "script", "style", "figure"]

# name, catalogue row (corpus/sources.csv), listing path under https://www.gov.pl/web/
SECTIONS = [
    ("govpl_kgpsp", 5, "kgpsp/aktualnosci"),  # State Fire Service
    ("govpl_mon", 8, "obrona-narodowa/aktualnosci5"),  # Ministry of National Defence
    ("govpl_gis", 9, "gis/ostrzezenia"),  # Chief Sanitary Inspectorate: public warnings
    ("govpl_infrastruktura", 15, "infrastruktura/aktualnosci"),  # Ministry of Infrastructure
    ("govpl_rcb", 36, "rcb/aktualnosci"),  # Government Centre for Security: news, alert tests
    ("govpl_mswia", 37, "mswia/aktualnosci"),  # Ministry of the Interior
    ("govpl_premier", 39, "premier/wydarzenia"),  # Prime Minister's office
]


class GovPlCrawler(ListingCrawler):
    """Base class; concrete sections are generated from SECTIONS at the bottom of the file."""

    license = "Public sector information published on gov.pl (terms: to_verify)"
    listing_path: str

    @property
    def section(self) -> str:
        return "/web/" + self.listing_path.split("/")[0] + "/"

    def parse_listing(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = self.soup(html)
        links = []
        for item in soup.select(".art-prev li"):
            a = item.find("a", href=True)
            if a is None:
                continue
            url = urljoin(page_url, a["href"].strip())
            parsed = urlparse(url)
            if parsed.hostname not in ("www.gov.pl", "gov.pl") or not parsed.path.startswith(self.section):
                continue  # article of another section or an external link
            title = item.select_one(".title")
            date = item.select_one(".date, .event-date")
            links.append(
                ArticleLink(
                    url=url,
                    title=title.get_text(" ", strip=True) if title else a.get_text(" ", strip=True),
                    published_at=parse_polish_date(date.get_text()) if date else None,
                )
            )
        return links

    def parse_article(self, html: str, link: ArticleLink) -> Document:
        soup = self.soup(html)
        article = soup.select_one("article.article-area__article")
        if article is None:
            raise ValueError("article body not found (page layout changed?)")
        title_node = article.select_one("h2")
        date_node = article.select_one("p.event-date, .event-date")
        title = title_node.get_text(" ", strip=True) if title_node else (link.title or link.url)
        body = article.select_one("div.editor-content")
        if body is None:  # some pages have no editor block: use the article without its header
            body = article
            for node in body.select("h2, p.event-date"):
                node.decompose()
        for selector in NOT_TEXT:
            for node in body.select(selector):
                node.decompose()
        return Document(
            url=link.url,
            title=title,
            text=f"{title}\n{self.strip_emoji(self.clean_text(body))}",
            published_at=(parse_polish_date(date_node.get_text()) if date_node else None) or link.published_at,
        )


def _make(name: str, catalog_id: int, path: str) -> type[GovPlCrawler]:
    first = BASE + path
    pages = [first] + [f"{first}?page={n}&size=10" for n in range(2, PAGES + 1)]
    return type(
        f"GovPl_{name.removeprefix('govpl_')}",
        (GovPlCrawler,),
        {"name": name, "catalog_id": catalog_id, "listing_path": path, "listing_urls": pages},
    )


GOVPL_CRAWLERS: list[type[GovPlCrawler]] = [_make(*section) for section in SECTIONS]
