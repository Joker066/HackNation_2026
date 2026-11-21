"""EUvsDisinfo connector: record conversion and pipeline behaviour (no network)."""

from app.config import Settings
from app.llm.fake import FakeProvider
from app.pipeline.assess import AssessmentOutput, PassageJudgement
from app.pipeline.claims import ClaimExtraction, ExtractedClaim
from app.pipeline.run import Services, run_check
from app.schemas import CheckRequest, Verdict
from app.sources.euvsdisinfo import CATALOG_ID, EUvsDisinfoError, to_records
from app.store.audit import AuditLog
from app.store.corpus import Corpus, load_catalog

SEARCH_RESULTS = [
    {
        "type": "claim_review",
        "title": "Poland plans to annex western Ukraine",
        "content": "<p>Disinformation: <strong>Poland</strong> is preparing to annex western Ukraine.</p>",
        "link": "https://euvsdisinfo.eu/report/poland-plans-to-annex-western-ukraine/",
    },
    {"type": "article", "title": "", "content": "no title", "link": "https://euvsdisinfo.eu/x/"},  # skipped
]


def test_to_records_strips_html_and_files_under_context_row():
    records = to_records(SEARCH_RESULTS)
    assert len(records) == 1
    r = records[0]
    assert r["catalog_id"] == CATALOG_ID and r["publisher"] == "EUvsDisinfo (EEAS)"
    assert "<p>" not in r["text"] and "Poland is preparing to annex western Ukraine" in r["text"]
    assert r["text"].startswith("EUvsDisinfo – przypadek dezinformacji:")


class StubEU:
    def __init__(self, fail=False):
        self.fail, self.queries = fail, []

    def search(self, query, limit=5):
        self.queries.append(query)
        if self.fail:
            raise EUvsDisinfoError("EUvsDisinfo rejected the API key")
        return to_records(SEARCH_RESULTS)


def claims(user):
    return ClaimExtraction(
        status="ok",
        claims=[
            ExtractedClaim(
                text="Polska przygotowuje aneksję zachodniej Ukrainy.",
                kind="factual",
                search_queries=["Polska aneksja Ukrainy", "aneksja zachodniej Ukrainy"],
                english_query="Poland annex western Ukraine",
                implied_time_or_place="",
                time_sensitive=False,
            verifying_source="",
            )
        ],
    )


def assess_context(user):
    pid = int(user.split('<passage id="')[1].split('"')[0])
    return AssessmentOutput(
        passages=[PassageJudgement(passage_id=pid, stance="refutes", directness="explicit", same_claim=True,
                                   quote="Poland is preparing to annex western Ukraine")],
        misleading_context=False,
        misleading_reason="",
        findings_summary="",
    )


def make(tmp_path, eu):
    settings = Settings(llm_provider="fake")
    return Services(
        settings=settings,
        llm=FakeProvider({ClaimExtraction: claims, AssessmentOutput: assess_context}),
        corpus=Corpus(tmp_path / "corpus.db"),
        audit=AuditLog(tmp_path / "audit.db"),
        catalog=load_catalog(settings.sources_catalog_path),
        euvsdisinfo=eu,
    )


def test_match_is_shown_as_context_but_never_decides(tmp_path):
    eu = StubEU()
    claim = run_check(make(tmp_path, eu), CheckRequest(text="Polska chce zająć zachodnią Ukrainę")).claims[0]
    assert eu.queries[0] == "Poland annex western Ukraine"  # English query first
    assert claim.evidence and claim.evidence[0].role == "context_only" and claim.evidence[0].weight == 0
    assert claim.verdict == Verdict.insufficient and claim.score == 0.0  # weight 0: no verdict from it
    assert any("EUvsDisinfo" in w for w in claim.source_warnings)


def test_outage_is_a_limitation_not_a_verdict(tmp_path):
    claim = run_check(make(tmp_path, StubEU(fail=True)), CheckRequest(text="Polska chce zająć zachodnią Ukrainę")).claims[0]
    assert claim.verdict == Verdict.insufficient
    assert "EUvsDisinfo" in claim.limitations and not claim.source_warnings
