"""Web-search fallback: turn allowlisted search results into passages for the normal assessment.

Only called when our own sources leave a claim at "brak wystarczających dowodów". Pages are
fetched by our own fetcher (SSRF guard), split into chunks and the most relevant chunks are
assessed like any other passage (verbatim quote check, catalogue credibility, scoring).
Nothing is stored: media licences do not allow archiving, and the result is used once.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.llm import LLMUsage
from app.schemas import SourceType
from app.sources.web_search import WebSearchError
from app.store.corpus import STOPWORDS, Passage, chunk_text, match_catalog

from .ingest import IngestError, fetch_url

log = logging.getLogger(__name__)

CHUNKS_PER_PAGE = 2


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"\w+", text.lower()) if len(w) >= 4 and w not in STOPWORDS}


def _best_chunks(text: str, stems: set[str], k: int = CHUNKS_PER_PAGE) -> list[str]:
    chunks = chunk_text(text)
    scored = sorted(chunks, key=lambda c: len(_stems(c) & stems), reverse=True)
    return [c for c in scored[:k] if _stems(c) & stems]


def web_search_passages(svc, claim, usage: LLMUsage) -> tuple[list[Passage], str]:
    """(passages, limitation note). Never raises: a failed search is a note, not a verdict."""
    try:
        hits, search_cost, tokens_in, tokens_out = svc.web_search.search(claim.text)
    except WebSearchError as e:
        log.warning("web search failed: %s", e)
        return [], "Wyszukiwanie w zaufanych serwisach internetowych było niedostępne."
    s = svc.settings
    usage.add(
        LLMUsage(
            model=s.llm_model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=search_cost + (tokens_in * s.llm_price_input_per_mtok + tokens_out * s.llm_price_output_per_mtok) / 1e6,
        )
    )

    # Keep only results from catalogue sources that may serve as evidence, and prefer different
    # publishers (round-robin): independent confirmations are what the score rewards.
    by_publisher: dict[str, list] = {}
    for hit in hits:
        entry = match_catalog(hit.url, svc.catalog)
        if entry is not None and entry.role == "evidence":
            group = by_publisher.setdefault(entry.publisher, [])
            if all(hit.url != h.url for h, _ in group):
                group.append((hit, entry))
    accepted = []
    while len(accepted) < s.web_search_pages and any(by_publisher.values()):
        for group in by_publisher.values():
            if group and len(accepted) < s.web_search_pages:
                accepted.append(group.pop(0))
    if not accepted:
        return [], ""

    def fetch(item):
        hit, _entry = item
        try:
            return fetch_url(hit.url)
        except IngestError as e:
            log.info("could not fetch search result %s: %s", hit.url, e.message)
            return None

    with ThreadPoolExecutor(max_workers=len(accepted)) as pool:
        pages = list(pool.map(fetch, accepted))

    stems = _stems(" ".join([claim.text, *claim.search_queries]))
    now = datetime.now(UTC)
    passages = []
    for i, ((hit, entry), page) in enumerate(zip(accepted, pages)):
        if page is None:
            continue
        title, text = page
        published = now - timedelta(days=hit.age_days) if hit.age_days is not None else None
        for k, chunk in enumerate(_best_chunks(text, stems)):
            passages.append(
                Passage(
                    passage_id=-(1000 + i * 10 + k),  # negative ids: not from the stored corpus
                    text=chunk,
                    url=hit.url,
                    title=hit.title or title or hit.url,
                    publisher=entry.publisher,
                    domain=entry.domain,
                    source_type=SourceType(entry.source_type),
                    credibility=entry.credibility,
                    role=entry.role,
                    update_frequency=entry.update_frequency,
                    published_at=published,
                    retrieved_at=now,
                )
            )
    return passages, ""
