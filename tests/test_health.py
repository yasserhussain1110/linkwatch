from zill.fetch import FetchResult
from zill.health import diagnose


def codes(url: str, **kwargs) -> set[str]:
    fetch = FetchResult(requested_url=url, final_url=kwargs.pop("final_url", url), **kwargs)
    return {issue.code for issue in diagnose(url, fetch)}


INSTOCK = '<html><title>Lamp</title><script type="application/ld+json">{"availability":"https://schema.org/InStock"}</script></html>'


def test_schema_out_of_stock_and_ignores_prose():
    html = '<html><script type="application/ld+json">{"availability":"https://schema.org/OutOfStock"}</script></html>'
    assert codes("https://shop.example/mug", status_code=200, text=html) == {"out_of_stock"}
    prose = "<html><title>Review</title><p>It was out of stock last year.</p></html>"
    assert codes("https://shop.example/mug", status_code=200, text=prose) == set()


def test_class_marks_out_of_stock():
    html = '<div class="product out-of-stock">Waiting</div>'
    assert "out_of_stock" in codes("https://shop.example/mug", status_code=200, text=html)


def test_tracking_and_destination_rules():
    tagged = "https://www.amazon.com/dp/B0TAGSTRP1?tag=fieldnote-20"
    stripped = "https://www.amazon.com/dp/B0TAGSTRP1"
    assert codes(tagged, final_url=stripped, status_code=200, text=INSTOCK, redirect_chain=[tagged, stripped]) == {"tracking_lost"}

    start = "https://www.amazon.com/dp/B0AAAAAAAA?tag=x-20"
    final = "https://www.amazon.com/dp/B0BBBBBBBB?tag=x-20"
    found = codes(start, final_url=final, status_code=200, text=INSTOCK, redirect_chain=[start, final])
    assert found == {"wrong_product"}

    bare = "https://www.amazon.com/dp/B0NOTAGCH1"
    assert codes(bare, status_code=200, text=INSTOCK) == {"missing_attribution"}
    assert "broken" in codes(bare, status_code=404, text="missing")

    network = "https://shareasale.com/r.cfm?b=1&u=2&m=3"
    product = "https://shop.example/products/lamp"
    assert codes(network, final_url=product, status_code=200, text=INSTOCK, redirect_chain=[network, product]) == set()

    home = "https://sjv.io/c/fieldnote/lamp"
    assert codes(home, final_url="https://shop.example/", status_code=200, text="<title>Home</title>", redirect_chain=[home, "https://shop.example/"]) == {"homepage_redirect"}

    search = "https://www.amazon.com/dp/B0DEAD4041?tag=fieldnote-20"
    landed = "https://www.amazon.com/s?k=lamp"
    assert "homepage_redirect" in codes(search, final_url=landed, status_code=200, text="<title>Search</title>", redirect_chain=[search, landed])


def test_blocked_is_not_a_broken_link():
    assert codes("https://shop.example/p", status_code=403, text="nope") == {"blocked"}


def test_bot_challenge_answered_with_200_is_not_healthy():
    wall = "<html><title>Amazon.com</title><p>Enter the characters you see below</p></html>"
    assert codes("https://www.amazon.com/dp/B00X5ILD0K?tag=x-20", status_code=200, text=wall) == {"blocked"}


def test_region_phrase():
    html = "<html><title>Pan</title><p>This product is not available in your country.</p></html>"
    assert codes("https://www.amazon.com/dp/B0REGION01?tag=fieldnote-20", status_code=200, text=html) == {"region_unavailable"}
