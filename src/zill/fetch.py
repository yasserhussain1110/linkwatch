from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from zill.urls import canonical, hostname

UA = "ZillAffiliateAudit/0.1 (+public affiliate link check)"
UA_TOKEN = "ZillAffiliateAudit"
Resolver = Callable[..., list]

BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
MAX_HOPS = 12
RETRY_PAUSES = (2.0, 4.0)


@dataclass
class FetchResult:
    requested_url: str
    final_url: str | None = None
    status_code: int | None = None
    text: str = ""
    content_type: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    error: str | None = None


def _ip_is_public(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return bool(addr.is_global)


def assess(url: str, resolver: Resolver = socket.getaddrinfo) -> tuple[str, str | None]:
    """Return ('ok'|'denied'|'dns', reason). Private and local targets are denied."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return "denied", "unsupported scheme"
    host = parts.hostname
    if not host:
        return "denied", "missing host"
    host_l = host.lower().rstrip(".")
    if host_l in BLOCKED_HOSTS or host_l.endswith(".localhost") or host_l.endswith(".local"):
        return "denied", "local host"
    if host_l.isdigit():
        return "denied", "numeric host"
    try:
        literal = ipaddress.ip_address(host_l)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            return "denied", "non-public address"
        return "ok", None
    try:
        infos = resolver(host_l, None)
    except socket.gaierror:
        return "dns", "dns"
    except OSError:
        return "dns", "dns"
    addresses: list[str] = []
    for info in infos or []:
        sockaddr = info[4]
        if sockaddr:
            addresses.append(sockaddr[0])
    if not addresses:
        return "dns", "dns"
    for raw in addresses:
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            return "denied", "bad address"
        if not _ip_is_public(addr):
            return "denied", "non-public address"
    return "ok", None


class HttpxFetcher:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None
        self._host_safety: dict[str, tuple[str, str | None]] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def __aenter__(self) -> HttpxFetcher:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=8.0),
                follow_redirects=False,
                headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"},
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _safety(self, url: str) -> tuple[str, str | None]:
        host = hostname(url)
        if host and host in self._host_safety:
            return self._host_safety[host]
        result = await asyncio.to_thread(assess, url)
        if host:
            self._host_safety[host] = result
        return result

    async def _request(self, url: str) -> FetchResult:
        assert self._client is not None
        safety, _reason = await self._safety(url)
        if safety == "dns":
            return FetchResult(requested_url=url, error="dns")
        if safety != "ok":
            return FetchResult(requested_url=url, error="denied")

        visited: list[str] = []
        current = url
        for _ in range(MAX_HOPS):
            safety, _reason = await self._safety(current)
            if safety == "dns":
                return FetchResult(requested_url=url, final_url=None, redirect_chain=visited, error="dns")
            if safety != "ok":
                return FetchResult(requested_url=url, final_url=None, redirect_chain=visited, error="denied")
            visited.append(current)
            try:
                response = await self._client.get(current)
            except httpx.TimeoutException:
                return FetchResult(requested_url=url, final_url=current, redirect_chain=visited, error="timeout")
            except httpx.ConnectError as exc:
                message = str(exc).lower()
                error = "dns" if any(token in message for token in ("name or service", "nodename", "getaddrinfo", "temporary failure")) else "unreachable"
                return FetchResult(requested_url=url, final_url=current, redirect_chain=visited, error=error)
            except httpx.HTTPError:
                return FetchResult(requested_url=url, final_url=current, redirect_chain=visited, error="unreachable")

            status = response.status_code
            location = response.headers.get("location")
            if status in {301, 302, 303, 307, 308} and location:
                current = canonical(urljoin(current, location.strip()))
                continue

            # Availability markup often sits late in the document; Costco's page
            # alone is ~500KB, so a tight cap silently hides the offer.
            raw = response.content[:2_000_000]
            encoding = response.encoding or "utf-8"
            text = raw.decode(encoding, errors="replace")
            return FetchResult(
                requested_url=url,
                final_url=canonical(str(response.url)),
                status_code=status,
                text=text,
                content_type=response.headers.get("content-type", ""),
                redirect_chain=visited,
                error=None,
            )
        return FetchResult(requested_url=url, redirect_chain=visited, error="too_many_redirects")

    async def get(self, url: str) -> FetchResult:
        """Retry timeouts before reporting them: affiliate chains are several slow hops."""
        target = canonical(url)
        result = await self._request(target)
        for pause in RETRY_PAUSES:
            if result.error != "timeout":
                break
            await asyncio.sleep(pause)
            result = await self._request(target)
        return result

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(canonical(url))
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            result = await self._request(robots_url)
            parser = urllib.robotparser.RobotFileParser()
            if result.error is None and result.status_code == 200:
                parser.parse((result.text or "").splitlines())
            else:
                parser.parse([])
            self._robots[origin] = parser
        try:
            return bool(self._robots[origin].can_fetch(UA_TOKEN, url))
        except Exception:
            return True
