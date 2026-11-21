"""Evidence scoring: every claim gets ONE number, score = f(all features), from −1 (sources
refute) to +1 (sources confirm).

Features of each piece of evidence (multiplied into its weight):
    credibility   1-5 from the audited catalogue            → credibility / 5
    recency       age vs. how fast the source changes        → 0.5 ^ (age / half-life)
    directness    passage states the point explicitly?       → explicit 1.0, implicit 0.7
    quote check   quote is verbatim in the source            → evidence dropped if not (in run.py)
    role          context_only sources (EUvsDisinfo)         → 0
Features of the claim as a whole (combined in claim_score):
    stance        supports (+) or refutes (−)
    independence  each publisher counts once
    supersession  a publisher's latest statement replaces its earlier ones

    weight(source)   = min(credibility/5 × recency × directness × role, 0.95)
    strength(source) = −ln(1 − weight)                     # evidence in "log" units
    balance          = Σ strength(supporting) − Σ strength(refuting)
    score            = sign(balance) × (1 − e^−|balance|)  # back to the range −1…+1

Why this form:
- With sources on one side only, it equals 1 − Π(1 − weight): independent confirmations
  add up (two 0.6 sources → 0.84) but never reach certainty.
- In a conflict, strong evidence outweighs weak evidence instead of merely being reduced
  by it (official 0.95 vs fact-check 0.6 → +0.92), and equal sources cancel out (→ 0).
- credibility (1-5) comes from the audited catalogue (corpus/sources.csv).
- recency halves every half-life, set by how fast the source changes. It applies only when
  the claim is about the present; a 2022 article about a 2022 event is not stale.
- Each publisher counts once (its strongest item), and if a publisher said both things, only
  its latest statement counts: an issued-then-lifted warning is not a conflict.
- context_only sources (e.g. EUvsDisinfo) get weight 0: shown to the user, never decisive.
"""

import math
from datetime import UTC, datetime

from app.schemas import Evidence, Stance

# Half-life in days per catalogue update_frequency. None = does not go stale.
HALF_LIFE_DAYS: dict[str, float | None] = {
    "real-time": 0.125,  # 3 hours
    "continuous": 0.125,
    "hourly": 0.25,  # 6 hours
    "daily": 3,
    "weekly": 30,
    "event-driven": 90,
    "rarely": None,
}
DEFAULT_HALF_LIFE = 30.0
UNKNOWN_DATE_FACTOR = 0.5  # undated material about the present counts half
MAX_WEIGHT = 0.95  # no single source is ever treated as certain

DIRECTNESS_FACTOR = {"explicit": 1.0, "implicit": 0.7}

DECISION_THRESHOLD = 0.7  # |score| needed for confirmed / false


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def recency_factor(
    published_at: datetime | None, update_frequency: str, time_sensitive: bool, now: datetime
) -> float:
    if not time_sensitive:
        return 1.0
    half_life = HALF_LIFE_DAYS.get(update_frequency, DEFAULT_HALF_LIFE)
    if half_life is None:
        return 1.0
    if published_at is None:
        return UNKNOWN_DATE_FACTOR
    age_days = max(0.0, (now - _aware(published_at)).total_seconds() / 86400)
    return 0.5 ** (age_days / half_life)


def evidence_weight(*, credibility: int, recency: float, directness: float, role: str) -> float:
    """The weight of one piece of evidence: every per-source feature in one place."""
    if role == "context_only":
        return 0.0
    return round(min(credibility / 5 * recency * directness, MAX_WEIGHT), 3)


def score_evidence(evidence: list[Evidence], time_sensitive: bool, now: datetime | None = None) -> None:
    """Fill in `recency` and `weight` on each evidence item (in place)."""
    now = now or datetime.now(UTC)
    for e in evidence:
        e.recency = round(recency_factor(e.published_at, e.update_frequency, time_sensitive, now), 3)
        e.weight = evidence_weight(
            credibility=e.credibility, recency=e.recency, directness=e.directness, role=e.role
        )


def strength(weight: float) -> float:
    return -math.log(1 - min(weight, MAX_WEIGHT))


def counted(evidence: list[Evidence]) -> list[Evidence]:
    """The evidence that actually enters the score: one item per publisher, latest position wins."""
    by_publisher: dict[str, list[Evidence]] = {}
    for e in evidence:
        if e.stance in (Stance.supports, Stance.refutes) and e.weight > 0:
            by_publisher.setdefault(e.publisher, []).append(e)
    result = []
    for items in by_publisher.values():
        latest = max(items, key=lambda e: _aware(e.published_at) if e.published_at else datetime.min.replace(tzinfo=UTC))
        same_side = [e for e in items if e.stance == latest.stance]
        result.append(max(same_side, key=lambda e: e.weight))
    return result


def claim_score(evidence: list[Evidence]) -> float:
    """The single evidence score for a claim, from −1 (refuted) to +1 (confirmed)."""
    balance = sum(strength(e.weight) * (1 if e.stance == Stance.supports else -1) for e in counted(evidence))
    return round(math.copysign(1 - math.exp(-abs(balance)), balance), 3) if balance else 0.0


def total_strength(evidence: list[Evidence]) -> float:
    """How much decisive evidence there is regardless of direction (used for 'misleading')."""
    best: dict[str, float] = {}
    for e in evidence:
        if e.weight > 0:
            best[e.publisher] = max(best.get(e.publisher, 0.0), e.weight)
    return round(1 - math.exp(-sum(strength(w) for w in best.values())), 3)
