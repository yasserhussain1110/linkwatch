from __future__ import annotations

import re
from urllib.parse import urlsplit

from zill.classify import asin, has_associate_tag, is_amazon_host, is_amazon_short, is_network_host
from zill.fetch import FetchResult
from zill.issues import IssueHit, hit

SOFT_NOT_FOUND = re.compile(
    r"(page not found|404 not found|product not found|we couldn't find that page|not a functioning page)",
    re.I,
)
AMAZON_DEAD_END = re.compile(r"^/(s|gp/search|gp/errors|gp/404)(/|$)", re.I)
REGION_PHRASE = re.compile(
    r"(not available in your country|unavailable in your region|does not ship to your)",
    re.I,
)
CLASS_OUT_OF_STOCK = re.compile(
    r"""(?:class|id)=["'][^"']*(?:out-of-stock|outofstock|availability--out)""",
    re.I,
)


def page_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", text).strip()


def availability_signals(html: str) -> set[str]:
    lowered = html.lower()
    signals: set[str] = set()
    if "schema.org/discontinued" in lowered or re.search(r'"availability"\s*:\s*"discontinued"', lowered):
        signals.add("discontinued")
    if (
        "schema.org/outofstock" in lowered
        or "schema.org/soldout" in lowered
        or re.search(r'"availability"\s*:\s*"outofstock"', lowered)
        or CLASS_OUT_OF_STOCK.search(html)
    ):
        signals.add("out_of_stock")
    if "schema.org/instock" in lowered or re.search(r'"availability"\s*:\s*"instock"', lowered):
        signals.add("in_stock")
    for match in re.finditer(
        r'itemprop=["\']availability["\'][^>]*content=["\']([^"\']+)|content=["\']([^"\']+)["\'][^>]*itemprop=["\']availability["\']',
        html,
        re.I,
    ):
        value = (match.group(1) or match.group(2) or "").lower()
        if "discontinued" in value:
            signals.add("discontinued")
        elif "outofstock" in value or "out of stock" in value or "soldout" in value:
            signals.add("out_of_stock")
        elif "instock" in value or "in stock" in value:
            signals.add("in_stock")
    if REGION_PHRASE.search(html):
        signals.add("region")
    return signals


def is_soft_not_found(html: str) -> bool:
    title = page_title(html)
    if title and SOFT_NOT_FOUND.search(title):
        return True
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if not match:
        return False
    heading = re.sub(r"<[^>]+>", " ", match.group(1))
    heading = re.sub(r"\s+", " ", heading).strip()
    return len(heading) < 120 and bool(SOFT_NOT_FOUND.search(heading))


def is_home(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.path or "/") == "/" and not parts.query


def is_search_fallback(url: str) -> bool:
    if not is_amazon_host(url):
        return False
    return bool(AMAZON_DEAD_END.match(urlsplit(url).path or "/"))


def _dedupe(issues: list[IssueHit]) -> list[IssueHit]:
    seen: set[str] = set()
    unique: list[IssueHit] = []
    for issue in issues:
        if issue.code in seen:
            continue
        seen.add(issue.code)
        unique.append(issue)
    return unique


def diagnose(url: str, fetch: FetchResult) -> list[IssueHit]:
    issues: list[IssueHit] = []
    final = fetch.final_url or url

    if asin(url) and is_amazon_host(url) and not has_associate_tag(url) and not is_amazon_short(url):
        issues.append(
            hit(
                "missing_attribution",
                "This Amazon product link has no associate tag, so a sale may not be credited to you.",
            )
        )

    if fetch.error == "dns":
        if is_network_host(url):
            issues.append(hit("network_failure", f"The tracking domain {hostname_or(url)} doesn't resolve."))
        else:
            issues.append(hit("unreachable", f"The link doesn't resolve ({hostname_or(url)})."))
        return _dedupe(issues)
    if fetch.error == "timeout":
        issues.append(hit("timeout", "The destination didn't respond in time."))
        return _dedupe(issues)
    if fetch.error == "denied":
        issues.append(hit("blocked", "Zill skipped this URL because it doesn't point at the public web."))
        return _dedupe(issues)
    if fetch.error == "too_many_redirects":
        issues.append(hit("network_failure", "The link redirected too many times and never settled on a product."))
        return _dedupe(issues)
    if fetch.error:
        issues.append(hit("unreachable", "The link couldn't be opened."))
        return _dedupe(issues)

    status = fetch.status_code
    if status in {401, 403, 429}:
        issues.append(
            hit(
                "blocked",
                f"The site returned HTTP {status}, so an automated check couldn't see the page. It may still work in a browser.",
            )
        )
        return _dedupe(issues)
    if status in {404, 410} or (status is not None and 400 <= status < 500):
        issues.append(hit("broken", f"Shoppers get HTTP {status} instead of a product."))
        return _dedupe(issues)
    if status is not None and status >= 500:
        if is_network_host(url) and is_network_host(final):
            issues.append(
                hit(
                    "network_failure",
                    f"The affiliate network returned HTTP {status} and never handed the shopper to a product.",
                )
            )
        else:
            issues.append(hit("server_error", f"The destination returned HTTP {status}."))
        return _dedupe(issues)
    if status in {301, 302, 303, 307, 308}:
        issues.append(hit("network_failure", "The link redirected without landing on a page."))
        return _dedupe(issues)
    if status != 200:
        issues.append(hit("soft_not_found", f"The link returned HTTP {status} without a product page."))
        return _dedupe(issues)

    if is_network_host(url) and is_network_host(final):
        issues.append(hit("network_failure", "The tracking link never left the affiliate network."))

    signals = availability_signals(fetch.text or "")
    if "discontinued" in signals:
        issues.append(hit("discontinued", "The product page says this item is discontinued."))
    elif "out_of_stock" in signals:
        issues.append(hit("out_of_stock", "The product page loads, but the item is out of stock."))
    elif "region" in signals and "in_stock" not in signals:
        issues.append(
            hit(
                "region_unavailable",
                "The product doesn't appear to be available in the region this check ran from.",
            )
        )
    elif "in_stock" not in signals and is_soft_not_found(fetch.text or ""):
        issues.append(
            hit(
                "soft_not_found",
                "The site returns a success page, but the copy says the product can't be found.",
            )
        )

    redirected = len(fetch.redirect_chain) >= 2
    if redirected and not is_home(url) and is_home(final):
        issues.append(
            hit(
                "homepage_redirect",
                "After the redirect, shoppers land on the store homepage instead of a product.",
            )
        )
    elif redirected and is_search_fallback(final) and not is_search_fallback(url):
        issues.append(hit("homepage_redirect", "The product link falls through to Amazon search or an error page."))

    start_asin = asin(url)
    final_asin = asin(final)
    if start_asin and final_asin and start_asin != final_asin:
        issues.append(hit("wrong_product", f"The link starts on Amazon {start_asin} and ends on {final_asin}."))

    if is_amazon_host(url) and is_amazon_host(final) and has_associate_tag(url) and not has_associate_tag(final):
        issues.append(
            hit(
                "tracking_lost",
                "The associate tag is gone on the final Amazon URL, so the sale may not be credited.",
            )
        )
    return _dedupe(issues)


def hostname_or(url: str) -> str:
    from zill.urls import hostname

    return hostname(url) or "unknown host"
