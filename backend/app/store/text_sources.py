"""On-disk store of every fetched document: corpus/text_sources/<host>/<slug>-<hash>.json.

One JSON file per document (url, title, publisher, dates, text, licence, catalogue info), so:
- crawlers and API seeders skip documents that are already saved and still fresh,
- the search index can be rebuilt at any time without network access,
- the jury can audit exactly what the system knows (plain files in the repository).
"""

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from app.config import REPO_ROOT

TEXT_SOURCES_DIR = REPO_ROOT / "corpus" / "text_sources"

# How long a saved copy is good enough before a crawler should fetch the page again.
REFRESH_AFTER = {
    "real-time": timedelta(hours=1),
    "continuous": timedelta(hours=1),
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "snapshot-daily": timedelta(hours=6),
    "weekly": timedelta(days=7),
    "event-driven": timedelta(days=7),
    "rarely": timedelta(days=30),
}


def path_for(url: str, root: Path = TEXT_SOURCES_DIR) -> Path:
    parsed = urlparse(url)
    host = (parsed.hostname or "unknown").removeprefix("www.")
    slug = re.sub(r"[^a-z0-9]+", "-", parsed.path.lower()).strip("-")[-60:] or "index"
    digest = hashlib.sha1(url.encode()).hexdigest()[:10]
    return root / host / f"{slug}-{digest}.json"


def save(record: dict, root: Path = TEXT_SOURCES_DIR) -> Path:
    if not record.get("retrieved_at"):
        record["retrieved_at"] = datetime.now(UTC).isoformat()
    path = path_for(record["url"], root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def load(url: str, root: Path = TEXT_SOURCES_DIR) -> dict | None:
    path = path_for(url, root)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def is_fresh(record: dict | None, update_frequency: str, now: datetime | None = None) -> bool:
    """True if a saved copy is recent enough that the page need not be fetched again."""
    if not record or not record.get("retrieved_at"):
        return False
    retrieved = datetime.fromisoformat(record["retrieved_at"])
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - retrieved < REFRESH_AFTER.get(update_frequency, timedelta(days=7))


def iter_all(root: Path = TEXT_SOURCES_DIR) -> Iterator[dict]:
    for path in sorted(root.rglob("*.json")):
        yield json.loads(path.read_text(encoding="utf-8"))
