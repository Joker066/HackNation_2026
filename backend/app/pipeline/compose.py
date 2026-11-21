"""Step 6: build the plain-Polish answer from the verdict and verified evidence only.

The verdict sentence comes from fixed templates, so the model cannot phrase a stronger
conclusion than the rules allow. The model's contribution is a short summary of what the
sources say, which was itself constrained to the passages.
"""

from app.schemas import ClaimResult, Evidence, Strength, Verdict

from .verdict import VerdictResult

VERDICT_SENTENCE = {
    Verdict.confirmed: "Sprawdzone źródła potwierdzają to twierdzenie.",
    Verdict.false: "Sprawdzone źródła przeczą temu twierdzeniu.",
    Verdict.misleading: "To twierdzenie wprowadza w błąd: fakty są wyrwane z kontekstu.",
    Verdict.insufficient: "Nie da się tego teraz rozstrzygnąć — brakuje wystarczających dowodów.",
    Verdict.unverifiable: "Tego nie da się zweryfikować na podstawie źródeł.",
}

STRENGTH_LABEL = {Strength.high: "wysoka", Strength.medium: "średnia", Strength.low: "niska"}


def compose(
    claim_text: str,
    decision: VerdictResult,
    evidence: list[Evidence],
    findings_summary: str,
    source_warnings: list[str],
) -> ClaimResult:
    parts = [VERDICT_SENTENCE[decision.verdict]]
    if findings_summary and evidence:
        parts.append(findings_summary.strip())
    if decision.strength is not None:
        parts.append(f"Siła podstaw: {STRENGTH_LABEL[decision.strength]}.")
    if any(e.archival_warning for e in evidence):
        parts.append("Uwaga: część źródeł to materiały archiwalne — sprawdź ich datę.")
    return ClaimResult(
        text=claim_text,
        verdict=decision.verdict,
        strength=decision.strength,
        score=decision.score,
        reasons=decision.reasons,
        explanation=" ".join(parts),
        evidence=evidence,
        limitations=decision.limitations,
        source_warnings=source_warnings,
    )
