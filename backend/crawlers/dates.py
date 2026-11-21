"""Parse the date formats Polish government sites use."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")

MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
    # nominative forms, used in some headers
    "styczeń": 1, "luty": 2, "marzec": 3, "kwiecień": 4, "maj": 5, "czerwiec": 6,
    "lipiec": 7, "sierpień": 8, "wrzesień": 9, "październik": 10, "listopad": 11, "grudzień": 12,
}

_TIME = r"(?:\D{0,12}?(\d{1,2})[:.](\d{2}))?"
_PATTERNS = [
    # 21 listopada 2026 r. [, godz. 12:30]
    re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})" + _TIME, re.IGNORECASE),
    # 21.11.2026 [12:30]
    re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})" + _TIME),
    # 2026-11-21[T12:30]
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2}))?"),
]


def parse_polish_date(text: str) -> datetime | None:
    """First date found in `text`, as an aware datetime in Europe/Warsaw (midnight if no time)."""
    for i, pattern in enumerate(_PATTERNS):
        m = pattern.search(text)
        if not m:
            continue
        g = m.groups()
        try:
            if i == 0:
                day, month, year = int(g[0]), MONTHS[g[1].lower()], int(g[2])
            elif i == 1:
                day, month, year = int(g[0]), int(g[1]), int(g[2])
            else:
                year, month, day = int(g[0]), int(g[1]), int(g[2])
            hour, minute = (int(g[3]), int(g[4])) if g[3] else (0, 0)
            return datetime(year, month, day, hour, minute, tzinfo=WARSAW)
        except (ValueError, KeyError):
            continue
    return None
