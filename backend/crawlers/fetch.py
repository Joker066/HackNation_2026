"""Polite HTTP fetching for crawlers: identifies itself, respects robots.txt, waits between requests."""

import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.net import http_client

log = logging.getLogger(__name__)

USER_AGENT = "TapCheck/0.1 (HackNation 2026 Prawdowid prototype; fact-checking research crawler)"
MAX_BYTES = 3_000_000


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, delay_seconds: float = 1.0, timeout: float = 15.0):
        self.delay = delay_seconds
        self.client = http_client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept-Language": "pl"}
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp = self.client.get(f"{origin}/robots.txt")
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    parser = None  # no robots.txt: everything allowed
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def _wait_turn(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request[host] = time.monotonic()

    def get_html(self, url: str) -> str:
        if not self._allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        self._wait_turn(urlparse(url).netloc)
        try:
            resp = self.client.get(url)
        except httpx.HTTPError as e:
            raise FetchError(f"{url}: {e}") from e
        if resp.status_code != 200:
            raise FetchError(f"{url}: HTTP {resp.status_code}")
        if len(resp.content) > MAX_BYTES:
            raise FetchError(f"{url}: page too large")
        return resp.text

    def close(self) -> None:
        self.client.close()
