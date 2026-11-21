"""Retention and deletion for corpus/text_sources/ (see docs/sources.md).

Retention: full-text articles stored by crawlers are deleted RETENTION_MONTHS after
publication (default 12). Fact-check metadata and excerpts are kept: they are small,
licensed for reuse, and old fact-checks stay relevant.

Deletion on request: remove every document of a source (--catalog-id) or one document (--url).

Run from the backend/ directory:
    ../.venv/bin/python -m scripts.purge_sources                 # apply retention
    ../.venv/bin/python -m scripts.purge_sources --dry-run       # show what would be deleted
    ../.venv/bin/python -m scripts.purge_sources --catalog-id 28 # delete a whole source
    ../.venv/bin/python -m scripts.purge_sources --url https://… # delete one document
Add --rebuild-index to rebuild the search index after deleting something.
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import get_settings
from app.store import text_sources


def _published(record: dict) -> datetime | None:
    value = record.get("published_at")
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def select(records: list[tuple[Path, dict]], args, now: datetime) -> list[tuple[Path, dict, str]]:
    chosen = []
    cutoff = now - timedelta(days=30 * args.older_than_months)
    for path, rec in records:
        if args.url:
            if rec.get("url") == args.url:
                chosen.append((path, rec, "requested (url)"))
        elif args.catalog_id is not None:
            if rec.get("catalog_id") == args.catalog_id:
                chosen.append((path, rec, f"requested (source {args.catalog_id})"))
        else:  # retention: only full-text articles stored by crawlers
            published = _published(rec)
            full_text = rec.get("crawler") and rec.get("storage", "full_text") == "full_text"
            if full_text and published and published < cutoff:
                chosen.append((path, rec, f"retention (> {args.older_than_months} months)"))
    return chosen


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--older-than-months", type=int, default=settings.corpus_retention_months)
    parser.add_argument("--catalog-id", type=int, help="delete all documents of this catalogue row")
    parser.add_argument("--url", help="delete the document with this URL")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true", help="rebuild the search index afterwards")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    root = text_sources.TEXT_SOURCES_DIR
    records = [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(root.rglob("*.json"))]
    chosen = select(records, args, datetime.now(UTC))

    for path, rec, reason in chosen:
        if not args.quiet:
            print(f"{'would delete' if args.dry_run else 'deleted'}: {rec.get('url')}  [{reason}]")
        if not args.dry_run:
            path.unlink()
    if not args.quiet or chosen:
        print(f"{len(chosen)} of {len(records)} documents {'would be ' if args.dry_run else ''}deleted")

    if chosen and not args.dry_run and args.rebuild_index:
        subprocess.run([sys.executable, "-m", "scripts.build_index", "--rebuild"], check=True)


if __name__ == "__main__":
    main()
