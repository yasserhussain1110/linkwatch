from zill.classify import classify_kind
from zill.urls import canonical


PAGE = "https://publisher.example/reviews/desk"


def test_ignores_plain_external_and_amazon_home():
    assert classify_kind(PAGE, "https://twitter.com/fieldnote", "nofollow") is None
    assert classify_kind(PAGE, "https://www.amazon.com/", "") is None


def test_detects_affiliate_shapes():
    assert classify_kind(PAGE, "https://www.amazon.com/dp/B0DEAD4041?tag=fieldnote-20", "") == "amazon"
    assert classify_kind(PAGE, "https://www.amazon.com/dp/B0NOTAGCH1", "") == "amazon"
    assert classify_kind(PAGE, "https://shareasale.com/r.cfm?b=1", "") == "network"
    assert classify_kind(PAGE, "https://shop.example/p/1?irclickid=abc", "") == "tagged"
    assert classify_kind(PAGE, "https://publisher.example/go/lamp", "") == "redirector"
    assert classify_kind(PAGE, "https://publisher.example/wirecutter/out/deals/256782?merchant=Amazon", "") == "redirector"
    assert classify_kind(PAGE, "https://publisher.example/reviews/go", "") is None
    assert classify_kind(PAGE, "https://other.example/go/lamp", "") is None
    assert classify_kind(PAGE, "https://merchant.example/product", "sponsored nofollow") == "sponsored"


def test_canonical_strips_fragment_but_keeps_trailing_slash():
    assert canonical("https://Publisher.Example/reviews/desk#buy") == "https://publisher.example/reviews/desk"
    assert canonical("https://publisher.example") == "https://publisher.example/"
    # Impact's tracker 404s without the trailing slash.
    assert canonical("https://www.ojrq.net/p/?return=x") == "https://www.ojrq.net/p/?return=x"
