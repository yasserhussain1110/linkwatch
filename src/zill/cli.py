from __future__ import annotations

import argparse
import asyncio
import json
import sys

from zill.audit import DEFAULT_MAX_PAGES, AuditError, Report, audit_site


def print_report(report: Report, *, show_healthy: bool) -> None:
    print("Zill — affiliate revenue at risk")
    print(f"Site: {report.site}")
    if report.site_title:
        print(f"Title: {report.site_title}")
    print(f"Pages crawled: {report.pages_crawled}")
    if report.pages_blocked:
        print(f"Pages the site refused: {report.pages_blocked}")
    print(f"Affiliate links found: {report.affiliate_links_found}")
    if report.truncated:
        print(f"Checked the first {report.links_checked}.")
    print()
    if report.crawl_error:
        print(report.crawl_error)
        return
    print(f"{report.problem_count} link(s) look like they're failing to earn")
    print(f"{report.healthy_count} look healthy")
    if report.unverified_count:
        print(f"{report.unverified_count} couldn't be verified")
    print()
    for finding in report.findings:
        if finding.bucket == "healthy" and not show_healthy:
            continue
        print(finding.anchor or finding.url)
        print(f"  {finding.url}")
        if finding.final_url and finding.final_url != finding.url:
            print(f"  Lands on: {finding.final_url}")
        for issue in finding.issues:
            print(f"  {issue.title}: {issue.summary}")
            print(f"  Next: {issue.action}")
        if not finding.issues:
            print("  Healthy")
        print(f"  Found on: {', '.join(finding.sources)}")
        print()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Find affiliate links that are failing to earn.")
    parser.add_argument("url", nargs="?", help="Site to crawl")
    parser.add_argument("--sample", action="store_true", help="Audit the built-in sample publisher")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--max-links", type=int, default=None, help="Check only the first N links (default: all)")
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Render pages in headless Chromium (slower, reads JavaScript-built pages)",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all", action="store_true", help="Include healthy links in the text report")
    args = parser.parse_args(argv)
    if not args.sample and not args.url:
        parser.error("Pass a site URL or --sample")

    async def run() -> Report:
        return await audit_site(
            args.url or "",
            sample=args.sample,
            max_pages=args.max_pages,
            max_links=args.max_links,
            respect_robots=not args.ignore_robots,
            use_browser=args.browser,
            on_progress=lambda message: print(message, file=sys.stderr),
        )

    try:
        report = asyncio.run(run())
    except AuditError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_report(report, show_healthy=args.all)
    if report.crawl_error:
        raise SystemExit(1)
