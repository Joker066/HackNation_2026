"""Collect fact-checks on likely topics into corpus/text_sources/ (one JSON file per review).

Topics follow the organisers' source list (warnings, crises, safety, transport, cyber,
health, defence) plus common FIMI narratives. Reviews already saved are not rewritten.

Run from the backend/ directory:  python -m scripts.seed_factchecks
Then rebuild the index:           python -m scripts.build_index --rebuild
"""

import sys
import time
from collections import Counter

from app.config import get_settings
from app.sources.google_factcheck import FactCheckError, GoogleFactCheck, load_factcheckers
from app.store import text_sources

TOPICS = [
    # crises and warnings
    "powódź", "ewakuacja", "alert RCB", "ostrzeżenie IMGW", "susza", "blackout", "brak prądu",
    "skażenie wody", "woda pitna", "pożar", "huragan", "smog",
    # nuclear / radiation
    "promieniowanie", "elektrownia jądrowa", "Zaporoże", "jod tabletki", "Czarnobyl",
    # defence and security
    "mobilizacja", "pobór do wojska", "wojsko polskie", "dron", "rakieta Polska", "NATO",
    "granica Białoruś", "Ukraina wojna", "Rosja Polska", "zamach",
    # migration
    "uchodźcy", "migranci", "imigranci Polska",
    # cyber and scams
    "cyberatak", "phishing", "SMS oszustwo", "bank awaria",
    # transport
    "lotnisko zamknięte", "przestrzeń powietrzna", "PKP pociągi", "autostrada",
    # health
    "szczepionka", "epidemia", "grypa ptasia", "ASF",
    # society, economy, EU
    "Unia Europejska", "ceny prądu", "inflacja", "800 plus", "emerytury", "podatek", "euro waluta",
    "wybory", "Zielony Ład", "5G",
]


def main() -> None:
    settings = get_settings()
    if not settings.google_factcheck_api_key:
        raise SystemExit("Set GOOGLE_FACTCHECK_API_KEY in .env")
    client = GoogleFactCheck(settings.google_factcheck_api_key, load_factcheckers(settings.factcheckers_path))

    saved, publishers = 0, Counter()
    for topic in TOPICS:
        try:
            records = client.search(topic, page_size=10, language="pl")
        except FactCheckError as e:
            print(f"{topic}: {e}", file=sys.stderr)
            continue
        new = [r for r in records if text_sources.load(r["url"]) is None]
        for r in new:
            text_sources.save(r)
            publishers[r["publisher"]] += 1
        saved += len(new)
        print(f"{topic}: {len(records)} results, {len(new)} new")
        time.sleep(0.2)  # be polite to the API

    print(f"\n{saved} new fact-checks saved to {text_sources.TEXT_SOURCES_DIR}")
    print("new by publisher:", dict(publishers.most_common()))


if __name__ == "__main__":
    main()
