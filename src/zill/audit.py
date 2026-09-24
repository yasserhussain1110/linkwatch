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

MAX_LINKS = 50
CAVEAT = (
    "Zill counts links that can't earn. It does not estimate dollars. "
    "Out-of-stock and discontinued flags come from page markup, not a full browser."
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
    crawled_at: str
    pages_crawled: int
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
            "crawled_at": self.crawled_at,
            "pages_crawled": self.pages_crawled,
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


def bucket_for(codes: list[str]) -> str:
    if any(code != "blocked" for code in codes):
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


def _is_html(result: FetchResult) -> bool:
    if "html" in (result.content_type or "").lower():
        return True
    return (result.text or "").lstrip().startswith("<")


async def audit_site(
    url: str,
    *,
    sample: bool = False,
    fetcher: HttpxFetcher | SampleNet | None = None,
    max_pages: int = 25,
    respect_robots: bool = True,
    on_progress: ProgressFn | None = None,
) -> Report:
    max_pages = max(1, min(max_pages, 40))
    if sample:
        url = SAMPLE_START
    else:
        url = parse_http_url(url)

    own: HttpxFetcher | None = None
    if fetcher is None:
        if sample:
            fetcher = SampleNet()
        else:
            own = HttpxFetcher()
            fetcher = await own.__aenter__()
    try:
        return await _audit(
            url,
            fetcher=fetcher,
            sample=sample,
            max_pages=max_pages,
            respect_robots=respect_robots,
            on_progress=on_progress,
            delay=0.0 if sample or isinstance(fetcher, SampleNet) else 0.15,
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
    respect_robots: bool,
    on_progress: ProgressFn | None,
    delay: float,
) -> Report:
    start = canonical(url)
    queue: deque[str] = deque([start])
    seen = {start}
    pages: list[tuple[str, str]] = []
    crawl_error: str | None = None

    while queue and len(pages) < max_pages:
        page_url = queue.popleft()
        if respect_robots and not await fetcher.allowed(page_url):
            continue
        if delay and pages:
            await asyncio.sleep(delay)
        if on_progress:
            on_progress(f"Crawling {page_url}")
        result = await fetcher.get(page_url)
        final = result.final_url or page_url
        if result.error or result.status_code != 200 or not _is_html(result):
            if not pages:
                crawl_error = _failure_message(result)
                break
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
    truncated = len(links) > MAX_LINKS
    checked = links[:MAX_LINKS]
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
            if issue.code == "blocked":
                continue
            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1

    title = page_title(pages[0][1]) if pages else ""
    return Report(
        site=start,
        sample=sample,
        crawled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        pages_crawled=len(pages),
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
    )


async def _check_links(
    links: list[AffiliateLink],
    fetcher: HttpxFetcher | SampleNet,
    on_progress: ProgressFn | None,
) -> list[Finding]:
    semaphore = asyncio.Semaphore(5)
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
