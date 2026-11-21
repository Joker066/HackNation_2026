"""Image (screenshot) input: validation, reading, limits disclosed, image not stored (no network)."""

import base64

import pytest

from app.config import Settings
from app.llm.fake import FakeProvider
from app.pipeline.claims import ClaimExtraction, ExtractedClaim
from app.pipeline.image import IMAGE_LIMITATIONS, ImageError, ImageReading, decode_image
from app.pipeline.run import Services, run_check
from app.schemas import CheckRequest, Status
from app.store.audit import AuditLog
from app.store.corpus import Corpus

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG_B64 = base64.b64encode(PNG).decode()


def test_decode_accepts_png_and_data_urls():
    assert decode_image(PNG_B64, "image/png").data == PNG
    assert decode_image("data:image/png;base64," + PNG_B64, None).media_type == "image/png"


@pytest.mark.parametrize(
    ("data", "media_type"),
    [(PNG_B64, "application/pdf"), ("not base64!!", "image/png"), (base64.b64encode(b"GIF89a....").decode(), "image/png")],
)
def test_decode_rejects_bad_files(data, media_type):
    with pytest.raises(ImageError):
        decode_image(data, media_type)


def reading(readable=True, text="Od jutra bankomaty PKO nie będą działać przez 3 dni! Zadzwoń 600 700 800"):
    return lambda user: ImageReading(
        readable=readable, image_kind="screenshot_social", text_on_image=text,
        visible_date="21.11.2026", visible_source="@konto_x", description="Zrzut ekranu wpisu.",
    )


def claims(user):
    assert "Treść obrazu (odczytana automatycznie)" in user  # the image text reached claim extraction
    assert "600 700 800" not in user  # ...with personal data masked
    return ClaimExtraction(status="ok", input_kind="message", claims=[ExtractedClaim(
        text="Od jutra bankomaty PKO nie będą działać przez 3 dni.", kind="factual", search_queries=["bankomaty PKO"],
        english_query="", implied_time_or_place="", time_sensitive=True, verifying_source="komunikat banku")])


def make(tmp_path, read):
    return Services(settings=Settings(llm_provider="fake"), llm=FakeProvider({ImageReading: read, ClaimExtraction: claims}),
                    corpus=Corpus(tmp_path / "c.db"), audit=AuditLog(tmp_path / "a.db"))


def test_screenshot_goes_through_the_pipeline_with_limits_disclosed(tmp_path):
    svc = make(tmp_path, reading())
    r = run_check(svc, CheckRequest(image=PNG_B64, image_media_type="image/png", session_id="s"))
    assert r.status == Status.ok and r.input_kind == "message"
    assert "bankomaty PKO" in r.image_text and "[TELEFON]" in r.image_text
    assert IMAGE_LIMITATIONS in r.claims[0].limitations
    logged = svc.audit.recent()[0]
    assert logged["input_masked"].strip() == "[obraz]"  # the image itself is never stored


def test_unreadable_image_asks_for_clarification(tmp_path):
    r = run_check(make(tmp_path, reading(readable=False, text="")), CheckRequest(image=PNG_B64, image_media_type="image/png"))
    assert r.status == Status.needs_clarification and r.claims == []


def test_invalid_upload_is_not_a_verdict(tmp_path):
    r = run_check(make(tmp_path, reading()), CheckRequest(image=PNG_B64, image_media_type="application/pdf"))
    assert r.status == Status.needs_clarification and r.claims == []


def test_who_is_in_the_photo_is_not_checked_and_not_searched(tmp_path):
    def identity_claim(user):
        return ClaimExtraction(status="ok", input_kind="mixed", claims=[ExtractedClaim(
            text="Mężczyzna na zdjęciu to Donald Trump.", kind="appearance_identity", search_queries=["Trump"],
            english_query="Trump", implied_time_or_place="", time_sensitive=False, verifying_source="")])

    class NoSearch:
        def search(self, *a, **k):
            raise AssertionError("identity claims must not trigger a web search")

    svc = make(tmp_path, reading())
    svc.llm.handlers[ClaimExtraction] = identity_claim
    svc.web_search = NoSearch()
    claim = run_check(svc, CheckRequest(text="ten pan na zdjęciu to Trump", image=PNG_B64, image_media_type="image/png")).claims[0]
    assert claim.verdict.value == "nie_podlega_weryfikacji" and "po wyglądzie twarzy" in claim.limitations
