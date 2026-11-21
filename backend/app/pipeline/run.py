"""Orchestrates one check end to end. Every channel calls `run_check`, so results match."""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import Settings
from app.llm import LLMError, LLMProvider, LLMUsage
from app.schemas import CheckRequest, CheckResponse, ClaimResult, Evidence, Stance, Status, Verdict
from app.security.injection import looks_like_injection
from app.security.pii import mask_pii
from app.store.audit import AuditLog
from app.sources.euvsdisinfo import EUvsDisinfo, EUvsDisinfoError
from app.sources.google_factcheck import FactCheckError, GoogleFactCheck
from app.sources.web_search import WebSearch
from app.store import text_sources
from app.store.corpus import CatalogEntry, Corpus, Passage

from .assess import assess, fact_check_rating, quote_is_verbatim, stance_from_rating
from .claims import ExtractedClaim, extract_claims
from .compose import compose
from .image import IMAGE_LIMITATIONS, ImageError, as_text, decode_image, read_image
from .ingest import IngestError, ingest
from .scoring import DIRECTNESS_FACTOR
from .verdict import decide, is_archival
from .web_evidence import web_search_passages

log = logging.getLogger(__name__)

LLM_ERROR_MESSAGES = {
    "misconfigured": "Usługa nie jest poprawnie skonfigurowana (brak klucza modelu). To błąd techniczny, nie wynik sprawdzenia.",
    "auth": "Usługa nie może połączyć się z modelem językowym (problem z kluczem). To błąd techniczny, nie wynik sprawdzenia.",
    "rate_limited": "Usługa jest chwilowo przeciążona. Spróbuj ponownie za minutę. To nie jest wynik sprawdzenia.",
    "unavailable": "Model językowy jest chwilowo niedostępny. Spróbuj ponownie później. To nie jest wynik sprawdzenia.",
    "refused": "Nie udało się przetworzyć tej treści. To nie jest wynik sprawdzenia.",
    "bad_output": "Wystąpił błąd podczas analizy. Spróbuj ponownie. To nie jest wynik sprawdzenia.",
}


@dataclass
class Services:
    settings: Settings
    llm: LLMProvider
    corpus: Corpus
    audit: AuditLog
    catalog: list[CatalogEntry] = field(default_factory=list)
    factcheck: GoogleFactCheck | None = None
    euvsdisinfo: EUvsDisinfo | None = None
    web_search: "WebSearch | None" = None  # fallback when own sources leave a claim undecided
    save_fetched: bool = False  # write live-fetched documents to corpus/text_sources/


@dataclass
class _ClaimOutcome:
    result: ClaimResult
    usage: LLMUsage
    security_events: list[str] = field(default_factory=list)
    retrieval_error: bool = False


def _fetch_live_sources(svc: Services, claim: ExtractedClaim) -> list[str]:
    """Query the live sources for this claim and cache their documents in the corpus.

    Google Fact Check gets the claim's keyword queries; EUvsDisinfo (an English database)
    gets the claim's English query first. Returns limitation notes for sources that failed.
    """
    queries = list(dict.fromkeys(claim.search_queries))
    jobs: list[tuple[str, object, str]] = []  # (source label, search function, query)
    if svc.factcheck is not None:
        for q in queries[: svc.settings.factcheck_queries_per_claim]:
            jobs.append(("Google Fact Check", svc.factcheck.search, q))
    if svc.euvsdisinfo is not None:
        eu_queries = [q for q in dict.fromkeys([claim.english_query, *queries]) if q][
            : svc.settings.euvsdisinfo_queries_per_claim
        ]
        for q in eu_queries:
            jobs.append(("EUvsDisinfo", svc.euvsdisinfo.search, q))
    if not jobs:
        return []

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [(label, pool.submit(fn, q)) for label, fn, q in jobs]
    attempts: dict[str, int] = {}
    failures: dict[str, int] = {}
    for label, future in futures:
        attempts[label] = attempts.get(label, 0) + 1
        try:
            for record in future.result():
                if svc.corpus.add_document(record, svc.catalog) and svc.save_fetched:
                    text_sources.save(record)  # keep it for future index rebuilds
        except (FactCheckError, EUvsDisinfoError) as e:
            log.warning("%s search failed: %s", label, e)
            failures[label] = failures.get(label, 0) + 1
        except ValueError:
            log.exception("could not store a record from %s", label)
    return [
        f"Źródło {label} było niedostępne — wynik opiera się tylko na pozostałych źródłach."
        for label, n in failures.items()
        if n == attempts[label]
    ]


MAX_SOURCE_WARNINGS = 2  # more than two context notes per claim only adds noise


def _source_warnings(evidence: list[Evidence]) -> list[str]:
    """Neutral notes for context-only matches (never part of the verdict)."""
    notes = []
    for e in evidence:
        if e.role == "context_only":
            notes.append(
                f"Podobny wątek opisuje baza EUvsDisinfo (przypadki prokremlowskiej dezinformacji): "
                f"„{e.title}”. To informacja o kontekście, a nie ocena tego twierdzenia."
            )
    return list(dict.fromkeys(notes))[:MAX_SOURCE_WARNINGS]


@dataclass
class _Judgement:
    evidence: list[Evidence] = field(default_factory=list)
    findings: str = ""
    misleading: bool = False
    misleading_reason: str = ""


def _clean(passages: list[Passage], events: list[str]) -> list[Passage]:
    """Drop passages that contain instructions aimed at the model (and log them)."""
    clean = []
    for p in passages:
        if looks_like_injection(p.text):
            events.append(f"Pominięto fragment źródła z instrukcjami dla modelu: {p.url}")
        else:
            clean.append(p)
    return clean


def _judge(svc: Services, claim: ExtractedClaim, passages: list[Passage], usage: LLMUsage) -> _Judgement:
    """Model judges each passage; code verifies quotes, translates ratings and builds evidence."""
    if not passages:
        return _Judgement()
    assessment, u = assess(svc.llm, claim, passages)
    usage.add(u)
    by_id = {p.passage_id: p for p in passages}
    seen_quotes: set[tuple[str, str]] = set()
    rating_says_misleading = False
    evidence = []
    for j in assessment.passages:
        p = by_id.get(j.passage_id)
        if p is None or j.stance == "irrelevant":
            continue
        stance = j.stance
        rating = fact_check_rating(p.text)
        if rating is not None:
            # Fact-check record: the model only judged whether it is about the same claim;
            # the rating is translated into a stance here, deterministically.
            mapped = stance_from_rating(rating)
            if j.same_claim and mapped is not None:
                stance, rating_misleading = mapped
                rating_says_misleading = rating_says_misleading or rating_misleading
            else:
                stance = "context"
        if not quote_is_verbatim(j.quote, p.text):
            log.info("dropped unverifiable quote for passage %s", p.passage_id)
            continue
        if (p.url, j.quote.strip()) in seen_quotes:  # overlapping passages of one document
            continue
        seen_quotes.add((p.url, j.quote.strip()))
        evidence.append(
            Evidence(
                stance=Stance(stance),
                title=p.title,
                publisher=p.publisher,
                url=p.url,
                published_at=p.published_at,
                retrieved_at=p.retrieved_at,
                quote=j.quote.strip(),
                source_type=p.source_type,
                credibility=p.credibility,
                role=p.role,
                update_frequency=p.update_frequency,
                directness=DIRECTNESS_FACTOR[j.directness],
                archival_warning=is_archival(p.published_at, svc.settings.archival_after_days),
            )
        )
    return _Judgement(
        evidence=evidence,
        findings=assessment.findings_summary,
        misleading=assessment.misleading_context or rating_says_misleading,
        misleading_reason=assessment.misleading_reason
        or ("Fact-checker ocenił to twierdzenie jako częściowo prawdziwe lub pozbawione kontekstu." if rating_says_misleading else ""),
    )


def _decide(claim: ExtractedClaim, j: _Judgement):
    return decide(
        kind=claim.kind,
        evidence=j.evidence,
        misleading_context=j.misleading,
        misleading_reason=j.misleading_reason,
        time_sensitive=claim.time_sensitive,
    )


def _check_claim(svc: Services, claim: ExtractedClaim) -> _ClaimOutcome:
    usage = LLMUsage(model=getattr(svc.llm, "name", "unknown"))
    events: list[str] = []

    if claim.kind != "factual":
        decision = decide(kind=claim.kind, evidence=[], misleading_context=False)
        return _ClaimOutcome(compose(claim.text, decision, [], "", []), usage)

    # 1. Our own sources (corpus + live fact-check and disinformation databases).
    retrieval_error = False
    live_notes = _fetch_live_sources(svc, claim)
    try:
        passages = svc.corpus.search(
            [claim.text, *claim.search_queries, claim.english_query], k=svc.settings.passages_per_claim
        )
    except Exception:  # a search failure must not turn into a verdict
        log.exception("corpus search failed")
        passages, retrieval_error = [], True
    judgement = _judge(svc, claim, _clean(passages, events), usage)
    decision = _decide(claim, judgement)

    # 2. Still undecided: search allowlisted domains on the web, judge those pages the same way.
    if decision.verdict == Verdict.insufficient and svc.web_search is not None:
        web_passages, web_note = web_search_passages(svc, claim, usage)
        if web_note:
            live_notes.append(web_note)
        known = {e.url for e in judgement.evidence}
        web_passages = [p for p in _clean(web_passages, events) if p.url not in known]
        if web_passages:
            extra = _judge(svc, claim, web_passages, usage)
            # Search results may confirm or refute, but cannot by themselves make a claim
            # "misleading": related articles about other dates or places too easily trigger that
            # flag. It stays reserved for our audited sources and fact-check ratings.
            judgement = _Judgement(
                evidence=judgement.evidence + extra.evidence,
                findings=extra.findings or judgement.findings,
                misleading=judgement.misleading,
                misleading_reason=judgement.misleading_reason,
            )
            decision = _decide(claim, judgement)

    if decision.verdict == Verdict.insufficient and claim.verifying_source.strip():
        decision.limitations = (
            f"{decision.limitations} Do rozstrzygnięcia potrzebny byłby np.: {claim.verifying_source.strip().rstrip('.')}."
        ).strip()
    if retrieval_error:
        decision.limitations = (decision.limitations + " Wyszukiwanie w źródłach nie powiodło się.").strip()
    if live_notes:
        decision.limitations = " ".join([decision.limitations, *live_notes]).strip()
        retrieval_error = True
    warnings = _source_warnings(judgement.evidence)
    return _ClaimOutcome(
        compose(claim.text, decision, judgement.evidence, judgement.findings, warnings), usage, events, retrieval_error
    )


def run_check(svc: Services, req: CheckRequest) -> CheckResponse:
    started = time.monotonic()
    request_id = uuid.uuid4().hex[:12]
    response = CheckResponse(
        request_id=request_id,
        created_at=datetime.now(UTC),
        status=Status.ok,
        result_url=f"{svc.settings.public_base_url.rstrip('/')}/r/{request_id}",
    )
    usage = LLMUsage(model=getattr(svc.llm, "name", "unknown"))
    # The audit log never stores the image itself, only a marker (plus the masked text read from it below).
    masked_input = mask_pii((req.text or "") + (f" {req.url}" if req.url else "") + (" [obraz]" if req.image else ""))
    retrieval_errors = 0

    try:
        ingested = ingest(req, svc.settings)
        notes = list(ingested.notes)
        raw_text = ingested.text
        if req.image:
            image = decode_image(req.image, req.image_media_type)
            reading, u = read_image(svc.llm, image)
            usage.add(u)
            if not reading.readable and not raw_text.strip():
                raise ImageError(
                    Status.needs_clarification,
                    "Nie udało się odczytać z obrazu treści do sprawdzenia. Wyślij wyraźniejszy obraz albo wklej tekst.",
                )
            response.image_text = mask_pii(as_text(reading))
            raw_text = f"{raw_text}\n\n{as_text(reading)}".strip()
            notes.append(IMAGE_LIMITATIONS)
        text = mask_pii(raw_text)
        if looks_like_injection(text):
            response.security_events.append("Wiadomość zawierała polecenia dla modelu — zostały zignorowane.")

        extraction, u = extract_claims(svc.llm, text, svc.settings.max_claims)
        usage.add(u)
        response.input_kind = extraction.input_kind
        if extraction.status != "ok" or not extraction.claims:
            response.status = (
                Status.out_of_scope if extraction.status == "out_of_scope" else Status.needs_clarification
            )
            response.status_detail = (
                "To pytanie wykracza poza zakres usługi — sprawdzamy doniesienia o faktach."
                if response.status == Status.out_of_scope
                else "Nie znaleziono w wiadomości twierdzenia do sprawdzenia. Napisz, co dokładnie chcesz zweryfikować."
            )
        else:
            with ThreadPoolExecutor(max_workers=len(extraction.claims)) as pool:
                outcomes = list(pool.map(lambda c: _check_claim(svc, c), extraction.claims))
            for o in outcomes:
                if notes:
                    o.result.limitations = " ".join([o.result.limitations, *notes]).strip()
                response.claims.append(o.result)
                response.security_events.extend(o.security_events)
                usage.add(o.usage)
                retrieval_errors += int(o.retrieval_error)
    except (IngestError, ImageError) as e:
        response.status, response.status_detail = e.status, e.message
    except LLMError as e:
        log.warning("LLM error (%s): %s", e.kind, e)
        response.status = Status.error
        response.status_detail = LLM_ERROR_MESSAGES.get(e.kind, LLM_ERROR_MESSAGES["bad_output"])
        response.claims = []  # never return a partial result that looks like a verdict
    except Exception:
        log.exception("unexpected pipeline failure")
        response.status = Status.error
        response.status_detail = "Wystąpił nieoczekiwany błąd techniczny. To nie jest wynik sprawdzenia."
        response.claims = []

    if response.status != Status.ok:
        response.result_url = None
    response.security_events = list(dict.fromkeys(response.security_events))

    svc.audit.save(
        response,
        channel=req.channel,
        session_id=req.session_id,
        input_masked=masked_input[:2000],
        latency_ms=int((time.monotonic() - started) * 1000),
        llm_model=usage.model,
        llm_input_tokens=usage.input_tokens,
        llm_output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
        retrieval_errors=retrieval_errors,
    )
    return response
