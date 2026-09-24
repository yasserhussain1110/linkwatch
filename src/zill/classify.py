from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from zill.urls import canonical, crawlable_path, hostname, in_scope

AMAZON_HOSTS = {
    "amazon.com",
    "amazon.co.uk",
    "amazon.ca",
    "amazon.de",
    "amazon.fr",
    "amazon.it",
    "amazon.es",
    "amazon.co.jp",
    "amazon.in",
    "amazon.com.au",
    "amazon.com.br",
    "amazon.com.mx",
    "amazon.nl",
    "amazon.sg",
    "amazon.ae",
    "amazon.sa",
    "amazon.pl",
    "amazon.se",
    "amazon.com.tr",
    "amzn.to",
    "amzn.eu",
    "amzn.asia",
    "a.co",
}
AMAZON_SHORT = {"amzn.to", "amzn.eu", "amzn.asia", "a.co"}
NETWORK_HOSTS = {
    "shareasale.com",
    "shareasale-analytics.com",
    "awin1.com",
    "zenaps.com",
    "anrdoezrs.net",
    "dpbolvw.net",
    "jdoqocy.com",
    "tkqlhce.com",
    "kqzuq.com",
    "qksrv.net",
    "emjcd.com",
    "afcyhf.com",
    "ftmpsu.com",
    "lduhtrp.net",
    "tqlkg.com",
    "commission-junction.com",
    "pjtra.com",
    "pjatr.com",
    "pntra.com",
    "pntrs.com",
    "gopjn.com",
    "prf.hn",
    "sjv.io",
    "evyy.net",
    "7eer.net",
    "8cnq.net",
    "pxf.io",
    "ojrq.net",
    "syuh.net",
    "linksynergy.com",
    "clickbank.net",
    "avantlink.com",
    "flexlinks.com",
    "skimresources.com",
    "viglink.com",
    "rstyle.me",
    "howl.link",
    "howl.me",
    "shopltk.com",
    "geni.us",
    "shopstyle.it",
    "partnerize.com",
    "webgains.com",
    "tradedoubler.com",
}
AFFILIATE_QUERY_KEYS = {
    "irclickid",
    "cjevent",
    "sscid",
    "awinaffid",
    "awinmid",
    "clickref",
    "aff_id",
    "affiliate_id",
    "affid",
}
ASSOCIATE_KEYS = {"tag", "ascsubtag", "linkcode", "linkid"}
REDIRECT_PREFIXES = ("/go/", "/recommends/", "/recommend/", "/out/", "/visit/", "/link/")
ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.I)
KIND_RANK = {"amazon": 5, "network": 4, "tagged": 3, "redirector": 2, "sponsored": 1}


@dataclass(frozen=True)
class FoundLink:
    url: str
    source_page: str
    anchor: str
    kind: str


@dataclass
class AffiliateLink:
    url: str
    sources: list[str]
    anchor: str
    kind: str


@dataclass(frozen=True)
class PageLinks:
    affiliate: list[FoundLink]
    crawl: list[str]


def host_matches(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def is_amazon_host(url: str) -> bool:
    return host_matches(hostname(url), AMAZON_HOSTS)


def is_amazon_short(url: str) -> bool:
    return host_matches(hostname(url), AMAZON_SHORT)


def is_network_host(url: str) -> bool:
    return host_matches(hostname(url), NETWORK_HOSTS)


def asin(url: str) -> str | None:
    match = ASIN_RE.search(urlsplit(url).path or "")
    return match.group(1).upper() if match else None


def query_keys(url: str) -> set[str]:
    return {key.lower() for key in parse_qs(urlsplit(url).query, keep_blank_values=True)}


def has_associate_tag(url: str) -> bool:
    return bool(query_keys(url) & ASSOCIATE_KEYS)


def same_site(page_url: str, url: str) -> bool:
    page_host = hostname(page_url).removeprefix("www.")
    host = hostname(url).removeprefix("www.")
    if not page_host or not host:
        return False
    return host == page_host or host.endswith("." + page_host) or page_host.endswith("." + host)


def is_redirect_prefix(url: str) -> bool:
    path = urlsplit(url).path or ""
    return any(path.startswith(prefix) for prefix in REDIRECT_PREFIXES)


def classify_kind(page_url: str, url: str, rel: str) -> str | None:
    if is_network_host(url):
        return "network"
    if is_amazon_host(url) and (asin(url) or has_associate_tag(url) or is_amazon_short(url)):
        return "amazon"
    if query_keys(url) & AFFILIATE_QUERY_KEYS:
        return "tagged"
    if same_site(page_url, url) and is_redirect_prefix(url):
        return "redirector"
    if "sponsored" in set(rel.lower().split()) and not same_site(page_url, url):
        return "sponsored"
    return None


def extract_page_links(page_url: str, html: str, start_url: str) -> PageLinks:
    soup = BeautifulSoup(html, "html.parser")
    affiliate: list[FoundLink] = []
    crawl: list[str] = []
    for tag in soup.find_all("a", href=True):
        raw = tag.get("href")
        if not isinstance(raw, str):
            continue
        raw = raw.strip()
        if not raw or raw.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        absolute = urljoin(page_url, raw)
        if urlsplit(absolute).scheme not in {"http", "https"}:
            continue
        cleaned = canonical(absolute)
        if not hostname(cleaned):
            continue
        rel = tag.get("rel") or []
        rel_s = rel if isinstance(rel, str) else " ".join(rel)
        kind = classify_kind(page_url, cleaned, rel_s)
        if kind:
            anchor = " ".join(tag.get_text(" ", strip=True).split())[:160]
            affiliate.append(FoundLink(url=cleaned, source_page=canonical(page_url), anchor=anchor, kind=kind))
            continue
        if in_scope(start_url, cleaned) and crawlable_path(cleaned) and len(crawl) < 100:
            crawl.append(cleaned)
        if len(affiliate) >= 100:
            break
    return PageLinks(affiliate=affiliate, crawl=crawl)


def merge_links(found: list[FoundLink]) -> list[AffiliateLink]:
    order: list[str] = []
    by_url: dict[str, AffiliateLink] = {}
    for item in found:
        existing = by_url.get(item.url)
        if existing is None:
            by_url[item.url] = AffiliateLink(
                url=item.url,
                sources=[item.source_page],
                anchor=item.anchor,
                kind=item.kind,
            )
            order.append(item.url)
            continue
        if item.source_page not in existing.sources:
            existing.sources.append(item.source_page)
        if not existing.anchor and item.anchor:
            existing.anchor = item.anchor
        if KIND_RANK[item.kind] > KIND_RANK[existing.kind]:
            existing.kind = item.kind
    return [by_url[url] for url in order]
