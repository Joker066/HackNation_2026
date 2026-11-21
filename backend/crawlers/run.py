"""Run crawlers and save documents to corpus/text_sources/.

Run from the backend/ directory:
    ../.venv/bin/python -m crawlers.run --list          # show available crawlers
    ../.venv/bin/python -m crawlers.run rcb             # run one
    ../.venv/bin/python -m crawlers.run --all           # run all
    ../.venv/bin/python -m crawlers.run rcb --force     # re-fetch even if a fresh copy exists
Then rebuild the index:
    ../.venv/bin/python -m scripts.build_index --rebuild
"""

import argparse
import logging
import sys

from . import REGISTRY
from .fetch import Fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="crawler names (see --list)")
    parser.add_argument("--all", action="store_true", help="run every registered crawler")
    parser.add_argument("--list", action="store_true", help="list crawlers and exit")
    parser.add_argument("--max", type=int, default=30, help="max new documents per crawler")
    parser.add_argument("--force", action="store_true", help="ignore saved copies and re-fetch")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one host")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.list:
        for name, cls in REGISTRY.items():
            print(f"{name:12} catalog_id={cls.catalog_id}")
        return
    names = list(REGISTRY) if args.all else args.names
    unknown = [n for n in names if n not in REGISTRY]
    if not names or unknown:
        parser.error(f"unknown or missing crawler names: {unknown or '(none)'}; use --list")

    fetcher = Fetcher(delay_seconds=args.delay)
    failures = 0
    try:
        for name in names:
            stats = REGISTRY[name](fetcher).run(max_documents=args.max, force=args.force)
            print(f"{name}: saved {stats.saved}, already fresh {stats.skipped_fresh}, failed {stats.failed}")
            for error in stats.errors[:10]:
                print(f"  ! {error}", file=sys.stderr)
            failures += stats.failed
    finally:
        fetcher.close()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
