"""Live web search over an allowlist of catalogue domains (Claude's server-side web_search tool).

Used only to DISCOVER pages when our own sources leave a claim undecided. The search tool's
page content is not usable by our code, so we only take the result URLs; our own fetcher then
reads the pages (SSRF guard) and they go through the normal assessment, verbatim quote check
and scoring. Pages from media are used for that single check and never stored.

The allowlist is built from corpus/sources.csv, so every possible source is auditable. Domains
the search tool cannot reach (it reports them) are dropped automatically.
"""

import logging
import re
import threading
from dataclasses import dataclass

import anthropic

from app.store.corpus import CatalogEntry

log = logging.getLogger(__name__)

# The basic variant: the newer one (web_search_20260209) adds "dynamic filtering" through hidden
# code execution, which we do not need (our code reads the pages) and which failed with
# invalid_tool_input on ~half of the queries in testing.
TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
PRICE_PER_SEARCH_USD = 0.01


class WebSearchError(Exception):
    """Search unavailable (no credit, outage, all domains rejected). Never a verdict."""


@dataclass
class SearchHit:
    url: str
    title: str
    age_days: int | None  # "24 days ago" → 24; None if unknown


def allowlist(catalog: list[CatalogEntry]) -> list[str]:
    """Registrable domains of catalogue sources whose pages may serve as evidence."""
    domains = []
    for e in catalog:
        if e.role != "evidence" or e.domain in ("google.com",):
            continue
        domain = e.domain.lower().removeprefix("www.")
        if domain.endswith("policja.gov.pl"):
            domain = "policja.gov.pl"
        domains.append(domain)
    return sorted(set(domains))


class WebSearch:
    def __init__(self, client: anthropic.Anthropic, model: str, domains: list[str]):
        self.client = client
        self.model = model
        self.domains = list(domains)
        self._lock = threading.Lock()

    def search(self, query: str, limit: int = 6) -> tuple[list[SearchHit], float, int, int]:
        """(hits, cost_usd, input_tokens, output_tokens) for one search."""
        for _ in range(3):  # retry after dropping domains the tool cannot reach
            with self._lock:
                domains = list(self.domains)
            if not domains:
                raise WebSearchError("no searchable domains left")
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    tools=[{**TOOL, "allowed_domains": domains}],
                    messages=[{
                        "role": "user",
                        "content": f"Use web_search exactly once with this query, then reply only 'ok'.\nQuery: {query}",
                    }],
                )
            except anthropic.BadRequestError as e:
                message = str(e.message)
                if "not accessible" in message:
                    blocked = set(re.findall(r"'([a-z0-9.-]+\.[a-z]{2,})'", message.split("not accessible", 1)[1]))
                    with self._lock:
                        self.domains = [d for d in self.domains if d not in blocked]
                    log.warning("web search: dropping unreachable domains %s", sorted(blocked))
                    continue
                raise WebSearchError(f"search rejected: {message[:120]}") from e
            except anthropic.APIError as e:
                raise WebSearchError(f"search unavailable: {type(e).__name__}") from e

            hits = []
            for block in response.content:
                if block.type == "web_search_tool_result":
                    if not isinstance(block.content, list):  # tool error object
                        raise WebSearchError(f"search failed: {getattr(block.content, 'error_code', 'error')}")
                    for item in block.content:
                        age = re.match(r"(\d+)\s+day", getattr(item, "page_age", None) or "")
                        hits.append(SearchHit(url=item.url, title=item.title, age_days=int(age.group(1)) if age else None))
            searches = getattr(getattr(response.usage, "server_tool_use", None), "web_search_requests", 0) or 0
            usage = response.usage
            return hits[:limit], searches * PRICE_PER_SEARCH_USD, usage.input_tokens, usage.output_tokens
        raise WebSearchError("search domains kept being rejected")
