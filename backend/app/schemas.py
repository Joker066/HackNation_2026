"""Public response contract, shared by every channel (web, Discord, SMS demo)."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    ok = "ok"
    error = "error"  # technical failure: never a verdict
    needs_clarification = "needs_clarification"
    out_of_scope = "out_of_scope"


class Verdict(str, Enum):
    confirmed = "potwierdzone"
    false = "fałszywe"
    misleading = "wprowadzające_w_błąd"
    insufficient = "brak_wystarczających_dowodów"
    unverifiable = "nie_podlega_weryfikacji"


class Strength(str, Enum):
    high = "wysoka"
    medium = "średnia"
    low = "niska"


class Stance(str, Enum):
    supports = "supports"
    refutes = "refutes"
    context = "context"


class SourceType(str, Enum):
    official = "official"  # primary / government / legal text
    factcheck = "factcheck"  # IFCN/EFCSN fact-checkers, EUvsDisinfo, EDMO
    media = "media"
    dataset = "dataset"


class Evidence(BaseModel):
    stance: Stance
    title: str
    publisher: str
    url: str
    published_at: datetime | None
    retrieved_at: datetime | None
    quote: str
    source_type: SourceType
    credibility: int  # 1-5 from the audited catalogue
    role: str = "evidence"  # evidence | context_only (shown, never decisive)
    update_frequency: str = "weekly"
    recency: float = 1.0  # 0-1, see pipeline/scoring.py
    directness: float = 1.0  # explicit 1.0 / implicit 0.7
    weight: float = 0.0  # credibility/5 × recency × directness (capped at 0.95)
    archival_warning: bool = False


class ClaimResult(BaseModel):
    text: str
    verdict: Verdict
    strength: Strength | None  # None when the verdict is an abstention or unverifiable
    score: float | None = None  # −1 (sources refute) … +1 (sources confirm); None if unverifiable
    reasons: list[str] = Field(default_factory=list)
    explanation: str  # plain Polish, built from verified evidence only
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: str = ""
    source_warnings: list[str] = Field(default_factory=list)


class CheckRequest(BaseModel):
    text: str | None = None
    url: str | None = None
    channel: str = "web"
    session_id: str | None = None


class CheckResponse(BaseModel):
    request_id: str
    created_at: datetime
    status: Status
    status_detail: str | None = None  # plain Polish message for non-ok statuses
    input_summary: str = ""
    claims: list[ClaimResult] = Field(default_factory=list)
    security_events: list[str] = Field(default_factory=list)
    result_url: str | None = None
