"""Polite HTTP fetching for crawlers: identifies itself, respects robots.txt, waits between requests."""

import logging
import re
import time
from urllib.parse import urlparse

import httpx

from app.net import http_client

log = logging.getLogger(__name__)

USER_AGENT = "TapCheck/0.1 (HackNation 2026 Prawdowid prototype; fact-checking research crawler)"
MAX_BYTES = 3_000_000


class FetchError(Exception):
    pass


class RobotsRules:
    """robots.txt rules as RFC 9309 defines them (and Google applies them).

    Python's urllib.robotparser differs in ways that matter on real sites: it applies the
    FIRST matching rule instead of the most specific one, and a blank line ends its rule
    group. moje.cert.pl uses "Disallow: /" followed by "Allow: /komunikaty/", which
    robotparser reads as "everything blocked".

    Here: rules from the group for our user agent (else "*"); the longest matching path
    wins; on a tie, Allow wins; "*" matches any characters and "$" anchors the end.
    """

    def __init__(self, text: str, agent: str = "tapcheck"):
        groups: dict[str, list[tuple[bool, str]]] = {}
        current: list[str] = []
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue  # blank lines and junk do not end a group (RFC 9309)
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:  # a user-agent line after rules starts a new group
                    current, in_rules = [], False
                current.append(value.lower())
                groups.setdefault(value.lower(), [])
            elif key in ("allow", "disallow") and current:
                in_rules = True
                if value or key == "allow":
                    for ua in current:
                        groups[ua].append((key == "allow", value))
        agent = agent.lower()
        specific = next((ua for ua in groups if ua != "*" and ua in agent), None)
        self.rules = groups.get(specific or "*", [])

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        regex = re.escape(pattern).replace(r"\*", ".*")
        if regex.endswith(r"\$"):
            regex = regex[:-2] + "$"
        return re.match(regex, path) is not None

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
        best_len, allowed = -1, True
        for allow, pattern in self.rules:
            if self._matches(pattern, path):
                length = len(pattern)
                if length > best_len or (length == best_len and allow):
                    best_len, allowed = length, allow
        return allowed


class Fetcher:
    def __init__(self, delay_seconds: float = 1.0, timeout: float = 15.0):
        self.delay = delay_seconds
        self.client = http_client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept-Language": "pl"}
        )
        self._robots: dict[str, RobotsRules | None] = {}
        self._last_request: dict[str, float] = {}

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            rules: RobotsRules | None = None  # no robots.txt: everything allowed
            try:
                resp = self.client.get(f"{origin}/robots.txt")
                if resp.status_code == 200:
                    rules = RobotsRules(resp.text, agent="tapcheck")
            except httpx.HTTPError:
                pass
            self._robots[origin] = rules
        rules = self._robots[origin]
        return rules is None or rules.can_fetch(url)

    def _wait_turn(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request[host] = time.monotonic()

    def get_html(self, url: str) -> str:
        if not self._allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        resp = None
        for attempt in (1, 2):  # one retry: some servers drop idle keep-alive connections
            self._wait_turn(urlparse(url).netloc)
            try:
                resp = self.client.get(url)
                break
            except httpx.TransportError as e:
                if attempt == 2:
                    raise FetchError(f"{url}: {e}") from e
                log.info("retrying %s after: %s", url, e)
            except httpx.HTTPError as e:
                raise FetchError(f"{url}: {e}") from e
        if resp.status_code != 200:
            raise FetchError(f"{url}: HTTP {resp.status_code}")
        if len(resp.content) > MAX_BYTES:
            raise FetchError(f"{url}: page too large")
        return resp.text

    def close(self) -> None:
        self.client.close()
