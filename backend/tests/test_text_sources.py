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
