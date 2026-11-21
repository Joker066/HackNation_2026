"""EUvsDisinfo MCP connector (EEAS East StratCom): known pro-Kremlin disinformation cases.

Server: https://mcp.euvsd.info/mcp, MCP Streamable HTTP, JSON-RPC 2.0. We use the server's
stateless mode (one tools/call per request with a client-generated mcp-session-id) and its
`search` tool (full-text search over cases and articles).

Results become ordinary corpus records filed under catalogue row 42 (role context_only):
they are shown to the user as context and as a neutral source warning, and they NEVER decide
a verdict. A match only means a similar narrative appeared in an information operation.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from app.net import http_client

log = logging.getLogger(__name__)

DEFAULT_URL = "https://mcp.euvsd.info/mcp"
CATALOG_ID = 42  # corpus/sources.csv: EUvsDisinfo, role context_only
MAX_TEXT = 2500  # article bodies can be long; keep enough for matching and quoting


class EUvsDisinfoError(Exception):
    """The server could not be queried (bad key, outage, timeout). Never a verdict."""


def _html_to_text(html: str) -> str:
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


class EUvsDisinfo:
    def __init__(self, api_key: str, url: str = DEFAULT_URL, timeout: float = 10.0):
        self.url = url
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {api_key}",
        }
        self.client = http_client(timeout=timeout)

    def _call(self, tool: str, arguments: dict) -> dict:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        headers = {**self.headers, "mcp-session-id": str(uuid.uuid4())}  # stateless mode
        try:
            resp = self.client.post(self.url, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise EUvsDisinfoError("EUvsDisinfo server unreachable") from e
        if resp.status_code == 401:
            raise EUvsDisinfoError("EUvsDisinfo rejected the API key")
        if resp.status_code != 200:
            raise EUvsDisinfoError(f"EUvsDisinfo error {resp.status_code}")
        if "text/event-stream" in resp.headers.get("content-type", ""):
            data = [line[5:].strip() for line in resp.text.splitlines() if line.startswith("data:")]
            message = json.loads(data[-1]) if data else {}
        else:
            message = resp.json()
        if "error" in message:
            raise EUvsDisinfoError(f"EUvsDisinfo tool error: {message['error'].get('message', '')[:120]}")
        return message.get("result", {})

    def search(self, query: str, limit: int = 5) -> list[dict]:
        result = self._call("search", {"query": query})
        items = result.get("structuredContent")
        if isinstance(items, dict):
            items = items.get("results")
        if items is None:  # some versions only return the JSON as text content
            text = " ".join(block.get("text", "") for block in result.get("content", []))
            try:
                items = json.loads(text)
            except ValueError:
                items = []
        return to_records(items[:limit] if isinstance(items, list) else [])


def to_records(items: list[dict]) -> list[dict]:
    retrieved = datetime.now(UTC).isoformat()
    records = []
    for item in items:
        url, title = item.get("link"), (item.get("title") or "").strip()
        if not url or not title:
            continue
        kind = "przypadek dezinformacji" if item.get("type") == "claim_review" else "analiza"
        body = _html_to_text(item.get("content", ""))[:MAX_TEXT]
        records.append(
            {
                "url": url,
                "title": title,
                "publisher": "EUvsDisinfo (EEAS)",
                "published_at": None,  # the search tool does not return dates
                "retrieved_at": retrieved,
                "text": f"EUvsDisinfo – {kind}: {title}. {body}",
                "lang": "en",
                "license": "EUvsDisinfo database (EEAS East StratCom Task Force), via MCP API",
                "catalog_id": CATALOG_ID,
                "euvsdisinfo_type": item.get("type"),
            }
        )
    return records
