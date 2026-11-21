"""Provider-neutral LLM interface. The pipeline only ever talks to this."""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """A technical failure. Callers must report it as status=error, never as a verdict."""

    def __init__(self, kind: str, message: str):
        # kind: misconfigured | auth | rate_limited | unavailable | refused | bad_output
        super().__init__(message)
        self.kind = kind


@dataclass
class LLMUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: "LLMUsage") -> None:
        if other.input_tokens or other.output_tokens:
            self.model = other.model  # record the model that actually answered
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd += other.cost_usd


@dataclass
class ImageInput:
    """An image passed to the model (screenshot or photo sent by the user)."""

    data: bytes
    media_type: str  # image/png | image/jpeg | image/webp | image/gif


class LLMProvider(Protocol):
    name: str

    def generate(
        self, *, system: str, user: str, schema: type[T], images: list[ImageInput] | None = None
    ) -> tuple[T, LLMUsage]:
        """Return an instance of `schema` filled in by the model, plus token usage."""
        ...
