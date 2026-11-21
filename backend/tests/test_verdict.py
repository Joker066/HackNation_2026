from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.pipeline.scoring import claim_score, recency_factor, score_evidence
from app.pipeline.verdict import decide, is_archival
from app.schemas import Evidence, SourceType, Stance, Strength, Verdict
from app.store.corpus import load_catalog, match_catalog

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def ev(
    stance: Stance,
    publisher: str = "Demagog",
    credibility: int = 3,
    age_hours: float | None = 1,
    freq: str = "daily",
    role: str = "evidence",
    directness: float = 1.0,
) -> Evidence:
    return Evidence(
        stance=stance,
        title="t",
        publisher=publisher,
        url=f"https://example.org/{publisher}",
        published_at=None if age_hours is None else NOW - timedelta(hours=age_hours),
        retrieved_at=None,
        quote="cytat ze źródła",
        source_type=SourceType.official if credibility >= 4 else SourceType.factcheck,
        credibility=credibility,
        role=role,
        update_frequency=freq,
        directness=directness,
    )


def run(evidence, misleading=False, present=True):
    return decide(
        kind="factual", evidence=evidence, misleading_context=misleading, time_sensitive=present, now=NOW
    )


# --- scoring ---------------------------------------------------------------


def test_recency_half_life():
    assert recency_factor(NOW - timedelta(hours=6), "hourly", True, NOW) == pytest.approx(0.5)
    assert recency_factor(NOW - timedelta(days=3), "daily", True, NOW) == pytest.approx(0.5)
    assert recency_factor(NOW - timedelta(days=3000), "rarely", True, NOW) == 1.0


def test_recency_ignored_for_claims_about_the_past():
    assert recency_factor(NOW - timedelta(days=900), "hourly", False, NOW) == 1.0


def test_undated_material_about_present_counts_half():
    assert recency_factor(None, "daily", True, NOW) == 0.5


def scored(*items):
    score_evidence(list(items), True, NOW)
    return claim_score(list(items))


def test_independent_sources_add_up_but_one_publisher_counts_once():
    assert scored(ev(Stance.supports, "A", 3, 0), ev(Stance.supports, "B", 3, 0)) == pytest.approx(0.84)
    assert scored(ev(Stance.supports, "A", 3, 0), ev(Stance.supports, "A", 3, 0)) == pytest.approx(0.6)


def test_implicit_evidence_counts_less():
    assert scored(ev(Stance.refutes, "GDDKiA", 5, 0, directness=0.7)) == pytest.approx(-0.7)
    assert run([ev(Stance.refutes, "Demagog", 4, 0, directness=0.7)]).verdict == Verdict.insufficient


def test_score_sign_and_range():
    assert scored(ev(Stance.refutes, "IMGW", 5, 0)) == pytest.approx(-0.95)
    assert scored() == 0.0


def test_strong_evidence_outweighs_weak_instead_of_being_cancelled():
    s = scored(ev(Stance.supports, "IMGW", 5, 0), ev(Stance.refutes, "Fact-check", 3, 0))
    assert s == pytest.approx(0.875, abs=0.01)


def test_equal_evidence_cancels_out():
    assert scored(ev(Stance.supports, "GIS", 5, 1), ev(Stance.refutes, "RCB", 5, 1)) == pytest.approx(0, abs=0.01)


def test_publisher_latest_statement_supersedes_its_earlier_one():
    issued = ev(Stance.supports, "IMGW-PIB", 5, 6, "hourly")
    lifted = ev(Stance.refutes, "IMGW-PIB", 5, 0.5, "hourly")
    assert scored(issued, lifted) < -0.7


def test_context_only_never_counts():
    e = ev(Stance.refutes, "EUvsDisinfo", 3, 0, role="context_only")
    assert run([e]).verdict == Verdict.insufficient
    assert e.weight == 0


# --- verdicts ----------------------------------------------------------------


def test_no_evidence_abstains():
    assert run([]).verdict == Verdict.insufficient


def test_opinion_is_unverifiable():
    r = decide(kind="opinion", evidence=[ev(Stance.supports, credibility=5)], misleading_context=False)
    assert r.verdict == Verdict.unverifiable and r.strength is None


def test_single_fresh_official_source_decides():
    r = run([ev(Stance.refutes, "IMGW", 5, 0.5)])
    assert r.verdict == Verdict.false and r.strength == Strength.high
    assert r.score == pytest.approx(-0.95)


def test_single_secondary_source_is_not_enough():
    assert run([ev(Stance.refutes, "Demagog", 3)]).verdict == Verdict.insufficient


def test_two_independent_secondary_sources_decide():
    assert run([ev(Stance.supports, "A", 3, 0), ev(Stance.supports, "B", 3, 0)]).verdict == Verdict.confirmed


def test_newer_report_from_another_body_beats_older_one():
    """RCB reported a warning 6 h ago; IMGW says 30 min ago it was lifted: the newer one wins."""
    old_warning = ev(Stance.supports, "RCB", 5, 6, "hourly")
    lifted = ev(Stance.refutes, "IMGW-PIB", 5, 0.5, "hourly")
    r = run([old_warning, lifted])
    assert r.verdict == Verdict.false
    assert r.score < -0.7
    assert any("mniejszej wadze" in reason for reason in r.reasons)


def test_equal_fresh_official_sources_in_conflict_abstain():
    r = run([ev(Stance.supports, "GIS", 5, 1), ev(Stance.refutes, "RCB", 5, 1)])
    assert r.verdict == Verdict.insufficient
    assert "sprzeczne" in r.reasons[0]


def test_higher_credibility_wins_over_aggregator():
    r = run([ev(Stance.supports, "IMGW", 5, 1), ev(Stance.refutes, "Fact-check", 3, 1)])
    assert r.verdict == Verdict.confirmed


def test_stale_realtime_data_cannot_decide_a_present_claim():
    assert run([ev(Stance.refutes, "GDDKiA", 5, 48, "real-time")]).verdict == Verdict.insufficient


def test_misleading_context():
    r = run([ev(Stance.context, "GUS", 5, 1)], misleading=True)
    assert r.verdict == Verdict.misleading


def test_misleading_needs_strong_evidence():
    assert run([ev(Stance.context, "Demagog", 3)], misleading=True).verdict == Verdict.insufficient


def test_reasons_show_the_weights():
    r = run([ev(Stance.refutes, "IMGW", 5, 0)])
    assert any("wiarygodność 5/5" in reason and "waga" in reason for reason in r.reasons)
    assert any("wynik dowodów: -0,95" in reason for reason in r.reasons)


def test_archival():
    assert is_archival(NOW - timedelta(days=800), 365, NOW)
    assert not is_archival(NOW - timedelta(days=10), 365, NOW)
    assert not is_archival(None, 365, NOW)


# --- catalogue matching (real corpus/sources.csv) -----------------------------


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(Settings().sources_catalog_path)


@pytest.mark.parametrize(
    ("url", "expected_id"),
    [
        ("https://www.gov.pl/web/gis/ostrzezenie-publiczne-dotyczace-zywnosci", 9),  # gov.pl section
        ("https://www.gov.pl/web/rcb/raport-dobowy3", 4),  # exact page
        ("https://policja.pl/pol/aktualnosci/123,tytul.html", 6),  # below listed page
        ("https://mazowiecka.policja.gov.pl/ra/aktualnosci/999,x.html", 7),  # same dedicated host
        ("https://ulc.gov.pl/prawa-pasazera/poradnik-dla-pasazerow/opoznienie", 25),  # most specific
        ("https://hydro.imgw.pl/#/station/hydro/150190340", 34),
    ],
)
def test_catalog_matching(catalog, url, expected_id):
    assert match_catalog(url, catalog).id == expected_id


@pytest.mark.parametrize("url", ["https://www.gov.pl/web/zdrowie/cos", "https://example.com/news"])
def test_unlisted_sources_are_rejected(catalog, url):
    assert match_catalog(url, catalog) is None


@pytest.mark.parametrize(
    ("host", "site"),
    [
        ("podlaska.policja.gov.pl", "policja.gov.pl"),
        ("www.gov.pl", "gov.pl"),
        ("policja.pl", "policja.pl"),
        ("sprawdzam.afp.com", "afp.com"),
        ("ulc.gov.pl", "ulc.gov.pl"),
        ("hydro.imgw.pl", "imgw.pl"),
    ],
)
def test_site_domain(host, site):
    from app.store.corpus import site_domain

    assert site_domain(host) == site
