"""TEMPLATE for a new listing adapter. Copy this file, rename it, fill in the TODOs.

Steps:
  1. Pick a source from corpus/sources.csv and note its `id` (catalog_id).
  2. Open its listing page in a browser, right-click an item → Inspect, and find:
       - the CSS selector of one list item,
       - where the link, title and date are inside it.
  3. Open one article and find the element that holds the main text.
  4. Copy this file to crawlers/<name>.py, fill in the TODOs, register the class in
     crawlers/__init__.py, then run:
         cd backend && ../.venv/bin/python -m crawlers.run <name> --max 5
     and look at the saved JSON files in corpus/text_sources/<host>/.
  5. Add a test in tests/test_crawlers.py with a small saved HTML snippet.

Tips:
  - Use self.soup(html) to parse, soup.select(...) / select_one(...) for CSS selectors.
  - Always return absolute URLs: urljoin(page_url, href).
  - parse_polish_date() understands "21 listopada 2026 r.", "21.11.2026", "2026-11-21".
  - If the article has no date, use the date from the listing (link.published_at).
  - Raise ValueError("...") if the page doesn't look as expected; the framework logs it
    and continues with the next article.
  - The example selectors below are the real ones for gov.pl "aktualności" pages
    (e.g. https://www.gov.pl/web/kgpsp/aktualnosci), which many sources share.
"""

from urllib.parse import urljoin

from .base import ArticleLink, Document, ListingCrawler
from .dates import parse_polish_date


class ExampleCrawler(ListingCrawler):
    name = "example"  # TODO: short name for the command line
    catalog_id = 5  # TODO: row id in corpus/sources.csv
    listing_urls = ["https://www.gov.pl/web/kgpsp/aktualnosci"]  # TODO
    license = "Public sector information published on gov.pl (terms: to_verify)"  # TODO

    def parse_listing(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = self.soup(html)
        links = []
        for item in soup.select(".art-prev li"):  # TODO: selector of one list item
            a = item.find("a", href=True)
            if a is None:
                continue
            date_node = item.select_one(".date")  # TODO: where the date is (may be None)
            links.append(
                ArticleLink(
                    url=urljoin(page_url, a["href"]),
                    title=item.select_one(".title").get_text(strip=True) if item.select_one(".title") else None,
                    published_at=parse_polish_date(date_node.get_text()) if date_node else None,
                )
            )
        return links

    def parse_article(self, html: str, link: ArticleLink) -> Document:
        soup = self.soup(html)
        article = soup.select_one("article")  # TODO: element holding the main text
        if article is None:
            raise ValueError("article body not found")
        title_node = soup.select_one("h2, h1")  # TODO: title element
        date_node = soup.select_one(".event-date, .date")  # TODO: date element (optional)
        return Document(
            url=link.url,
            title=title_node.get_text(strip=True) if title_node else (link.title or link.url),
            text=self.clean_text(article),
            published_at=(parse_polish_date(date_node.get_text()) if date_node else None) or link.published_at,
        )
