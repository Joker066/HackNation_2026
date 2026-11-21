"""Offline provider for development and tests.

It never claims anything: it splits input into sentences and marks every passage as
irrelevant, so the pipeline always abstains. Tests can inject custom handlers.
"""

import re
from collections.abc import Callable

from pydantic import BaseModel

from .base import ImageInput, LLMUsage, T

Handler = Callable[[str], BaseModel]


class FakeProvider:
    name = "fake"

    def __init__(self, handlers: dict[type, Handler] | None = None):
        self.handlers = handlers or {}

    def generate(
        self, *, system: str, user: str, schema: type[T], images: list[ImageInput] | None = None
    ) -> tuple[T, LLMUsage]:
        if schema in self.handlers:
            result = self.handlers[schema](user)
        else:
            result = _default(schema, user)
        return result, LLMUsage(model="fake")


def _default(schema: type[BaseModel], user: str) -> BaseModel:
    # Imported here to avoid a circular import (pipeline modules import llm).
    from app.pipeline.assess import AssessmentOutput
    from app.pipeline.claims import ClaimExtraction, ExtractedClaim

    if schema is ClaimExtraction:
        body = user.split("<input>")[-1].split("</input>")[0]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 10]
        return ClaimExtraction(
            status="ok" if sentences else "needs_clarification",
            input_kind="statement",
            claims=[
                ExtractedClaim(text=s, kind="factual", search_queries=[s], english_query="", implied_time_or_place="", time_sensitive=False, verifying_source="")
                for s in sentences[:5]
            ],
        )
    if schema is AssessmentOutput:
        return AssessmentOutput(passages=[], misleading_context=False, misleading_reason="", findings_summary="")
    raise NotImplementedError(f"FakeProvider has no default for {schema.__name__}")
