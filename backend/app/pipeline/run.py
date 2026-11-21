"""Orchestrates one check end to end. Every channel calls `run_check`, so results match."""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import Settings
from app.llm import LLMError, LLMProvider, LLMUsage
from app.schemas import CheckRequest, CheckResponse, ClaimResult, Evidence, Stance, Status
from app.security.injection import looks_like_injection
from app.security.pii import mask_pii
from app.store.audit import AuditLog
from app.store.corpus import Corpus

from .assess import assess, quote_is_verbatim
from .claims import ExtractedClaim, extract_claims
from .compose import compose
from .ingest import IngestError, ingest
from .scoring import DIRECTNESS_FACTOR
from .verdict import decide, is_archival

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


@dataclass
class _ClaimOutcome:
    result: ClaimResult
    usage: LLMUsage
    security_events: list[str] = field(default_factory=list)
    retrieval_error: bool = False


def _check_claim(svc: Services, claim: ExtractedClaim) -> _ClaimOutcome:
    usage = LLMUsage(model=getattr(svc.llm, "name", "unknown"))
    events: list[str] = []

    if claim.kind != "factual":
        decision = decide(kind=claim.kind, evidence=[], misleading_context=False)
        return _ClaimOutcome(compose(claim.text, decision, [], "", []), usage)

    retrieval_error = False
    try:
        passages = svc.corpus.search([claim.text, *claim.search_queries], k=svc.settings.passages_per_claim)
    except Exception:  # a search failure must not turn into a verdict
        log.exception("corpus search failed")
        passages, retrieval_error = [], True

    clean = []
    for p in passages:
        if looks_like_injection(p.text):
            events.append(f"Pominięto fragment źródła z instrukcjami dla modelu: {p.url}")
        else:
            clean.append(p)

    findings, misleading, misleading_reason, evidence = "", False, "", []
    if clean:
        assessment, u = assess(svc.llm, claim, clean)
        usage.add(u)
        by_id = {p.passage_id: p for p in clean}
        for j in assessment.passages:
            p = by_id.get(j.passage_id)
            if p is None or j.stance == "irrelevant":
                continue
            if not quote_is_verbatim(j.quote, p.text):
                log.info("dropped unverifiable quote for passage %s", p.passage_id)
                continue
            evidence.append(
                Evidence(
                    stance=Stance(j.stance),
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
        findings, misleading, misleading_reason = (
            assessment.findings_summary,
            assessment.misleading_context,
            assessment.misleading_reason,
        )

    decision = decide(
        kind=claim.kind,
        evidence=evidence,
        misleading_context=misleading,
        misleading_reason=misleading_reason,
        refers_to_present=claim.refers_to_present,
    )
    if retrieval_error:
        decision.limitations = (decision.limitations + " Wyszukiwanie w źródłach nie powiodło się.").strip()
    return _ClaimOutcome(compose(claim.text, decision, evidence, findings, []), usage, events, retrieval_error)


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
    masked_input = mask_pii((req.text or "") + (f" {req.url}" if req.url else ""))
    retrieval_errors = 0

    try:
        ingested = ingest(req, svc.settings)
        text = mask_pii(ingested.text)
        response.input_summary = (ingested.page_title or text)[:200]
        if looks_like_injection(text):
            response.security_events.append("Wiadomość zawierała polecenia dla modelu — zostały zignorowane.")

        extraction, u = extract_claims(svc.llm, text, svc.settings.max_claims)
        usage.add(u)
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
                if ingested.notes:
                    o.result.limitations = " ".join([o.result.limitations, *ingested.notes]).strip()
                response.claims.append(o.result)
                response.security_events.extend(o.security_events)
                usage.add(o.usage)
                retrieval_errors += int(o.retrieval_error)
    except IngestError as e:
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
