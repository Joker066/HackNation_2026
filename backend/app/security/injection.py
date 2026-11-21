"""Detect instructions aimed at the model inside user input or source documents.

Detection is only one layer. The main defences are structural: content is always passed
to the model as delimited data, the model can only return a fixed JSON schema, it has no
tools, quotes are verified against the source text in code, and verdicts are computed by
rules rather than by the model.
"""

import re

_PATTERNS = [
    # English
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any )?(the )?(previous|prior|above|system) (instructions|rules|prompts?)",
    r"you are now\b",
    r"new (system )?instructions?:",
    r"system prompt",
    r"(answer|respond|reply|mark|classify)\s.{0,40}\b(true|confirmed|verified)\b.{0,20}\bregardless",
    # Polish
    r"zignoruj (wszystkie |wcześniejsze |poprzednie |powyższe )*(instrukcje|polecenia|zasady|reguły)",
    r"pomiń (wszystkie |wcześniejsze |poprzednie |powyższe )*(instrukcje|polecenia|zasady|reguły)",
    r"jesteś teraz\b",
    r"nowe instrukcje( systemowe)?:",
    r"prompt systemowy",
    r"(oznacz|oceń|uznaj).{0,40}\b(jako )?(prawd\w*|potwierdzon\w*)\b.{0,30}\bniezależnie",
]
_REGEX = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


def looks_like_injection(text: str) -> bool:
    return bool(_REGEX.search(text))
