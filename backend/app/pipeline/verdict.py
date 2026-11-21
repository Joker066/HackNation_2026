"""Step 5: deterministic verdict from the claim's single evidence score (see scoring.py).

    score ≥ +0.7  → potwierdzone
    score ≤ −0.7  → fałszywe
    otherwise     → brak wystarczających dowodów (with the reason: nothing found / too weak / conflict)

The model never picks the verdict. The rules never look at the domain, author, channel or
popularity of the content being checked; only verified evidence from the audited corpus counts.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.schemas import Evidence, Stance, Strength, Verdict

from .scoring import DECISION_THRESHOLD, claim_score, counted, score_evidence, total_strength


@dataclass
class VerdictResult:
    verdict: Verdict
    strength: Strength | None
    reasons: list[str] = field(default_factory=list)
    limitations: str = ""
    score: float | None = None  # −1…+1; None for opinions / predictions


def is_archival(published_at: datetime | None, archival_after_days: int, now: datetime | None = None) -> bool:
    if published_at is None:
        return False
    now = now or datetime.now(UTC)
    aware = published_at if published_at.tzinfo else published_at.replace(tzinfo=UTC)
    return (now - aware).days > archival_after_days


def _strength(magnitude: float) -> Strength:
    return Strength.high if magnitude >= 0.9 else Strength.medium if magnitude >= 0.8 else Strength.low


def _fmt(x: float, signed: bool = False) -> str:
    return (f"{x:+.2f}" if signed else f"{x:.2f}").replace(".", ",")


def _score_line(score: float) -> str:
    return (
        f"wynik dowodów: {_fmt(score, signed=True)} w skali od −1 (źródła zaprzeczają) "
        f"do +1 (źródła potwierdzają); rozstrzygnięcie od ±{_fmt(DECISION_THRESHOLD)}"
    )


def _evidence_lines(items: list[Evidence], limit: int = 4) -> list[str]:
    lines = []
    for e in sorted(items, key=lambda e: e.weight, reverse=True)[:limit]:
        direction = "potwierdza" if e.stance == Stance.supports else "zaprzecza"
        lines.append(
            f"{e.publisher} ({direction}): wiarygodność {e.credibility}/5 × aktualność {_fmt(e.recency)}"
            f" × bezpośredniość {_fmt(e.directness)} = waga {_fmt(e.weight)}"
        )
    return lines


def decide(
    *,
    kind: str,
    evidence: list[Evidence],
    misleading_context: bool,
    misleading_reason: str = "",
    time_sensitive: bool = False,
    now: datetime | None = None,
) -> VerdictResult:
    if kind == "appearance_identity":
        return VerdictResult(
            Verdict.unverifiable,
            None,
            ["twierdzenie dotyczy tego, kim jest osoba na zdjęciu lub nagraniu"],
            "Nie rozpoznajemy osób na zdjęciach po wyglądzie twarzy (to dane biometryczne). Możemy sprawdzić "
            "tylko to, co jest na obrazie napisane (podpis, nazwisko), oraz informacje o samym zdarzeniu — "
            "np. zapytaj, czy dana osoba była w tym miejscu i czasie.",
        )
    if kind in ("opinion", "prediction"):
        what = "opinią" if kind == "opinion" else "przewidywaniem dotyczącym przyszłości"
        return VerdictResult(
            Verdict.unverifiable,
            None,
            [f"to twierdzenie jest {what}, a nie faktem"],
            "Opinii i prognoz nie da się potwierdzić ani obalić na podstawie źródeł.",
        )

    score_evidence(evidence, time_sensitive, now)
    score = claim_score(evidence)
    used = counted(evidence)

    # Scenario B: real material presented out of its time/place. Evidence for this is often
    # "context" or "refutes", so every decisive source counts towards it, whatever its direction.
    if misleading_context:
        amount = total_strength(evidence)
        if amount >= DECISION_THRESHOLD:
            return VerdictResult(
                Verdict.misleading,
                _strength(amount),
                [
                    "fakty są prawdziwe, ale pochodzą z innego czasu, miejsca lub kontekstu",
                    f"siła dowodów kontekstu: {_fmt(amount)} (próg {_fmt(DECISION_THRESHOLD)})",
                    *_evidence_lines([e for e in evidence if e.weight > 0]),
                ],
                misleading_reason,
                score,
            )

    if not used:
        return VerdictResult(
            Verdict.insufficient,
            None,
            ["w zbiorze źródeł nie znaleziono aktualnego materiału, który potwierdza lub obala to twierdzenie"],
            "Nie udało się znaleźć wiarygodnych publikacji na ten temat w sprawdzanych źródłach. "
            "To nie znaczy, że twierdzenie jest fałszywe — może być zbyt nowe lub spoza zakresu źródeł.",
            score,
        )

    both_sides = {e.stance for e in used} == {Stance.supports, Stance.refutes}
    reasons = [_score_line(score), *_evidence_lines(used)]

    if abs(score) < DECISION_THRESHOLD:
        if both_sides:
            return VerdictResult(
                Verdict.insufficient,
                None,
                ["źródła są sprzeczne i żadne nie ma wyraźnej przewagi", *reasons],
                "Wiarygodne źródła podają różne informacje. Zobacz oba stanowiska poniżej.",
                score,
            )
        return VerdictResult(
            Verdict.insufficient,
            None,
            ["znalezione źródła są zbyt słabe lub nieaktualne, by rozstrzygnąć", *reasons],
            "Potrzebne jest aktualne źródło urzędowe albo kilka niezależnych źródeł.",
            score,
        )

    if both_sides:
        reasons.append("istnieje też źródło przeciwne, ale o wyraźnie mniejszej wadze")
    verdict = Verdict.confirmed if score > 0 else Verdict.false
    return VerdictResult(verdict, _strength(abs(score)), reasons, "", score)
