"""Build the corpus search index from the saved documents in corpus/text_sources/.

Each JSON file there is one document (see app/store/text_sources.py):
  {"url": "...", "title": "...", "publisher": "...", "published_at": "2025-03-01",
   "retrieved_at": "2026-11-21T10:00:00+00:00", "text": "...", "license": "...", "lang": "pl"}

Run from the backend/ directory:  python -m scripts.build_index [--rebuild]
"""

import argparse
import sys

from app.config import get_settings
from app.store import text_sources
from app.store.corpus import Corpus, load_catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="delete the existing index first")
    args = parser.parse_args()

    settings = get_settings()
    if args.rebuild and settings.corpus_db_path.exists():
        settings.corpus_db_path.unlink()

    catalog = load_catalog(settings.sources_catalog_path)
    corpus = Corpus(settings.corpus_db_path)
    records = list(text_sources.iter_all())

    added = skipped = 0
    for record in records:
        try:
            added += corpus.add_document(record, catalog) > 0
        except (KeyError, ValueError) as e:
            skipped += 1
            print(f"skip {record.get('url', '?')}: {e}", file=sys.stderr)

    stats = corpus.stats()
    print(f"added {added} documents, skipped {skipped}")
    print(f"corpus: {stats}")
    if stats["documents"] < 100 or stats["domains"] < 10 or len(stats["source_types"]) < 2:
        print("WARNING: task minimum is 100 documents, 10 domains, 2 source types", file=sys.stderr)


if __name__ == "__main__":
    main()
