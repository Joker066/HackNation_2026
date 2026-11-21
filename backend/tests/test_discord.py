"""Discord reply formatting (no network, no Discord connection)."""

from channels.discord_bot import DISCORD_LIMIT, format_response, session_id_for


def claim(i: int) -> dict:
    return {
        "text": f"Twierdzenie numer {i} " + "bardzo długie " * 20,
        "verdict": "fałszywe",
        "score": -0.8,
        "explanation": "Sprawdzone źródła przeczą temu twierdzeniu. " * 6,
        "evidence": [
            {"publisher": "Demagog", "published_at": "2024-05-01T00:00:00Z", "url": f"https://demagog.org.pl/x{i}{j}/"}
            for j in range(3)
        ],
        "limitations": "",
    }


def test_long_answer_is_cut_to_discord_limit_and_keeps_the_link():
    data = {"status": "ok", "claims": [claim(i) for i in range(5)], "security_events": [],
            "result_url": "http://localhost:8000/r/abc123"}
    text = format_response(data)
    assert len(text) <= DISCORD_LIMIT
    assert text.rstrip().endswith("http://localhost:8000/r/abc123")  # full result still reachable


def test_short_answer_has_verdict_score_and_sources():
    data = {"status": "ok", "claims": [claim(1)], "security_events": [], "result_url": "http://x/r/1"}
    text = format_response(data)
    assert "FAŁSZ" in text and "−0,80" not in text  # score uses the ASCII sign from the format
    assert "-0,80" in text and "<https://demagog.org.pl/x10/>" in text  # links not unfurled


def test_errors_are_not_verdicts():
    text = format_response({"status": "error", "status_detail": "Model językowy jest chwilowo niedostępny. To nie jest wynik sprawdzenia."})
    assert text.startswith("ℹ️") and "FAŁSZ" not in text and "POTWIERDZONE" not in text


def test_session_id_is_pseudonymous_and_stable():
    a, b = session_id_for(123456789), session_id_for(123456789)
    assert a == b and a.startswith("dc-") and "123456789" not in a


def test_misleading_verdict_has_no_score():
    c = claim(1) | {"verdict": "wprowadzające_w_błąd", "score": 0.0}
    text = format_response({"status": "ok", "claims": [c], "security_events": [], "result_url": None})
    assert "WPROWADZA W BŁĄD" in text and "wynik dowodów" not in text


def test_first_image_picks_supported_attachment():
    from types import SimpleNamespace

    from channels.discord_bot import first_image

    pdf = SimpleNamespace(content_type="application/pdf", size=1000)
    huge = SimpleNamespace(content_type="image/png", size=9_000_000)
    ok = SimpleNamespace(content_type="image/jpeg; charset=binary", size=200_000)
    assert first_image([pdf, huge, ok]) is ok
    assert first_image([pdf]) is None


def test_zero_score_is_not_shown():
    c = claim(1) | {"verdict": "brak_wystarczających_dowodów", "score": 0.0}
    text = format_response({"status": "ok", "claims": [c], "security_events": [], "result_url": None})
    assert "wynik dowodów" not in text
