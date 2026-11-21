"""Web-search fallback (no network): only for undecided claims, allowlisted, nothing stored."""

from app.config import Settings
from app.llm.fake import FakeProvider
from app.pipeline import web_evidence
from app.pipeline.assess import AssessmentOutput, PassageJudgement
from app.pipeline.claims import ClaimExtraction, ExtractedClaim
from app.pipeline.run import Services, run_check
from app.schemas import CheckRequest, Verdict
from app.sources.web_search import SearchHit, WebSearchError, allowlist
from app.store.audit import AuditLog
from app.store.corpus import Corpus, load_catalog

PAGE = "Strajk generalny we Włoszech odbył się 20 listopada. Zamknięte były lotniska i dworce w całym kraju."


class StubSearch:
    def __init__(self, hits=None, fail=False):
        self.hits, self.fail, self.calls = hits or [], fail, 0

    def search(self, query):
        self.calls += 1
        if self.fail:
            raise WebSearchError("no credit")
        return self.hits, 0.01, 1000, 50


def claims(user):
    return ClaimExtraction(status="ok", input_kind="question", claims=[ExtractedClaim(
        text="We Włoszech odbył się strajk generalny.", kind="factual", search_queries=["strajk generalny Włochy"],
        english_query="Italy general strike", implied_time_or_place="Włochy", time_sensitive=True,
        verifying_source="komunikat MSZ")])


def assess_supports(user):
    if "<passage" not in user:
        return AssessmentOutput(passages=[], misleading_context=False, misleading_reason="", findings_summary="")
    import re
    pids = [int(x) for x in re.findall(r'<passage id="(-?\d+)"', user)]
    return AssessmentOutput(passages=[PassageJudgement(passage_id=pid, stance="supports", directness="explicit",
                            same_claim=False, quote="Strajk generalny we Włoszech odbył się 20 listopada.") for pid in pids],
                            misleading_context=False, misleading_reason="", findings_summary="Media podają, że strajk się odbył.")


def make(tmp_path, search, monkeypatch):
    monkeypatch.setattr(web_evidence, "fetch_url", lambda url: ("Tytuł", PAGE))
    settings = Settings(llm_provider="fake")
    return Services(settings=settings, llm=FakeProvider({ClaimExtraction: claims, AssessmentOutput: assess_supports}),
                    corpus=Corpus(tmp_path / "c.db"), audit=AuditLog(tmp_path / "a.db"),
                    catalog=load_catalog(settings.sources_catalog_path), web_search=search)


def test_allowlist_comes_from_the_catalogue():
    domains = allowlist(load_catalog(Settings().sources_catalog_path))
    assert {"gov.pl", "pap.pl", "tvp.info", "cert.pl", "policja.gov.pl"} <= set(domains)
    assert "euvsdisinfo.eu" not in domains and "google.com" not in domains  # context-only / aggregator rows excluded


def test_two_independent_media_reports_can_decide(tmp_path, monkeypatch):
    hits = [SearchHit("https://www.tvp.info/1/strajk", "Strajk", 1), SearchHit("https://www.pap.pl/aktualnosci/strajk", "Strajk", 1),
            SearchHit("https://example.com/blog", "Blog", 1)]  # not in the catalogue: ignored
    svc = make(tmp_path, StubSearch(hits), monkeypatch)
    claim = run_check(svc, CheckRequest(text="Czy we Włoszech był strajk?")).claims[0]
    assert {e.publisher for e in claim.evidence} == {"TVP Info", "Polska Agencja Prasowa (PAP)"}
    assert all(e.credibility == 3 for e in claim.evidence)
    assert claim.verdict == Verdict.confirmed  # 0.6 + 0.6 independent → 0.84
    assert svc.corpus.stats()["documents"] == 0  # media pages are never stored


def test_one_media_report_alone_does_not_decide(tmp_path, monkeypatch):
    svc = make(tmp_path, StubSearch([SearchHit("https://www.tvp.info/1/strajk", "Strajk", 1)]), monkeypatch)
    assert run_check(svc, CheckRequest(text="Czy we Włoszech był strajk?")).claims[0].verdict == Verdict.insufficient


def test_search_failure_is_a_note_not_a_verdict(tmp_path, monkeypatch):
    claim = run_check(make(tmp_path, StubSearch(fail=True), monkeypatch), CheckRequest(text="Czy we Włoszech był strajk?")).claims[0]
    assert claim.verdict == Verdict.insufficient and "Wyszukiwanie w zaufanych serwisach" in claim.limitations


def test_results_are_picked_across_publishers(tmp_path, monkeypatch):
    hits = [SearchHit(f"https://www.rp.pl/a{i}", "rp", 1) for i in range(4)] + [SearchHit("https://www.pap.pl/b", "pap", 1)]
    svc = make(tmp_path, StubSearch(hits), monkeypatch)
    from app.llm import LLMUsage
    passages, _ = web_evidence.web_search_passages(svc, claims("").claims[0], LLMUsage(model="x"))
    assert "https://www.pap.pl/b" in {p.url for p in passages}  # not crowded out by four rp.pl results


def test_search_results_alone_cannot_make_a_claim_misleading(tmp_path, monkeypatch):
    def assess_misleading(user):
        out = assess_supports(user)
        if "<passage" in user:
            out.misleading_context, out.misleading_reason = True, "inne daty"
        return out
    hits = [SearchHit("https://www.tvp.info/1/strajk", "Strajk", 1), SearchHit("https://www.pap.pl/a/strajk", "Strajk", 1)]
    svc = make(tmp_path, StubSearch(hits), monkeypatch)
    svc.llm.handlers[AssessmentOutput] = assess_misleading
    assert run_check(svc, CheckRequest(text="Czy we Włoszech był strajk?")).claims[0].verdict == Verdict.confirmed


def test_subdomain_of_catalogue_host_matches():
    from app.store.corpus import CatalogEntry, match_catalog
    import inspect
    fields = inspect.signature(CatalogEntry).parameters
    base = {k: "" for k in fields}
    base.update(id=1, url="https://wiadomosci.wp.pl/", publisher="WP", domain="wp.pl", credibility=3, role="evidence")
    wp = CatalogEntry(**{k: v for k, v in base.items() if k in fields})
    assert match_catalog("https://wiadomosci.wp.pl/finlandia-w-nato-123", [wp]) is wp
    pl = CatalogEntry(**{**{k: v for k, v in base.items() if k in fields}, "url": "https://www.euronews.com/", "publisher": "Euronews", "domain": "euronews.com"})
    assert match_catalog("https://pl.euronews.com/2023/04/04/finlandia", [pl]) is pl
    assert match_catalog("https://evil-euronews.com/x", [pl]) is None
