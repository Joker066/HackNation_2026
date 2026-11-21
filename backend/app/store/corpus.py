"""Local evidence corpus: documents + passages in SQLite, searched with FTS5/BM25.

Documents are accepted only if they match a row of the audited catalogue
(corpus/sources.csv), so the system can never cite an unlisted source. Each document
inherits publisher, credibility, role and update frequency from its catalogue row.
"""

import csv
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from app.schemas import SourceType

from .db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    domain TEXT NOT NULL,
    catalog_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    credibility INTEGER NOT NULL,
    role TEXT NOT NULL,
    update_frequency TEXT NOT NULL,
    license TEXT,
    lang TEXT,
    published_at TEXT,
    retrieved_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
    text,
    doc_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

# Very common Polish/English words that only add noise to BM25 queries.
STOPWORDS = set(
    "i w z na do że się nie to jest o od po za co jak ale lub oraz czy przez dla przy jako "
    "który która które są był była było być ten ta te tym tego tej the a an of in on to is are "
    "was were and or for with that this it by as at from".split()
)


@dataclass
class CatalogEntry:
    id: int
    url: str
    publisher: str
    domain: str
    source_type: str
    claim_types: str
    credibility: int
    role: str
    update_frequency: str


@dataclass
class Passage:
    passage_id: int
    text: str
    url: str
    title: str
    publisher: str
    domain: str
    source_type: SourceType
    credibility: int
    role: str
    update_frequency: str
    published_at: datetime | None
    retrieved_at: datetime | None


def normalise_url(url: str) -> str:
    """Scheme-less, lower-case host without www., no query/fragment: 'gov.pl/web/gis/x'."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return f"{host}{parsed.path}".rstrip("/")


def load_catalog(path: Path) -> list[CatalogEntry]:
    with path.open(encoding="utf-8", newline="") as f:
        return [
            CatalogEntry(
                id=int(row["id"]),
                url=row["url"],
                publisher=row["publisher"],
                domain=row["domain"],
                source_type=row["source_type"],
                claim_types=row["claim_types"],
                credibility=int(row["credibility"]),
                role=row["role"],
                update_frequency=row["update_frequency"],
            )
            for row in csv.DictReader(f)
        ]


def _match_keys(entry: CatalogEntry) -> list[tuple[int, str]]:
    """(priority, prefix) pairs a document URL can match this entry by."""
    norm = normalise_url(entry.url)
    keys = [(3, norm)]  # the listed page itself and anything below it
    parts = norm.split("/")
    if parts[0] == "gov.pl" and len(parts) >= 3 and parts[1] == "web":
        keys.append((2, "/".join(parts[:3])))  # same gov.pl section, e.g. gov.pl/web/gis
    elif parts[0] != "gov.pl":
        keys.append((1, parts[0]))  # same dedicated host, e.g. ulc.gov.pl
    return keys


def match_catalog(url: str, catalog: list[CatalogEntry], catalog_id: int | None = None) -> CatalogEntry | None:
    """Most specific catalogue row for a document URL (ties: higher credibility)."""
    if catalog_id is not None:
        return next((e for e in catalog if e.id == catalog_id), None)
    doc = normalise_url(url)
    best, best_rank = None, None
    for entry in catalog:
        for priority, key in _match_keys(entry):
            if doc == key or doc.startswith(key + "/"):
                rank = (priority, len(key), entry.credibility)
                if best_rank is None or rank > best_rank:
                    best, best_rank = entry, rank
    return best


def site_domain(host: str) -> str:
    """Group subdomains under one site: podlaska.policja.gov.pl -> policja.gov.pl, sprawdzam.afp.com -> afp.com.

    Used for the "at least 10 domains" count, so regional subdomains are not counted separately.
    """
    labels = host.lower().removeprefix("www.").split(".")
    # Polish functional second-level domains (gov.pl, edu.pl, com.pl, ...) need one more label.
    keep = 3 if len(labels) >= 3 and labels[-1] == "pl" and labels[-2] in {"gov", "edu", "com", "org", "net"} else 2
    return ".".join(labels[-keep:])


def chunk_text(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):  # prefer to cut at a sentence boundary
            cut = text.rfind(". ", start + size // 2, end)
            if cut != -1:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _to_fts_query(query: str) -> str:
    terms = []
    for word in re.findall(r"\w+", query.lower()):
        if len(word) < 3 or word in STOPWORDS:
            continue
        # Crude stemming for Polish inflection: match on the first 6 letters.
        stem = word[:6] if len(word) > 6 else word
        terms.append(f'"{stem}"*')
    return " OR ".join(dict.fromkeys(terms))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class Corpus:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        with connect(db_path) as conn:
            conn.executescript(SCHEMA)

    def add_document(self, record: dict, catalog: list[CatalogEntry]) -> int:
        """Insert one record; returns the number of passages added (0 if skipped).

        A record may set `catalog_id` explicitly (e.g. fact-checks found through the Google
        Fact Check API are filed under that API's catalogue row) and `publisher` to name the
        original author.
        """
        entry = match_catalog(record["url"], catalog, record.get("catalog_id"))
        if entry is None:
            raise ValueError(f"{record['url']!r} does not match any row of the source catalogue")
        chunks = chunk_text(record["text"])
        if not chunks:
            return 0
        with connect(self.db_path) as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO documents
                   (url, title, publisher, domain, catalog_id, source_type, credibility, role,
                    update_frequency, license, lang, published_at, retrieved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["url"],
                    record["title"],
                    record.get("publisher") or entry.publisher,
                    urlparse(record["url"]).hostname or entry.domain,
                    entry.id,
                    entry.source_type,
                    int(record.get("credibility") or entry.credibility),
                    entry.role,
                    entry.update_frequency,
                    record.get("license"),
                    record.get("lang", "pl"),
                    record.get("published_at"),
                    record.get("retrieved_at"),
                ),
            )
            if cur.rowcount == 0:  # URL already indexed
                return 0
            doc_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO passages (text, doc_id) VALUES (?, ?)", [(c, doc_id) for c in chunks]
            )
        return len(chunks)

    def search(self, queries: list[str], k: int = 8, per_doc: int = 2) -> list[Passage]:
        best: dict[int, tuple[float, sqlite3.Row]] = {}
        with connect(self.db_path) as conn:
            for query in queries:
                fts = _to_fts_query(query)
                if not fts:
                    continue
                rows = conn.execute(
                    """SELECT passages.rowid AS pid, passages.text, bm25(passages) AS score, d.*
                       FROM passages JOIN documents d ON d.id = passages.doc_id
                       WHERE passages MATCH ? ORDER BY score LIMIT ?""",
                    (fts, k * 3),
                ).fetchall()
                for row in rows:
                    if row["pid"] not in best or row["score"] < best[row["pid"]][0]:
                        best[row["pid"]] = (row["score"], row)
        results, per_doc_count = [], {}
        for _, row in sorted(best.values(), key=lambda item: item[0]):  # lower bm25 = better
            if per_doc_count.get(row["url"], 0) >= per_doc:
                continue
            per_doc_count[row["url"]] = per_doc_count.get(row["url"], 0) + 1
            results.append(
                Passage(
                    passage_id=row["pid"],
                    text=row["text"],
                    url=row["url"],
                    title=row["title"],
                    publisher=row["publisher"],
                    domain=row["domain"],
                    source_type=SourceType(row["source_type"]),
                    credibility=row["credibility"],
                    role=row["role"],
                    update_frequency=row["update_frequency"],
                    published_at=_parse_dt(row["published_at"]),
                    retrieved_at=_parse_dt(row["retrieved_at"]),
                )
            )
            if len(results) >= k:
                break
        return results

    def stats(self) -> dict:
        with connect(self.db_path) as conn:
            docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            hosts = [r[0] for r in conn.execute("SELECT DISTINCT domain FROM documents")]
            types = [r[0] for r in conn.execute("SELECT DISTINCT source_type FROM documents")]
            passages = conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        sites = sorted({site_domain(h) for h in hosts})
        return {"documents": docs, "domains": len(sites), "domain_list": sites, "source_types": types, "passages": passages}
