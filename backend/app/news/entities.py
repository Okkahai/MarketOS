"""Deterministic entity extraction: tickers, companies and countries. No LLM involved.

ponytail: aliases live in code because the MVP universe is 14 assets. Move them to the assets
table when the universe grows.
"""

import re

# symbol -> names that identify it in a headline (case-sensitive, whole words)
ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("Apple",),
    "MSFT": ("Microsoft",),
    "NVDA": ("Nvidia", "NVIDIA"),
    "AMZN": ("Amazon",),
    "GOOGL": ("Alphabet", "Google"),
    "META": ("Meta Platforms", "Facebook"),
    "TSLA": ("Tesla",),
    "JPM": ("JPMorgan", "JP Morgan", "JPMorgan Chase"),
    "AMD": ("Advanced Micro Devices",),
    "NFLX": ("Netflix",),
    "BTC-USD": ("Bitcoin",),
    "ETH-USD": ("Ethereum",),
}
# Providers label tickers in their own way.
PROVIDER_TICKER_MAP = {"BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "BTC": "BTC-USD", "ETH": "ETH-USD"}
# Uppercase symbols that count as a ticker mention when they appear as a whole word.
_SYMBOL_WORDS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "AMD", "NFLX",
                 "SPY", "QQQ"]  # fmt: skip

_TICKER_OK = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")
_CASHTAG = re.compile(r"(?<![\w$])\$([A-Z]{1,5}(?:-USD)?)\b")
_SYMBOL_RE = re.compile(r"\b(" + "|".join(_SYMBOL_WORDS) + r")\b")
_ALIAS_RE = {
    symbol: re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
    for symbol, names in ALIASES.items()
}

_COUNTRIES: dict[str, tuple[str, ...]] = {
    "US": ("United States", "U.S.", "Federal Reserve", "Fed", "Treasury", "Wall Street", "SEC"),
    "CN": ("China", "Chinese", "Beijing", "PBOC"),
    "JP": ("Japan", "Japanese", "BOJ", "Tokyo"),
    "GB": ("Britain", "British", "U.K.", "UK", "Bank of England"),
    "DE": ("Germany", "German", "Bundesbank"),
    "IN": ("India", "Indian"),
    "EU": ("Eurozone", "euro area", "ECB", "European Union", "Europe"),
    "RU": ("Russia", "Russian", "Moscow"),
}
_COUNTRY_RE = {
    code: re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
    for code, names in _COUNTRIES.items()
}
MAX_TICKERS = 20


def extract_tickers(text: str, provider_tickers: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []

    def add(symbol: str) -> None:
        if symbol not in found and len(found) < MAX_TICKERS:
            found.append(symbol)

    for raw in provider_tickers:
        symbol = PROVIDER_TICKER_MAP.get(raw.upper(), raw.upper())
        if _TICKER_OK.match(symbol):
            add(symbol)
    for match in _CASHTAG.finditer(text):
        add(PROVIDER_TICKER_MAP.get(match.group(1), match.group(1)))
    for match in _SYMBOL_RE.finditer(text):
        add(match.group(1))
    for symbol, pattern in _ALIAS_RE.items():
        if pattern.search(text):
            add(symbol)
    return found


def extract_companies(text: str) -> list[str]:
    return [names[0] for symbol, names in ALIASES.items() if _ALIAS_RE[symbol].search(text)]


def extract_countries(text: str) -> list[str]:
    return [code for code, pattern in _COUNTRY_RE.items() if pattern.search(text)]
