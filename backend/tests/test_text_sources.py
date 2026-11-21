from datetime import UTC, datetime, timedelta

from app.store import text_sources


def test_save_load_and_iterate(tmp_path):
    record = {"url": "https://www.gov.pl/web/rcb/raport-dobowy3", "title": "Raport", "text": "Treść"}
    path = text_sources.save(dict(record), tmp_path)
    assert path.parent.name == "gov.pl" and path.name.startswith("web-rcb-raport-dobowy3-")
    loaded = text_sources.load(record["url"], tmp_path)
    assert loaded["text"] == "Treść" and loaded["retrieved_at"]
    assert [r["url"] for r in text_sources.iter_all(tmp_path)] == [record["url"]]
    assert text_sources.load("https://www.gov.pl/other", tmp_path) is None


def test_freshness_depends_on_update_frequency():
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)
    two_hours_ago = {"retrieved_at": (now - timedelta(hours=2)).isoformat()}
    assert not text_sources.is_fresh(two_hours_ago, "hourly", now)  # warnings: re-fetch
    assert text_sources.is_fresh(two_hours_ago, "daily", now)
    assert text_sources.is_fresh({"retrieved_at": (now - timedelta(days=20)).isoformat()}, "rarely", now)
    assert not text_sources.is_fresh(None, "rarely", now)


def test_excerpt_cuts_at_sentence_end():
    from crawlers.base import Crawler
    text = "Tytuł\n" + "Pierwsze zdanie artykułu jest tutaj. " * 40
    out = Crawler.excerpt(text, limit=200)
    assert len(out) <= 210 and out.endswith(". […]")
    assert Crawler.excerpt("Krótki tekst.") == "Krótki tekst."


def test_excerpt_storage_is_driven_by_the_catalogue():
    from crawlers.base import Document
    from crawlers.kgsok import KgsokCrawler

    class F:  # no network needed
        def get_html(self, url): raise AssertionError

    crawler = KgsokCrawler(F())
    assert crawler.entry.storage == "excerpt"
    rec = crawler._record(Document(url="https://kgsok.pl/x/", title="T", text="Zdanie. " * 300, published_at=None))
    assert rec["storage"] == "excerpt" and len(rec["text"]) < 800 and "all rights reserved" in rec["license"]


def test_purge_selects_only_old_crawled_full_texts():
    from argparse import Namespace
    from datetime import UTC, datetime
    from pathlib import Path

    from scripts.purge_sources import select

    now = datetime(2026, 11, 21, tzinfo=UTC)
    recs = [
        (Path("a"), {"url": "old-news", "crawler": "policja", "storage": "full_text", "published_at": "2025-01-01"}),
        (Path("b"), {"url": "new-news", "crawler": "policja", "storage": "full_text", "published_at": "2026-10-01"}),
        (Path("c"), {"url": "old-factcheck", "catalog_id": 41, "published_at": "2019-01-01"}),  # metadata: kept
        (Path("d"), {"url": "old-excerpt", "crawler": "kgsok", "storage": "excerpt", "published_at": "2024-01-01"}),
    ]
    args = Namespace(older_than_months=12, url=None, catalog_id=None)
    assert [r["url"] for _, r, _ in select(recs, args, now)] == ["old-news"]
    args = Namespace(older_than_months=12, url=None, catalog_id=41)
    assert [r["url"] for _, r, _ in select(recs, args, now)] == ["old-factcheck"]
