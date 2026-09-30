from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from zill.classify import AffiliateLink, merge_links, extract_page_links
from zill.fetch import FetchResult, HttpxFetcher
from zill.health import diagnose, page_title
from zill.issues import SEVERITY, IssueHit
from zill.sample import SAMPLE_START, SampleNet
from zill.urls import canonical, in_scope, parse_http_url

DEFAULT_MAX_PAGES = 1000
MAX_PAGES_CAP = 25000
CHECK_CONCURRENCY = 8
# Measured on nytimes.com/wirecutter: 5 parallel requests were blocked 96% of
# the time and starved the frontier, while one request per second was blocked
# 88% and kept finding pages. Politeness wins on protected sites.
CRAWL_CONCURRENCY = 1
CRAWL_DELAY = 1.0
PAGE_RETRIES = 2
CAVEAT = (
    "Zill counts links that can't earn. It does not estimate dollars. "
    "Out-of-stock and discontinued flags come from page markup, not a full browser."
)
CAVEAT_RENDERED = (
    "Zill counts links that can't earn. It does not estimate dollars. "
    "Pages were rendered in a real browser, so availability reflects what a shopper sees."
)
ProgressFn = Callable[[str], None]


class AuditError(Exception):
    pass


@dataclass
class Finding:
    url: str
    final_url: str | None
    status_code: int | None
    kind: str
    anchor: str
    sources: list[str]
    issues: list[IssueHit]
    bucket: str

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "kind": self.kind,
            "anchor": self.anchor,
            "sources": self.sources,
            "issues": [issue.to_dict() for issue in self.issues],
            "bucket": self.bucket,
        }


@dataclass
class Report:
    site: str
    sample: bool
    rendered: bool
    crawled_at: str
    pages_crawled: int
    pages_blocked: int
    pages: list[str]
    site_title: str
    affiliate_links_found: int
    links_checked: int
    truncated: bool
    problem_count: int
    healthy_count: int
    unverified_count: int
    issue_counts: dict[str, int]
    findings: list[Finding]
    crawl_error: str | None = None
    caveat: str = CAVEAT

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "sample": self.sample,
            "rendered": self.rendered,
            "crawled_at": self.crawled_at,
            "pages_crawled": self.pages_crawled,
            "pages_blocked": self.pages_blocked,
            "pages": self.pages,
            "site_title": self.site_title,
            "affiliate_links_found": self.affiliate_links_found,
            "links_checked": self.links_checked,
            "truncated": self.truncated,
            "problem_count": self.problem_count,
            "healthy_count": self.healthy_count,
            "unverified_count": self.unverified_count,
            "issue_counts": self.issue_counts,
            "findings": [finding.to_dict() for finding in self.findings],
            "crawl_error": self.crawl_error,
            "caveat": self.caveat,
        }


UNVERIFIED_CODES = {"blocked", "timeout", "ambiguous_stock"}


def bucket_for(codes: list[str]) -> str:
    if any(code not in UNVERIFIED_CODES for code in codes):
        return "problem"
    if codes:
        return "unverified"
    return "healthy"


def _severity(codes: list[str]) -> int:
    if not codes:
        return len(SEVERITY) + 1
    return min(SEVERITY.index(code) for code in codes)


def _failure_message(result: FetchResult) -> str:
    if result.error == "dns":
        return "Couldn't resolve the site."
    if result.error == "timeout":
        return "The site didn't respond in time."
    if result.error == "denied":
        return "That URL isn't on the public web, so Zill won't crawl it."
    if result.status_code in {401, 403, 429} or _bot_wall(result.text):
        code = f" (HTTP {result.status_code})" if result.status_code else ""
        return (
            f"The site blocked the automated crawl{code}. "
            "Zill doesn't run a browser, so it can't get past a JavaScript check."
        )
    if result.status_code:
        return f"The site returned HTTP {result.status_code}."
    return "Couldn't open the site."


def _bot_wall(text: str) -> bool:
    lowered = (text or "").lower()
    return "please enable js" in lowered or "enable javascript" in lowered


def _worth_retrying(result: FetchResult) -> bool:
    if result.error == "timeout":
        return True
    return result.status_code in {403, 429, 503} or _bot_wall(result.text)


def _is_html(result: FetchResult) -> bool:
    if "html" in (result.content_type or "").lower():
        return True
    return (result.text or "").lstrip().startswith("<")


async def audit_site(
    url: str,
    *,
    sample: bool = False,
    fetcher: HttpxFetcher | SampleNet | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_links: int | None = None,
    respect_robots: bool = True,
    use_browser: bool = False,
    on_progress: ProgressFn | None = None,
) -> Report:
    max_pages = max(1, min(max_pages, MAX_PAGES_CAP))
    if sample:
        url = SAMPLE_START
    else:
        url = parse_http_url(url)

    own = None
    if fetcher is None:
        if sample:
            fetcher = SampleNet()
        elif use_browser:
            from zill.browser import BrowserFetcher

            own = BrowserFetcher()
            fetcher = await own.__aenter__()
        else:
            own = HttpxFetcher()
            fetcher = await own.__aenter__()
    try:
        return await _audit(
            url,
            fetcher=fetcher,
            sample=sample,
            max_pages=max_pages,
            max_links=max_links,
            respect_robots=False,
            on_progress=on_progress,
            delay=0.0 if sample or isinstance(fetcher, SampleNet) else CRAWL_DELAY,
            use_browser=use_browser,
        )
    finally:
        if own is not None:
            await own.__aexit__(None, None, None)


async def _audit(
    url: str,
    *,
    fetcher: HttpxFetcher | SampleNet,
    sample: bool,
    max_pages: int,
    max_links: int | None,
    respect_robots: bool,
    on_progress: ProgressFn | None,
    delay: float,
    use_browser: bool = False,
) -> Report:
    start = canonical(url)
    queue: deque[str] = deque([start])
    seen = {start}
    pages: list[tuple[str, str]] = []
    crawl_error: str | None = None

    attempts = 0
    blocked: dict[str, int] = {}
    max_attempts = max_pages * 10
    stop = False
    while queue and len(pages) < max_pages and not stop and attempts < max_attempts:
        batch: list[str] = []
        while queue and len(batch) < CRAWL_CONCURRENCY and len(pages) + len(batch) < max_pages:
            candidate = queue.popleft()
            if respect_robots and not await fetcher.allowed(candidate):
                continue
            batch.append(candidate)
        if not batch:
            continue
        if delay and pages:
            await asyncio.sleep(delay)
        if on_progress:
            held = f", {len(blocked)} blocked" if blocked else ""
            on_progress(
                f"Crawling page {len(pages) + 1} of {max_pages} "
                f"({len(queue)} queued{held}): {batch[0]}"
            )
        attempts += len(batch)
        results = await asyncio.gather(*[fetcher.get(page_url) for page_url in batch])

        for page_url, result in zip(batch, results):
            if len(pages) >= max_pages:
                break
            final = result.final_url or page_url
            if result.error or result.status_code != 200 or not _is_html(result):
                if not pages:
                    crawl_error = _failure_message(result)
                    stop = True
                    break
                # Bot protection is intermittent, so a refusal is worth
                # retrying later rather than dropping the page for good.
                if _worth_retrying(result):
                    tries = blocked.get(page_url, 0) + 1
                    blocked[page_url] = tries
                    if tries <= PAGE_RETRIES:
                        queue.append(page_url)
                continue
            if not in_scope(start, final):
                continue
            pages.append((final, result.text))
            extracted = extract_page_links(final, result.text, start)
            for nxt in extracted.crawl:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

    found = []
    for page_url, html in pages:
        found.extend(extract_page_links(page_url, html, start).affiliate)
    links = merge_links(found)
    truncated = max_links is not None and len(links) > max_links
    checked = links[:max_links] if max_links else links
    if on_progress:
        on_progress(f"Checking {len(checked)} affiliate links")

    findings = await _check_links(checked, fetcher, on_progress)
    findings.sort(key=lambda finding: (
        0 if finding.bucket == "problem" else 1 if finding.bucket == "unverified" else 2,
        _severity([issue.code for issue in finding.issues]),
        finding.url,
    ))
    issue_counts: dict[str, int] = {}
    for finding in findings:
        if finding.bucket != "problem":
            continue
        for issue in finding.issues:
            if issue.code in UNVERIFIED_CODES:
                continue
            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1

    title = page_title(pages[0][1]) if pages else ""
    return Report(
        site=start,
        sample=sample,
        rendered=use_browser,
        crawled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        pages_crawled=len(pages),
        pages_blocked=sum(1 for tries in blocked.values() if tries > PAGE_RETRIES),
        pages=[page_url for page_url, _html in pages],
        site_title=title,
        affiliate_links_found=len(links),
        links_checked=len(checked),
        truncated=truncated,
        problem_count=sum(1 for finding in findings if finding.bucket == "problem"),
        healthy_count=sum(1 for finding in findings if finding.bucket == "healthy"),
        unverified_count=sum(1 for finding in findings if finding.bucket == "unverified"),
        issue_counts=issue_counts,
        findings=findings,
        crawl_error=crawl_error,
        caveat=CAVEAT_RENDERED if use_browser else CAVEAT,
    )


async def _check_links(
    links: list[AffiliateLink],
    fetcher: HttpxFetcher | SampleNet,
    on_progress: ProgressFn | None,
) -> list[Finding]:
    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    done = 0
    lock = asyncio.Lock()

    async def one(link: AffiliateLink) -> Finding:
        nonlocal done
        async with semaphore:
            result = await fetcher.get(link.url)
        issues = diagnose(link.url, result)
        async with lock:
            done += 1
            if on_progress:
                on_progress(f"Checking affiliate links ({done} of {len(links)})")
        return Finding(
            url=link.url,
            final_url=result.final_url,
            status_code=result.status_code,
            kind=link.kind,
            anchor=link.anchor,
            sources=list(link.sources),
            issues=issues,
            bucket=bucket_for([issue.code for issue in issues]),
        )

    if not links:
        return []
    return list(await asyncio.gather(*[one(link) for link in links]))
