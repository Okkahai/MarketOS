"""Rule-based news category. Cheap, deterministic and explainable; the AI is not involved."""

import re

# Order matters: the first matching category wins.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("central_bank", re.compile(
        r"\b(federal reserve|fomc|fed chair|the fed|ecb|bank of england|bank of japan|boj|"
        r"rate decision|interest rates?|rate (cut|hike)|monetary policy|"
        r"quantitative (easing|tightening))\b",
        re.I)),
    ("earnings", re.compile(
        r"\b(earnings|quarterly results|first[- ]quarter|second[- ]quarter|third[- ]quarter|"
        r"fourth[- ]quarter|q[1-4] (results|revenue|profit)|eps|beats? estimates|misses? estimates|"
        r"guidance)\b", re.I)),
    ("macro", re.compile(
        r"\b(cpi|inflation|unemployment|jobless|jobs report|nonfarm|payrolls|gdp|retail sales|"
        r"pmi|consumer confidence|recession)\b", re.I)),
    ("crypto", re.compile(
        r"\b(bitcoin|ethereum|crypto(currency|currencies)?|btc|ether|stablecoin|blockchain)\b",
        re.I)),
    ("commodities", re.compile(
        r"\b(oil|crude|brent|opec|gold|silver|natural gas|copper|commodit(y|ies))\b", re.I)),
    ("geopolitics", re.compile(
        r"\b(war|sanctions?|tariffs?|invasion|ceasefire|missile|embargo|trade (war|deal)|"
        r"geopolitical)\b", re.I)),
]  # fmt: skip


def classify(text: str, *, has_company: bool) -> str:
    for category, pattern in _RULES:
        if pattern.search(text):
            return category
    return "company" if has_company else "other"
