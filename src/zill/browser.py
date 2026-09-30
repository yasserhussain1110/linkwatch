from __future__ import annotations

import asyncio
import os
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

from zill.fetch import UA_TOKEN, FetchResult, assess
from zill.urls import canonical, hostname

BUNDLED_BROWSERS = Path(__file__).resolve().parents[2] / ".playwright"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)
SKIP_RESOURCES = {"image", "media", "font"}
NAV_TIMEOUT_MS = 45_000


class BrowserUnavailable(RuntimeError):
    pass


class BrowserFetcher:
    """Renders pages in headless Chromium so JavaScript-built pages can be read.

    Merchants such as Amazon serve a stub to plain HTTP clients, so availability
    can only be judged from a rendered page.
    """

    def __init__(self, concurrency: int = 3, timeout_ms: int = NAV_TIMEOUT_MS) -> None:
        self._concurrency = max(1, concurrency)
        self._timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._semaphore = asyncio.Semaphore(self._concurrency)
        self._host_safety: dict[str, tuple[str, str | None]] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def __aenter__(self) -> BrowserFetcher:
        if BUNDLED_BROWSERS.is_dir():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BUNDLED_BROWSERS))
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailable(
                "Headless browsing needs Playwright. Install it with: "
                "pip install playwright && playwright install chromium"
            ) from exc

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception as exc:
            await self._playwright.stop()
            raise BrowserUnavailable(
                "Chromium wouldn't start. Install it with: playwright install chromium"
            ) from exc
        self._context = await self._browser.new_context(
            user_agent=BROWSER_UA,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        self._context.set_default_navigation_timeout(self._timeout_ms)
        await self._context.route("**/*", self._filter_assets)
        return self

    async def __aexit__(self, *exc: object) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    pass
        if self._playwright is not None:
            await self._playwright.stop()

    async def _filter_assets(self, route, request) -> None:
        """Skip images and fonts. Scripts still run, so rendered content is intact."""
        if request.resource_type in SKIP_RESOURCES:
            await route.abort()
        else:
            await route.continue_()

    async def _safety(self, url: str) -> tuple[str, str | None]:
        host = hostname(url)
        if host and host in self._host_safety:
            return self._host_safety[host]
        result = await asyncio.to_thread(assess, url)
        if host:
            self._host_safety[host] = result
        return result

    async def get(self, url: str) -> FetchResult:
        target = canonical(url)
        safety, _reason = await self._safety(target)
        if safety == "dns":
            return FetchResult(requested_url=target, error="dns")
        if safety != "ok":
            return FetchResult(requested_url=target, error="denied")
        if self._context is None:
            raise BrowserUnavailable("The browser isn't running.")

        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        async with self._semaphore:
            page = await self._context.new_page()
            try:
                response = await page.goto(target, wait_until="domcontentloaded")
                if response is None:
                    return FetchResult(requested_url=target, error="unreachable")
                html = await page.content()
                final = canonical(page.url)
                # A private address behind a redirect must not be readable.
                final_safety, _ = await self._safety(final)
                if final_safety != "ok":
                    return FetchResult(requested_url=target, error="denied")
                return FetchResult(
                    requested_url=target,
                    final_url=final,
                    status_code=response.status,
                    text=html,
                    content_type=(response.headers or {}).get("content-type", "text/html"),
                    redirect_chain=_chain(response, target),
                    error=None,
                )
            except PlaywrightTimeout:
                return FetchResult(requested_url=target, error="timeout")
            except PlaywrightError as exc:
                message = str(exc)
                if "ERR_NAME_NOT_RESOLVED" in message:
                    return FetchResult(requested_url=target, error="dns")
                if "ERR_TOO_MANY_REDIRECTS" in message:
                    return FetchResult(requested_url=target, error="too_many_redirects")
                return FetchResult(requested_url=target, error="unreachable")
            finally:
                await page.close()

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(canonical(url))
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            result = await self.get(f"{origin}/robots.txt")
            parser = urllib.robotparser.RobotFileParser()
            if result.error is None and result.status_code == 200:
                parser.parse(_plain_text(result.text).splitlines())
            else:
                parser.parse([])
            self._robots[origin] = parser
        try:
            return bool(self._robots[origin].can_fetch(UA_TOKEN, url))
        except Exception:
            return True


def _chain(response, target: str) -> list[str]:
    hops: list[str] = []
    request = response.request
    while request is not None:
        hops.append(canonical(request.url))
        request = request.redirected_from
    hops.reverse()
    return hops or [target]


def _plain_text(html: str) -> str:
    """Chromium wraps text/plain in a <pre> block; robots.txt needs the raw lines."""
    import re

    match = re.search(r"<pre[^>]*>(.*?)</pre>", html or "", re.S | re.I)
    body = match.group(1) if match else (html or "")
    body = re.sub(r"<[^>]+>", "", body)
    return (
        body.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
    )
