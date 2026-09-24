from __future__ import annotations

from zill.fetch import FetchResult
from zill.urls import canonical

SAMPLE_START = "https://publisher.example/"
URL_HEALTHY_NET = "https://shareasale.com/r.cfm?b=1&u=9&m=2&urllink=lamp"
URL_LAMP = "https://shop.example/products/lamp"
URL_BROKEN = "https://www.amazon.com/dp/B0DEAD4041?tag=fieldnote-20"
URL_OOS = "https://www.amazon.com/dp/B0OUTOFSTK?tag=fieldnote-20"
URL_DISCONTINUED = "https://www.amazon.com/dp/B0DISCONT1?tag=fieldnote-20"
URL_HOME_HOP = "https://sjv.io/c/fieldnote/lamp"
URL_SHOP_HOME = "https://shop.example/"
URL_TAG_STRIP = "https://www.amazon.com/dp/B0TAGSTRP1?tag=fieldnote-20"
URL_TAG_STRIP_FINAL = "https://www.amazon.com/dp/B0TAGSTRP1"
URL_GO = "https://publisher.example/go/lamp"
URL_HEALTHY_AMAZON = "https://www.amazon.com/dp/B0HEALTHYL?tag=fieldnote-20"
URL_NO_TAG = "https://www.amazon.com/dp/B0NOTAGCH1"
URL_CJ = "https://www.anrdoezrs.net/click-fieldnote-99"
URL_GENI = "https://geni.us/fieldnote-lamp"
URL_REGION = "https://www.amazon.com/dp/B0REGION01?tag=fieldnote-20"
URL_DESK = "https://publisher.example/reviews/desk"
URL_KITCHEN = "https://publisher.example/reviews/kitchen"
URL_ABOUT = "https://publisher.example/about"


def _html(title: str, body: str) -> str:
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"


def _product(name: str, availability: str) -> str:
    return _html(
        name,
        (
            "<script type=\"application/ld+json\">"
            '{"@context":"https://schema.org","@type":"Product","name":"'
            + name
            + '","offers":{"@type":"Offer","availability":"https://schema.org/'
            + availability
            + '"}}</script><p>'
            + name
            + "</p>"
        ),
    )


def _page(href: str, text: str) -> str:
    return f'<p><a href="{href}">{text}</a></p>'


PAGES: dict[str, tuple[int, str]] = {
    canonical(SAMPLE_START): (
        200,
        _html(
            "Fieldnote",
            "".join(
                [
                    _page(URL_DESK, "Desk setups"),
                    _page(URL_KITCHEN, "Kitchen gear"),
                    _page(URL_ABOUT, "About"),
                    '<p><a rel="nofollow" href="https://twitter.com/fieldnote">Twitter</a></p>',
                ]
            ),
        ),
    ),
    canonical(URL_DESK): (
        200,
        _html(
            "Desk setups",
            "".join(
                [
                    _page(URL_HEALTHY_NET, "Oak desk lamp"),
                    _page(URL_BROKEN, "Missing kettle"),
                    _page(URL_OOS, "Ceramic mug"),
                    _page(URL_DISCONTINUED, "Retired radio"),
                    _page(URL_HOME_HOP, "Shop the store"),
                    _page(URL_TAG_STRIP, "Brass speaker"),
                    _page(URL_GO, "Fieldnote lamp pick"),
                ]
            ),
        ),
    ),
    canonical(URL_KITCHEN): (
        200,
        _html(
            "Kitchen gear",
            "".join(
                [
                    _page(URL_NO_TAG, "Untracked chair"),
                    _page(URL_CJ, "Network kettle"),
                    _page(URL_GENI, "Short link blender"),
                    _page(URL_REGION, "Region-locked pan"),
                    _page(URL_BROKEN, "Missing kettle"),
                ]
            ),
        ),
    ),
    canonical(URL_ABOUT): (
        200,
        _html(
            "About Fieldnote",
            '<p><a href="https://www.w3.org/">W3C</a></p><p><a href="https://www.amazon.com/">Amazon</a></p>',
        ),
    ),
    canonical(URL_LAMP): (200, _product("Oak desk lamp", "InStock")),
    canonical(URL_HEALTHY_AMAZON): (200, _product("Fieldnote lamp", "InStock")),
    canonical(URL_TAG_STRIP_FINAL): (200, _product("Brass speaker", "InStock")),
    canonical(URL_NO_TAG): (200, _product("Untracked chair", "InStock")),
    canonical(URL_OOS): (200, _product("Ceramic mug", "OutOfStock")),
    canonical(URL_DISCONTINUED): (200, _product("Retired radio", "Discontinued")),
    canonical(URL_BROKEN): (404, _html("Page Not Found", "<h1>Page Not Found</h1>")),
    canonical(URL_CJ): (500, _html("Error", "<p>Network error</p>")),
    canonical(URL_SHOP_HOME): (200, _html("Shop home", "<h1>Welcome</h1><p>Browse the catalog.</p>")),
    canonical(URL_REGION): (
        200,
        _html("Region-locked pan", "<p>This product is not available in your country.</p>"),
    ),
}

REDIRECTS = {
    canonical(URL_HEALTHY_NET): canonical(URL_LAMP),
    canonical(URL_HOME_HOP): canonical(URL_SHOP_HOME),
    canonical(URL_TAG_STRIP): canonical(URL_TAG_STRIP_FINAL),
    canonical(URL_GO): canonical(URL_HEALTHY_AMAZON),
}
DNS_URLS = {canonical(URL_GENI)}


class SampleNet:
    """In-process site used to demo the report without crawling the public web."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    async def allowed(self, url: str) -> bool:
        return True

    async def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        current = canonical(url)
        chain: list[str] = []
        seen: set[str] = set()
        for _ in range(8):
            if current in seen:
                return FetchResult(requested_url=url, redirect_chain=chain, error="too_many_redirects")
            seen.add(current)
            if current in REDIRECTS:
                chain.append(current)
                current = REDIRECTS[current]
                continue
            chain.append(current)
            if current in DNS_URLS:
                return FetchResult(requested_url=url, final_url=None, redirect_chain=chain, error="dns")
            page = PAGES.get(current)
            if page is None:
                return FetchResult(requested_url=url, final_url=current, redirect_chain=chain, error="dns")
            status, body = page
            return FetchResult(
                requested_url=url,
                final_url=current,
                status_code=status,
                text=body,
                content_type="text/html; charset=utf-8",
                redirect_chain=chain,
                error=None,
            )
        return FetchResult(requested_url=url, redirect_chain=chain, error="too_many_redirects")
