"""Straż Ochrony Kolei (Railway Protection Guard, part of PKP Polskie Linie Kolejowe) — kgsok.pl.

News about security on railways and at stations: incidents, thefts, operations with the
police, safety campaigns. WordPress site; the news category is paginated (9 posts per page).
"""

from urllib.parse import urljoin

from .base import ArticleLink, Document, ListingCrawler
from .dates import parse_polish_date

BASE = "https://kgsok.pl/category/aktualnosci/"


class KgsokCrawler(ListingCrawler):
    name = "kgsok"
    catalog_id = 28  # corpus/sources.csv: Komenda Główna Straży Ochrony Kolei
    listing_urls = [BASE, f"{BASE}page/2/", f"{BASE}page/3/"]  # ~27 most recent posts
    license = "Straż Ochrony Kolei, kgsok.pl (terms: to_verify)"

    def parse_listing(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = self.soup(html)
        links = []
        # The wrapper is "news_list" on the home page but "news-list" on category pages,
        # so select the posts directly.
        for post in soup.select("div.news-list-post"):
            a = post.select_one("h3.news-list-post-title a[href]")
            if a is None:
                continue
            date_node = post.select_one("div.news-list-post-date")  # "18/11/2026"
            links.append(
                ArticleLink(
                    url=urljoin(page_url, a["href"].strip()),
                    title=a.get_text(" ", strip=True),
                    published_at=parse_polish_date(date_node.get_text()) if date_node else None,
                )
            )
        return links

    def parse_article(self, html: str, link: ArticleLink) -> Document:
        soup = self.soup(html)
        article = soup.select_one("article.post-type-post")
        body = article.select_one("div.single-new-body") if article else None
        if body is None:
            raise ValueError("article body not found (page layout changed?)")
        title_node = article.select_one("h1")
        date_node = article.select_one("div.single-header [class*=date]")  # "Data dodania 18 listopada 2026"
        title = title_node.get_text(" ", strip=True) if title_node else (link.title or link.url)
        return Document(
            url=link.url,
            title=title,
            text=f"{title}\n{self.strip_emoji(self.clean_text(body))}",
            published_at=(parse_polish_date(date_node.get_text()) if date_node else None) or link.published_at,
        )
