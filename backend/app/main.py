"""HTTP API. Every channel (web UI, Discord bot, SMS demo) goes through POST /api/check."""

import hmac
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.llm import build_provider
from app.pipeline.run import Services, run_check
from app.schemas import CheckRequest, CheckResponse
from app.security.ratelimit import RateLimiter
from app.store.audit import AuditLog
from app.sources.google_factcheck import GoogleFactCheck, load_factcheckers
from app.store.corpus import Corpus, load_catalog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
services = Services(
    settings=settings,
    llm=build_provider(settings),
    corpus=Corpus(settings.corpus_db_path),
    audit=AuditLog(settings.audit_db_path),
    catalog=load_catalog(settings.sources_catalog_path),
    factcheck=(
        GoogleFactCheck(settings.google_factcheck_api_key, load_factcheckers(settings.factcheckers_path))
        if settings.google_factcheck_api_key
        else None
    ),
    save_fetched=True,
)
services.audit.purge_older_than(settings.retention_days)
limiter = RateLimiter(settings.rate_limit_per_minute)

app = FastAPI(
    title="Tap & Check API",
    description="Weryfikacja doniesień w oparciu o jawny zbiór wiarygodnych źródeł (zadanie Prawdowid, MSZ).",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_base_url],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.admin_token or not x_admin_token or not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=403, detail="Admin token required")


@app.post("/api/check", response_model=CheckResponse)
def check(req: CheckRequest, request: Request) -> CheckResponse:
    # Rate-limit per session if the channel supplies one, otherwise per client IP.
    key = req.session_id or (request.client.host if request.client else "unknown")
    if not limiter.allow(f"{req.channel}:{key}"):
        raise HTTPException(status_code=429, detail="Zbyt wiele zapytań. Spróbuj ponownie za minutę.")
    return run_check(services, req)


@app.get("/api/check/{request_id}", response_model=CheckResponse)
def get_result(request_id: str) -> CheckResponse:
    result = services.audit.get(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono wyniku (mógł zostać usunięty).")
    return result


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str) -> dict:
    """Let a user delete everything stored for their demo session."""
    return {"deleted": services.audit.delete_session(session_id)}


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_provider": services.llm.name,
        "live_sources": {"google_factcheck": services.factcheck is not None},
        "corpus": services.corpus.stats(),
    }


@app.get("/api/logs", dependencies=[Depends(require_admin)])
def logs(limit: int = 50) -> list[dict]:
    return services.audit.recent(min(limit, 500))


@app.get("/api/metrics", dependencies=[Depends(require_admin)])
def metrics() -> dict:
    return services.audit.metrics()
