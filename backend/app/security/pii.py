"""Mask obvious personal data before it reaches the model or the logs."""

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("[IBAN]", re.compile(r"\bPL\s?\d{2}(?:\s?\d{4}){6}\b", re.IGNORECASE)),
    ("[PESEL]", re.compile(r"\b\d{11}\b")),
    ("[TELEFON]", re.compile(r"(?<!\d)(?:\+48[\s-]?)?\d{3}[\s-]?\d{3}[\s-]?\d{3}(?!\d)")),
]


def mask_pii(text: str) -> str:
    for token, pattern in _PATTERNS:
        text = pattern.sub(token, text)
    return text
