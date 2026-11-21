"""Google Fact Check Tools API connector (ClaimReview data from IFCN fact-checkers).

Results are turned into ordinary corpus records and cached in the local corpus, so they go
through the same retrieval, stance assessment, quote check and scoring as every other source.
We store only the review metadata (checked claim, claimant, rating, title, link), never the
fact-checker's full article.
"""

import csv
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.net import http_client

log = logging.getLogger(__name__)

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
CATALOG_ID = 41  # row of corpus/sources.csv this source is filed under


class FactCheckError(Exception):
    """The API could not be queried (missing key, quota, network). Never a verdict."""


@dataclass(frozen=True)
class KnownFactChecker:
    name: str  # canonical name: the same organisation must always count as ONE publisher
    credibility: int


def load_factcheckers(path: Path) -> dict[str, KnownFactChecker]:
    """site -> canonical name and credibility for known fact-checkers (corpus/factcheckers.csv).

    Publishers not listed keep the name Google reports and the catalogue's default credibility (3).
    """
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {
            row["site"].lower(): KnownFactChecker(row["name"], int(row["credibility"])) for row in csv.DictReader(f)
        }


def site_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


class GoogleFactCheck:
    def __init__(self, api_key: str, known: dict[str, KnownFactChecker] | None = None, timeout: float = 6.0):
        self.api_key = api_key
        self.known = known or {}
        self.client = http_client(timeout=timeout)

    def search(self, query: str, page_size: int = 5, language: str | None = None) -> list[dict]:
        params = {"query": query, "pageSize": page_size, "key": self.api_key}
        if language:
            params["languageCode"] = language
        try:
            resp = self.client.get(API_URL, params=params)
        except httpx.HTTPError as e:
            raise FactCheckError("Google Fact Check API unreachable") from e
        if resp.status_code == 429:
            raise FactCheckError("Google Fact Check API quota exceeded")
        if resp.status_code != 200:
            raise FactCheckError(f"Google Fact Check API error {resp.status_code}")
        return to_records(resp.json().get("claims", []), self.known)


def to_records(claims: list[dict], known: dict[str, KnownFactChecker] | None = None) -> list[dict]:
    """One corpus record per fact-check review."""
    retrieved = datetime.now(UTC).isoformat()
    records = []
    for claim in claims:
        for review in claim.get("claimReview", []):
            url, rating = review.get("url"), review.get("textualRating")
            if not url or not rating:
                continue
            pub = review.get("publisher") or {}
            # Identify the organisation by the review's website, not by the name Google
            # reports: Demagog appears both as "Demagog" and under a page title.
            checker = (known or {}).get(site_of(url))
            publisher = checker.name if checker else (pub.get("name") or pub.get("site"))
            claimant = claim.get("claimant") or "nieznany"
            claim_date = (claim.get("claimDate") or "")[:10] or "brak daty"
            text = (
                f"Sprawdzane twierdzenie: „{claim.get('text', '').strip()}”. "
                f"Autor twierdzenia: {claimant} ({claim_date}). "
                f"Ocena {publisher}: {rating}. "
                f"Tytuł weryfikacji: {review.get('title', '').strip()}"
            )
            records.append(
                {
                    "url": url,
                    "title": review.get("title") or f"Weryfikacja: {rating}",
                    "publisher": publisher or "Fact-checker (Google Fact Check)",
                    "published_at": review.get("reviewDate"),
                    "retrieved_at": retrieved,
                    "text": text,
                    "lang": review.get("languageCode", "pl"),
                    "license": "ClaimReview metadata via Google Fact Check Tools API; full article at source",
                    "catalog_id": CATALOG_ID,
                    "credibility": checker.credibility if checker else None,  # None -> catalogue default
                }
            )
    return records
