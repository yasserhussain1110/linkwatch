import asyncio

import httpx
from fastapi.testclient import TestClient

from zill.app import app
from zill.audit import audit_site
from zill.fetch import FetchResult
from zill.sample import (
    SAMPLE_START,
    URL_BROKEN,
    URL_CJ,
    URL_DISCONTINUED,
    URL_GENI,
    URL_GO,
    URL_HEALTHY_NET,
    URL_HOME_HOP,
    URL_NO_TAG,
    URL_OOS,
    URL_REGION,
    URL_TAG_STRIP,
    SampleNet,
)
from zill.urls import canonical


EXPECTED = {
    canonical(URL_HEALTHY_NET): set(),
    canonical(URL_GO): set(),
    canonical(URL_BROKEN): {"broken"},
    canonical(URL_OOS): {"out_of_stock"},
    canonical(URL_DISCONTINUED): {"discontinued"},
    canonical(URL_HOME_HOP): {"homepage_redirect"},
    canonical(URL_TAG_STRIP): {"tracking_lost"},
    canonical(URL_NO_TAG): {"missing_attribution"},
    canonical(URL_CJ): {"network_failure"},
    canonical(URL_GENI): {"network_failure"},
    canonical(URL_REGION): {"region_unavailable"},
}


def test_sample_audit_finds_revenue_leaks():
    net = SampleNet()
    report = asyncio.run(audit_site(SAMPLE_START, fetcher=net, respect_robots=False))
    assert report.crawl_error is None
    assert report.problem_count == 9
    assert report.healthy_count == 2
    found = {finding.url: {issue.code for issue in finding.issues} for finding in report.findings}
    assert found == EXPECTED
    broken = next(finding for finding in report.findings if finding.url == canonical(URL_BROKEN))
    assert len(broken.sources) == 2
    requested = " ".join(net.requested)
    assert "twitter.com" not in requested
    assert "w3.org" not in requested
    assert "https://www.amazon.com/" not in net.requested


def test_timeout_is_unverified_not_a_problem():
    from zill.audit import bucket_for

    assert bucket_for(["timeout"]) == "unverified"
    assert bucket_for(["blocked"]) == "unverified"
    assert bucket_for(["broken"]) == "problem"
    assert bucket_for([]) == "healthy"


def test_timeouts_are_retried_before_being_reported():
    from zill.fetch import HttpxFetcher

    class Flaky:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("slow")
            return httpx.Response(200, text="<html>ok</html>", request=httpx.Request("GET", url))

    flaky = Flaky()
    fetcher = HttpxFetcher(client=flaky)
    fetcher._host_safety["shop.example"] = ("ok", None)
    result = asyncio.run(fetcher.get("https://shop.example/p"))
    assert flaky.calls == 2
    assert result.error is None
    assert result.status_code == 200


def test_pages_refused_once_are_retried_not_dropped():
    class Flaky(SampleNet):
        """Refuses every page once, the way intermittent bot protection does."""

        def __init__(self):
            super().__init__()
            self.refused: set[str] = set()

        async def get(self, url: str) -> FetchResult:
            if url.startswith("https://publisher.example/") and url not in self.refused:
                self.refused.add(url)
                if url != canonical(SAMPLE_START):
                    return FetchResult(
                        requested_url=url, final_url=url, status_code=403,
                        text="<html>denied</html>", content_type="text/html",
                        redirect_chain=[url],
                    )
            return await super().get(url)

    report = asyncio.run(audit_site(SAMPLE_START, fetcher=Flaky(), max_pages=10))
    assert report.pages_crawled == 4
    assert report.pages_blocked == 0
    assert report.affiliate_links_found == 11


def test_bot_wall_explains_why_the_crawl_stopped():
    class Blocked:
        async def allowed(self, url: str) -> bool:
            return True

        async def get(self, url: str) -> FetchResult:
            return FetchResult(
                requested_url=url,
                final_url=url,
                status_code=403,
                text="<html><p>Please enable JS and disable any ad blocker</p></html>",
                content_type="text/html",
                redirect_chain=[url],
            )

    report = asyncio.run(audit_site("https://publisher.example/wirecutter", fetcher=Blocked()))
    assert report.pages_crawled == 0
    assert report.crawl_error is not None
    assert "blocked the automated crawl" in report.crawl_error
    assert "HTTP 403" in report.crawl_error


def test_max_pages_stops_before_reviews():
    net = SampleNet()
    report = asyncio.run(audit_site(SAMPLE_START, fetcher=net, max_pages=1))
    assert report.pages_crawled == 1
    assert report.affiliate_links_found == 0
    assert all("/reviews/" not in url for url in net.requested)


def test_api_sample_and_rejects_loopback():
    client = TestClient(app)
    denied = client.post("/api/audits", json={"url": "http://127.0.0.1/"})
    assert denied.status_code == 400

    started = client.post("/api/audits", json={"sample": True, "max_pages": 10})
    assert started.status_code == 200
    job_id = started.json()["id"]
    job = client.get(f"/api/audits/{job_id}").json()
    for _ in range(40):
        if job["status"] in {"done", "error"}:
            break
        job = client.get(f"/api/audits/{job_id}").json()
    assert job["status"] == "done"
    assert job["report"]["problem_count"] == 9
    assert job["report"]["site_title"] == "Fieldnote"

    home = client.get("/")
    assert home.status_code == 200
    assert "Find affiliate revenue you're losing" in home.text
