"""Crawler framework.

An adapter only knows how to read ONE site's HTML. Everything else is handled here:
fetching (robots.txt, delays), skipping documents already saved, attaching catalogue
metadata, saving to corpus/text_sources/, and error handling.

Two kinds of adapter:

- ListingCrawler   a news/warnings list page whose items link to article pages.
                   Implement parse_listing() and parse_article(). Most sources are like this.
- SnapshotCrawler  one page that the publisher overwrites in place (e.g. RCB daily report).
                   Implement parse_snapshot(). Each day's version is saved as its own document.

See crawlers/_template.py for a commented example to copy.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from app.config import get_settings
from app.store import text_sources
from app.store.corpus import CatalogEntry, load_catalog

from .fetch import FetchError, Fetcher

log = logging.getLogger(__name__)

# zero-width space / joiners and byte-order mark, common in CMS-generated HTML
INVISIBLE = str.maketrans("", "", "​‌‍⁠﻿")


@dataclass
class ArticleLink:
    """One item found on a listing page."""

    url: str
    title: str | None = None
    published_at: datetime | None = None


@dataclass
class Document:
    """What an adapter extracts from a page. Metadata is added by the framework."""

    url: str
    title: str
    text: str
    published_at: datetime | None


@dataclass
class CrawlStats:
    saved: int = 0
    skipped_fresh: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class Crawler(ABC):
    #: short unique name used on the command line, e.g. "rcb"
    name: str
    #: id of this source's row in corpus/sources.csv (gives publisher, credibility, ...)
    catalog_id: int
    #: licence / terms note stored with every document
    license: str = "to_verify: check the site's terms of use"

    def __init__(self, fetcher: Fetcher, catalog: list[CatalogEntry] | None = None):
        self.fetcher = fetcher
        catalog = catalog if catalog is not None else load_catalog(get_settings().sources_catalog_path)
        entry = next((e for e in catalog if e.id == self.catalog_id), None)
        if entry is None:
            raise ValueError(f"{self.name}: catalog_id {self.catalog_id} not in sources.csv")
        self.entry = entry

    @abstractmethod
    def run(self, max_documents: int, force: bool) -> CrawlStats: ...

    # -- helpers for adapters ---------------------------------------------------

    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    @staticmethod
    def clean_text(node) -> str:
        """Visible text of a node, without scripts, styles and navigation."""
        for tag in node(["script", "style", "noscript", "nav", "form", "button", "iframe"]):
            tag.decompose()
        text = node.get_text("\n").translate(INVISIBLE).replace("\xa0", " ")
        lines = [" ".join(line.split()) for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    # -- saving -------------------------------------------------------------------

    def _record(self, doc: Document, **extra) -> dict:
        return {
            "url": doc.url,
            "title": doc.title,
            "publisher": self.entry.publisher,
            "published_at": doc.published_at.isoformat() if doc.published_at else None,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "text": doc.text,
            "lang": "pl",
            "license": self.license,
            "catalog_id": self.catalog_id,
            "crawler": self.name,
            **extra,
        }

    def _save(self, doc: Document, stats: CrawlStats, **extra) -> None:
        if len(doc.text) < 80:
            stats.failed += 1
            stats.errors.append(f"{doc.url}: extracted text too short ({len(doc.text)} chars)")
            return
        text_sources.save(self._record(doc, **extra))
        stats.saved += 1


class ListingCrawler(Crawler):
    #: pages listing the articles (first page is enough for a daily crawl)
    listing_urls: list[str]

    @abstractmethod
    def parse_listing(self, html: str, page_url: str) -> list[ArticleLink]:
        """Return the article links found on a listing page (absolute URLs)."""

    @abstractmethod
    def parse_article(self, html: str, link: ArticleLink) -> Document:
        """Extract title, text and publication date from an article page."""

    def run(self, max_documents: int = 30, force: bool = False) -> CrawlStats:
        stats = CrawlStats()
        links: list[ArticleLink] = []
        for page_url in self.listing_urls:
            try:
                links.extend(self.parse_listing(self.fetcher.get_html(page_url), page_url))
            except FetchError as e:
                stats.failed += 1
                stats.errors.append(str(e))
        seen = set()
        for link in links:
            if link.url in seen:
                continue
            seen.add(link.url)
            if stats.saved >= max_documents:
                break
            # Articles rarely change after publication: if we have it, skip it.
            if not force and text_sources.load(link.url) is not None:
                stats.skipped_fresh += 1
                continue
            try:
                doc = self.parse_article(self.fetcher.get_html(link.url), link)
                self._save(doc, stats)
            except (FetchError, ValueError) as e:
                stats.failed += 1
                stats.errors.append(f"{link.url}: {e}")
        return stats


class SnapshotCrawler(Crawler):
    #: the page that is overwritten in place
    page_url: str

    @abstractmethod
    def parse_snapshot(self, html: str) -> Document:
        """Extract the current version. Return its date in published_at (required)."""

    def snapshot_url(self, published_at: datetime) -> str:
        """Each day's version gets its own document id (the fragment is ignored by browsers)."""
        return f"{self.page_url}#{published_at.date().isoformat()}"

    def run(self, max_documents: int = 1, force: bool = False) -> CrawlStats:
        stats = CrawlStats()
        today_url = self.snapshot_url(datetime.now(UTC))
        if not force and text_sources.is_fresh(text_sources.load(today_url), self.entry.update_frequency):
            stats.skipped_fresh += 1
            return stats
        try:
            doc = self.parse_snapshot(self.fetcher.get_html(self.page_url))
        except (FetchError, ValueError) as e:
            stats.failed += 1
            stats.errors.append(str(e))
            return stats
        if doc.published_at is None:
            stats.failed += 1
            stats.errors.append(f"{self.page_url}: no date found in the snapshot")
            return stats
        doc.url = self.snapshot_url(doc.published_at)
        self._save(doc, stats, snapshot_of=self.page_url)
        return stats
