"""CERT Polska advisories (moje.cert.pl/komunikaty) — national CSIRT run by NASK.

Warnings about phishing and SMS scam campaigns, fake shops, impersonation of banks,
couriers, energy companies and public bodies: one of the most common kinds of rumour
and fraud that citizens ask about.

robots.txt on moje.cert.pl blocks everything except a few paths, /komunikaty/ included
(see RobotsRules in fetch.py). The list is paginated, 10 advisories per page.
"""

import re
from urllib.parse import urljoin

from .base import ArticleLink, Document, ListingCrawler
from .dates import parse_polish_date

BASE = "https://moje.cert.pl/komunikaty/"
NOT_TEXT = ["div.d-flex.flex-wrap", "h1", "div.subtitle", "figure", "script", "style"]


class CertCrawler(ListingCrawler):
    name = "cert"
    catalog_id = 13  # corpus/sources.csv: CERT Polska (NASK), komunikaty
    listing_urls = [BASE, f"{BASE}?page=2", f"{BASE}?page=3"]  # ~30 most recent advisories
    license = "CERT Polska advisories, moje.cert.pl (terms: to_verify)"

    def parse_listing(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = self.soup(html)
        links = []
        for card in soup.select("main#main-content div.advisory-card"):
            a = card.find_parent("a", href=True)
            if a is None:
                continue
            title_node = card.select_one("h2")
            date_node = card.select_one("div.subtitle div")
            links.append(
                ArticleLink(
                    # the href comes with spaces around it: " /komunikaty/2026/218/.../ "
                    url=urljoin(page_url, a["href"].strip()),
                    title=self.strip_emoji(title_node.get_text(" ", strip=True)) if title_node else None,
                    published_at=parse_polish_date(date_node.get_text()) if date_node else None,
                )
            )
        return links

    def parse_article(self, html: str, link: ArticleLink) -> Document:
        soup = self.soup(html)
        advisory = soup.select_one("main#main-content div[id^=alert-advisory-]")
        if advisory is None:
            raise ValueError("advisory body not found (page layout changed?)")

        title_node = advisory.select_one("h1")
        title = self.strip_emoji(title_node.get_text(" ", strip=True)) if title_node else (link.title or link.url)
        subtitle = [d.get_text(strip=True) for d in advisory.select("div.subtitle > div")]
        published_at = (parse_polish_date(subtitle[0]) if subtitle else None) or link.published_at
        number = re.search(r"\d+/\d{4}", " ".join(subtitle))
        categories = [b.get_text(strip=True) for b in advisory.select("span.badge")]

        for selector in NOT_TEXT:
            for node in advisory.select(selector):
                node.decompose()
        body = self.strip_emoji(self.clean_text(advisory))

        extra = {}
        if number:
            extra["advisory_number"] = number.group(0)
        if categories:
            extra["categories"] = categories
        return Document(
            url=link.url,
            title=title,
            text=f"{title}\n{body}",  # title in the text helps search find the advisory
            published_at=published_at,
            extra=extra,
        )
