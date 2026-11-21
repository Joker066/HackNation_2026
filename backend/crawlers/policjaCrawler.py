"""Policja.pl news — national police portal (Komenda Główna Policji).

The national news list (https://policja.pl/pol/aktualnosci) mixes policja.pl's own articles
with articles hosted on regional and local police sites (podlaska.policja.gov.pl,
spkatowice.policja.gov.pl, ...). All of them run the same CMS, so one parser fits all.

Publisher: everything is filed under catalogue row 6 (Komenda Główna Policji). The regional
unit is kept in the extra "unit" field. Keeping one publisher name also means national and
regional police are not counted as *independent* confirmations of each other.
"""

import re
from urllib.parse import urljoin, urlparse

from .base import ArticleLink, Document, ListingCrawler
from .dates import parse_polish_date

# The list sometimes links to non-police sites (e.g. the police academy, csp.edu.pl).
ALLOWED_HOSTS = re.compile(r"^(www\.)?policja\.pl$|\.policja\.gov\.pl$")

# Blocks inside <article> that are not article text.
NOT_TEXT = ["#drukuj", "div.zdjecia", "section", "div.clear", "script", "style"]


class PolicjaCrawler(ListingCrawler):
    name = "policja"
    catalog_id = 6  # corpus/sources.csv: Komenda Główna Policji, policja.pl news
    listing_urls = ["https://policja.pl/pol/aktualnosci"]
    license = "Public sector information published on police websites (terms: to_verify)"

    def parse_listing(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = self.soup(html)
        links = []
        for item in soup.select("div.okno li.nnews"):
            a = item.find("a", href=True)
            if a is None:
                continue
            url = urljoin(page_url, a["href"])
            if not ALLOWED_HOSTS.search(urlparse(url).hostname or ""):
                continue
            title_node = item.select_one("h3")
            time_node = item.select_one("time.data")
            date_text = (time_node.get("datetime") or time_node.get_text()) if time_node else None
            links.append(
                ArticleLink(
                    url=url,
                    title=title_node.get_text(strip=True) if title_node else None,
                    published_at=parse_polish_date(date_text) if date_text else None,
                )
            )
        return links

    def parse_article(self, html: str, link: ArticleLink) -> Document:
        soup = self.soup(html)
        article = soup.select_one("article")
        if article is None:
            raise ValueError("article body not found (page layout changed?)")

        title_node = article.select_one("div.head-title h2")
        date_node = article.select_one("span.data")  # "Data publikacji 20.11.2026" (not on every site)
        published_at = (parse_polish_date(date_node.get_text()) if date_node else None) or link.published_at

        # The site logo names the unit: <h1><a><strong><span class="hide">title</span>Policja Podlaska</strong>
        logo = soup.select_one("h1#header-logo strong")
        unit = None
        if logo is not None:
            for hidden in logo.select("span.hide"):
                hidden.decompose()
            unit = logo.get_text(" ", strip=True) or None

        for selector in NOT_TEXT:
            for node in article.select(selector):
                node.decompose()

        return Document(
            url=link.url,
            title=title_node.get_text(strip=True) if title_node else (link.title or link.url),
            text=self.clean_text(article),
            published_at=published_at,
            extra={"unit": unit} if unit else {},
        )
