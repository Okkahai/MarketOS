"""Cleaning of untrusted text and URLs. Everything collected from the web goes through here."""

import hashlib
import html
import re
import unicodedata
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # includes NUL, which PostgreSQL rejects
_TAGS = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"\w+")
_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|cmpid|ocid|taid)$", re.I)
_DEFAULT_PORTS = {"http": 80, "https": 443}

MAX_URL_LENGTH = 2000


def clean_text(value: Any, max_len: int) -> str:
    """Plain text: markup removed, entities decoded, control characters dropped, whitespace
    collapsed and length capped. The result is data; it is never interpreted as HTML."""
    text = _TAGS.sub(" ", str(value))
    text = html.unescape(text)
    text = _CONTROL.sub("", text)
    return _SPACE.sub(" ", text).strip()[:max_len].rstrip()


def title_tokens_list(title: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", title).casefold())


def normalize_title(title: str) -> str:
    return " ".join(title_tokens_list(title))


def content_hash(title_norm: str) -> str:
    return hashlib.sha256(title_norm.encode()).hexdigest()


def canonicalize_url(url: str) -> str:
    """Same page, same string: lowercase host, no fragment, no tracking parameters, sorted query.

    Raises ValueError for anything that is not an http(s) URL, so javascript: and data: links
    from a feed can never reach the UI.
    """
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH or _CONTROL.search(url):
        raise ValueError("url is empty, too long or contains control characters")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) url: scheme {scheme!r}")
    host = parts.hostname.lower().removeprefix("www.")
    if parts.port and parts.port != _DEFAULT_PORTS[scheme]:
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def scrub_json(value: Any) -> Any:
    """A copy safe for a JSONB column: strings cleaned of NUL/control characters, Decimal as str."""
    if isinstance(value, str):
        return _CONTROL.sub("", value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {_CONTROL.sub("", str(k)): scrub_json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub_json(v) for v in value]
    return value
