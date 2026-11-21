"""Input intake: any text, links anywhere in it, safe fetching (no network: fetch_url is stubbed)."""

import pytest

from app.config import Settings
from app.pipeline import ingest as ingest_mod
from app.pipeline.ingest import IngestError, find_links, ingest
from app.schemas import CheckRequest, Status

SETTINGS = Settings(llm_provider="fake")


@pytest.fixture
def pages(monkeypatch):
    """Stub fetch_url: known URLs return a page, others fail like an unreachable site."""
    site = {
        "https://example.org/artykul": ("Tytuł", "Treść artykułu o zamknięciu lotniska."),
        "https://example.org/drugi": ("Drugi", "Druga strona."),
    }

    def fake_fetch(url):
        if url in site:
            return site[url]
        raise IngestError(Status.error, "Nie udało się pobrać strony (przekroczony czas lub błąd sieci).")

    monkeypatch.setattr(ingest_mod, "fetch_url", fake_fetch)
    return site


def test_find_links_strips_trailing_punctuation():
    text = "Zobacz https://example.org/artykul, a potem (https://example.org/drugi). Koniec."
    assert find_links(text) == ["https://example.org/artykul", "https://example.org/drugi"]


def test_plain_question_needs_no_fetching(pages):
    result = ingest(CheckRequest(text="Czy lotnisko jest zamknięte?"), SETTINGS)
    assert result.text == "Czy lotnisko jest zamknięte?" and result.fetched_links == 0


def test_link_only_message_is_replaced_by_the_page(pages):
    result = ingest(CheckRequest(text="https://example.org/artykul"), SETTINGS)
    assert result.text.startswith("Treść strony https://example.org/artykul:")
    assert "zamknięciu lotniska" in result.text and result.fetched_links == 1


def test_question_with_link_keeps_both(pages):
    result = ingest(CheckRequest(text="Czy to prawda? Sprawdź też tę stronę: https://example.org/artykul"), SETTINGS)
    assert result.text.startswith("Czy to prawda?") and "Treść strony https://example.org/artykul" in result.text


def test_failed_link_in_a_message_is_a_note_not_an_error(pages):
    result = ingest(CheckRequest(text="Czy to prawda? https://example.org/nie-ma"), SETTINGS)
    assert result.text.startswith("Czy to prawda?")
    assert any("Nie udało się pobrać strony" in n for n in result.notes)


def test_failed_link_only_message_is_an_error(pages):
    with pytest.raises(IngestError) as e:
        ingest(CheckRequest(text="https://example.org/nie-ma"), SETTINGS)
    assert e.value.status == Status.error


def test_at_most_two_links_are_fetched(pages):
    text = "a https://example.org/artykul b https://example.org/drugi c https://example.org/trzeci"
    result = ingest(CheckRequest(text=text), SETTINGS)
    assert result.fetched_links == 2 and any("tylko pierwsze 2" in n for n in result.notes)


def test_explicit_url_field_still_works(pages):
    result = ingest(CheckRequest(url="https://example.org/artykul"), SETTINGS)
    assert "zamknięciu lotniska" in result.text


def test_javascript_page_falls_back_to_json_ld_article_body():
    from app.pipeline.ingest import html_to_text
    html = """<html><head><title>Strajk</title>
      <script type="application/ld+json">{"@type": "NewsArticle", "articleBody": "<p>Włochy: strajk generalny sparaliżował lotniska i koleje w całym kraju.</p>"}</script>
      </head><body><div id="app"></div></body></html>"""
    title, text = html_to_text(html)
    assert title == "Strajk" and "sparaliżował lotniska" in text and "<p>" not in text


def test_normal_page_keeps_visible_text():
    from app.pipeline.ingest import html_to_text
    body = "Widoczny tekst artykułu. " * 30
    html = f"""<html><head><meta name="description" content="Opis"></head><body><article>{body}</article></body></html>"""
    assert html_to_text(html)[1].startswith("Widoczny tekst")
