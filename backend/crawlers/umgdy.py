"""Urząd Morski w Gdyni (Maritime Office in Gdynia) — umgdy.gov.pl news.

Coastal protection, ports, fairways, Baltic safety and navigation for the eastern Polish
coast. WordPress site; the archive is paginated as /aktualnosci/strona/N/ (10 per page).
"""

from urllib.parse import urljoin

from .base import ArticleLink, Document, ListingCrawler
from .dates import parse_polish_date

BASE = "https://www.umgdy.gov.pl/aktualnosci/"


class UmgdyCrawler(ListingCrawler):
    name = "umgdy"
    catalog_id = 30  # corpus/sources.csv: Urząd Morski w Gdyni
    listing_urls = [BASE, f"{BASE}strona/2/", f"{BASE}strona/3/"]  # ~30 most recent posts
    license = "Public sector information, umgdy.gov.pl (terms: to_verify)"

    def parse_listing(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = self.soup(html)
        links = []
        # Home page cards use <h3 class="card-title">, archive cards use <h2>; both are div.card.
        for card in soup.select("div.card"):
            a = card.select_one("h2 a[href*='/aktualnosc/'], h3 a[href*='/aktualnosc/']")
            if a is None:
                continue
            # Visible headings are cut off ("…Urząd Morski w Gd…"); the image alt has the full title.
            img = card.select_one("img[alt]")
            title = (img["alt"].strip() if img and img["alt"].strip() else None) or a.get_text(" ", strip=True)
            date_node = card.select_one("ul.list-inline li")  # "5 listopada 2026"
            links.append(
                ArticleLink(
                    url=urljoin(page_url, a["href"].strip()),
                    title=title,
                    published_at=parse_polish_date(date_node.get_text()) if date_node else None,
                )
            )
        return links

    def parse_article(self, html: str, link: ArticleLink) -> Document:
        soup = self.soup(html)
        # Main column only: the neighbouring div.col-xl-4 is a sidebar of other posts.
        body = soup.select_one("main div.pb-5 div.col.py-4")
        if body is None:
            raise ValueError("article body not found (page layout changed?)")
        title_node = soup.select_one("main h1")
        meta = [li.get_text(strip=True) for li in body.select("ul.list-inline li")]  # [date, author]
        published_at = (parse_polish_date(meta[0]) if meta else None) or link.published_at
        for node in body.select("ul.list-inline, script, style, figure"):
            node.decompose()
        title = title_node.get_text(" ", strip=True) if title_node else (link.title or link.url)
        return Document(
            url=link.url,
            title=title,
            text=f"{title}\n{self.strip_emoji(self.clean_text(body))}",
            published_at=published_at,
            extra={"author": meta[1]} if len(meta) > 1 and meta[1] else {},
        )
