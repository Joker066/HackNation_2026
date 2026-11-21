"""Google Fact Check connector: record conversion and pipeline integration (no network)."""

from app.config import Settings
from app.llm.fake import FakeProvider
from app.pipeline.assess import AssessmentOutput, PassageJudgement
from app.pipeline.claims import ClaimExtraction, ExtractedClaim
from app.pipeline.run import Services, run_check
from app.schemas import CheckRequest, SourceType, Verdict
from app.sources.google_factcheck import CATALOG_ID, FactCheckError, load_factcheckers, to_records
from app.store.audit import AuditLog
from app.store.corpus import Corpus, load_catalog

API_CLAIMS = [
    {
        "text": "Putin w 1996 roku zgodził się na wejście Polski do NATO.",
        "claimant": "Polityk X",
        "claimDate": "2022-05-20T00:00:00Z",
        "claimReview": [
            {
                "publisher": {"name": "Demagog", "site": "demagog.org.pl"},
                "url": "https://demagog.org.pl/wypowiedzi/putin-1996-nato/",
                "title": "Czy Putin zgodził się w 1996 roku na wejście Polski do NATO?",
                "reviewDate": "2022-05-23T00:00:00Z",
                "textualRating": "Fałsz",
                "languageCode": "pl",
            },
            {"publisher": {"name": "No URL"}, "textualRating": "Fałsz"},  # incomplete: skipped
        ],
    }
]


def test_to_records():
    records = to_records(API_CLAIMS)
    assert len(records) == 1
    r = records[0]
    assert r["catalog_id"] == CATALOG_ID and r["publisher"] == "Demagog"
    assert "Ocena Demagog: Fałsz" in r["text"]
    assert r["published_at"].startswith("2022-05-23")


class StubFactCheck:
    def __init__(self, fail: bool = False, credibility: dict | None = None):
        self.fail = fail
        self.credibility = credibility or {}
        self.queries: list[str] = []

    def search(self, query, page_size=5, language=None):
        self.queries.append(query)
        if self.fail:
            raise FactCheckError("quota")
        return to_records(API_CLAIMS, self.credibility)


def claims(user):
    return ClaimExtraction(
        status="ok",
        claims=[
            ExtractedClaim(
                text="Putin w 1996 roku zgodził się na wejście Polski do NATO.",
                kind="factual",
                search_queries=["Putin 1996 NATO", "Polska NATO Putin"],
                english_query="",
                implied_time_or_place="1996, Polska",
                time_sensitive=False,
            verifying_source="",
            )
        ],
    )


def assess_refutes(user):
    pid = int(user.split('<passage id="')[1].split('"')[0])
    return AssessmentOutput(
        passages=[PassageJudgement(passage_id=pid, stance="refutes", directness="explicit", same_claim=True, quote="Ocena Demagog: Fałsz")],
        misleading_context=False,
        misleading_reason="",
        findings_summary="Demagog ocenił tę wypowiedź jako fałszywą.",
    )


def make(tmp_path, factcheck):
    settings = Settings(llm_provider="fake")
    return Services(
        settings=settings,
        llm=FakeProvider({ClaimExtraction: claims, AssessmentOutput: assess_refutes}),
        corpus=Corpus(tmp_path / "corpus.db"),
        audit=AuditLog(tmp_path / "audit.db"),
        catalog=load_catalog(settings.sources_catalog_path),
        factcheck=factcheck,
    )


def test_fact_check_is_fetched_cached_and_used(tmp_path):
    stub = StubFactCheck()
    svc = make(tmp_path, stub)
    r = run_check(svc, CheckRequest(text="Putin w 1996 zgodził się na wejście Polski do NATO"))
    claim = r.claims[0]
    assert stub.queries == ["Putin 1996 NATO", "Polska NATO Putin"]
    assert svc.corpus.stats()["documents"] == 1  # cached once despite two queries
    ev = claim.evidence[0]
    assert ev.source_type == SourceType.factcheck and ev.credibility == 3
    # A single fact-check (credibility 3) is not enough on its own: the system abstains.
    assert claim.verdict == Verdict.insufficient
    assert claim.score == -0.6


def test_listed_fact_checker_gets_its_own_credibility_and_decides(tmp_path):
    known = load_factcheckers(Settings().factcheckers_path)
    assert known["demagog.org.pl"].credibility == 4
    svc = make(tmp_path, StubFactCheck(credibility=known))
    claim = run_check(svc, CheckRequest(text="Putin w 1996 zgodził się na wejście Polski do NATO")).claims[0]
    assert claim.evidence[0].credibility == 4
    assert claim.verdict == Verdict.false and claim.score == -0.8


def test_same_organisation_counts_as_one_publisher():
    known = load_factcheckers(Settings().factcheckers_path)
    renamed = [dict(API_CLAIMS[0], claimReview=[dict(API_CLAIMS[0]["claimReview"][0], publisher={
        "name": "Wypowiedzi - weryfikujemy słowa polityków i osób publicznych", "site": "demagog.org.pl"})])]
    assert to_records(renamed, known)[0]["publisher"] == "Demagog"


def test_fact_check_outage_is_a_limitation_not_a_verdict(tmp_path):
    svc = make(tmp_path, StubFactCheck(fail=True))
    r = run_check(svc, CheckRequest(text="Putin w 1996 zgodził się na wejście Polski do NATO"))
    claim = r.claims[0]
    assert claim.verdict == Verdict.insufficient
    assert "Google Fact Check" in claim.limitations


# --- rating translated by code, not by the model -------------------------------------

import pytest  # noqa: E402

from app.pipeline.assess import fact_check_rating, stance_from_rating  # noqa: E402


@pytest.mark.parametrize(
    ("rating", "expected"),
    [("Fałsz", ("refutes", False)), ("Raczej fałsz", ("refutes", False)), ("Prawda", ("supports", False)),
     ("Manipulacja", ("context", True)), ("brakujący kontekst", ("context", True)), ("Nieweryfikowalne", None)],
)
def test_stance_from_rating(rating, expected):
    text = f"Sprawdzane twierdzenie: „x”. Autor twierdzenia: y (2024-01-01). Ocena Demagog: {rating}. Tytuł weryfikacji: z"
    assert stance_from_rating(fact_check_rating(text)) == expected


def test_rating_only_read_from_fact_check_records():
    assert fact_check_rating("Komunikat policji. Ocena Demagog: Fałsz. coś") is None


def judged(same_claim: bool, stance: str):
    def handler(user):
        pid = int(user.split('<passage id="')[1].split('"')[0])
        return AssessmentOutput(
            passages=[PassageJudgement(passage_id=pid, stance=stance, directness="explicit", same_claim=same_claim,
                                       quote="Ocena Demagog: Fałsz")],
            misleading_context=False, misleading_reason="", findings_summary="",
        )
    return handler


def make_with(tmp_path, handler):
    settings = Settings(llm_provider="fake")
    return Services(settings=settings, llm=FakeProvider({ClaimExtraction: claims, AssessmentOutput: handler}),
                    corpus=Corpus(tmp_path / "corpus.db"), audit=AuditLog(tmp_path / "audit.db"),
                    catalog=load_catalog(settings.sources_catalog_path), factcheck=StubFactCheck(credibility=load_factcheckers(settings.factcheckers_path)))


def test_same_claim_rating_overrides_a_wrong_model_stance(tmp_path):
    # the model said "context" although the record rates this very claim "Fałsz"
    claim = run_check(make_with(tmp_path, judged(True, "context")), CheckRequest(text="Putin 1996 NATO")).claims[0]
    assert claim.evidence[0].stance.value == "refutes" and claim.verdict == Verdict.false


def test_different_claim_with_false_rating_is_only_context(tmp_path):
    claim = run_check(make_with(tmp_path, judged(False, "refutes")), CheckRequest(text="Putin 1996 NATO")).claims[0]
    assert claim.evidence[0].stance.value == "context" and claim.verdict == Verdict.insufficient
