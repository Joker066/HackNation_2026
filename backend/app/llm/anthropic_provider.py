"""Claude (Anthropic API) implementation of the LLM interface."""

import logging

import base64

import anthropic
import httpx2

from app.config import Settings

from .base import ImageInput, LLMError, LLMUsage, T

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept server-side refusal fallbacks. Claude Haiku 5.5 does not, so for it a
# refusal is reported as an LLMError ("refused"), which the pipeline shows as a technical error.
FALLBACK_MODELS = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings):
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        self.price_in = settings.llm_price_input_per_mtok
        self.price_out = settings.llm_price_output_per_mtok
        # api_key=None lets the SDK resolve credentials from the environment.
        http_client = None
        if settings.force_ipv4:  # see app/net.py
            http_client = anthropic.DefaultHttpxClient(transport=httpx2.HTTPTransport(local_address="0.0.0.0"))
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=45.0, max_retries=1, http_client=http_client
        )

    def generate(
        self, *, system: str, user: str, schema: type[T], images: list[ImageInput] | None = None
    ) -> tuple[T, LLMUsage]:
        content: str | list = user
        if images:  # images first, then the text (recommended order)
            content = [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": img.media_type, "data": base64.b64encode(img.data).decode()},
                }
                for img in images
            ] + [{"type": "text", "text": user}]
        try:
            extra = {}
            if self.model.startswith(FALLBACK_MODELS):
                # If a safety classifier declines, the API retries on a fallback model in the same call.
                extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=schema,
                output_config={"effort": self.effort},
                **extra,
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("auth", "Invalid or missing Anthropic API key") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError("auth", "API key lacks permission for this model") from e
        except anthropic.RateLimitError as e:
            raise LLMError("rate_limited", "Anthropic API rate limit reached") from e
        except anthropic.BadRequestError as e:
            raise LLMError("bad_output", f"Request rejected by the API: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError("unavailable", f"Anthropic API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("unavailable", "Cannot reach the Anthropic API") from e
        except anthropic.AnthropicError as e:
            raise LLMError("misconfigured", str(e)) from e
        except TypeError as e:  # the SDK raises this when no credentials are configured at all
            if "authentication" in str(e):
                raise LLMError("misconfigured", "No Anthropic credentials configured") from e
            raise

        log.debug("anthropic request_id=%s stop=%s", response._request_id, response.stop_reason)

        if response.stop_reason == "refusal":
            raise LLMError("refused", "The model declined to process this content")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError("bad_output", "The model did not return a complete structured answer")

        usage = LLMUsage(
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        usage.cost_usd = (usage.input_tokens * self.price_in + usage.output_tokens * self.price_out) / 1_000_000
        return response.parsed_output, usage
