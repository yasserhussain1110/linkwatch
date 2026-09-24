from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

DROP_CRAWL_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".mjs",
    ".pdf",
    ".zip",
    ".gz",
    ".mp4",
    ".mp3",
    ".woff",
    ".woff2",
    ".xml",
    ".json",
}


def hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def canonical(url: str) -> str:
    """Normalize a URL enough to dedupe fetches without rewriting the query."""
    raw = url.strip()
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if not scheme or not host:
        return raw.split("#", 1)[0]
    if ":" in host:
        netloc = f"[{host}]"
    else:
        netloc = host
    port = parts.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{netloc}:{port}"
    # A trailing slash is load-bearing on some affiliate endpoints: Impact's
    # /p/ tracker returns 404 for /p. Never normalize it away.
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def parse_http_url(raw: str) -> str:
    raw = (raw or "").strip()
    if len(raw) > 2048:
        raise ValueError("That URL is too long.")
    if not raw.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://.")
    parts = urlsplit(raw)
    if not parts.hostname:
        raise ValueError("URL needs a hostname.")
    return canonical(raw)


def in_scope(start_url: str, url: str) -> bool:
    base = hostname(start_url).removeprefix("www.")
    host = hostname(url).removeprefix("www.")
    if not base or not host:
        return False
    return host == base or host.endswith("." + base)


def crawlable_path(url: str) -> bool:
    path = (urlsplit(url).path or "").lower()
    return not any(path.endswith(ext) for ext in DROP_CRAWL_EXTENSIONS)
