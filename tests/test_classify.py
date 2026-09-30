from linkwatch.classify import classify_kind, extract_page_links
from linkwatch.urls import canonical, in_scope


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


def test_detects_cart_platform_and_travel_agent_links():
    assert classify_kind(PAGE, "https://groovepages.groovesell.com/a/5jM0qRHcm64r", "") == "network"
    assert classify_kind(PAGE, "https://tvallc.isrefer.com/go/hpg/usa1000/", "") == "network"
    assert classify_kind(PAGE, "https://usa1000--page1.thrivecart.com/designrr-offer/", "") == "network"
    assert classify_kind(PAGE, "https://warriorplus.com/o2/a/g454qp/0", "") == "network"
    # Travel suppliers credit the booking to an agent, not an affiliate id.
    assert classify_kind(PAGE, "https://www.virginvoyages.com/book/find?agentId=130423", "") == "tagged"


def test_shorteners_and_redirector_subdomains_are_followed():
    assert classify_kind(PAGE, "http://bit.ly/2R330w8", "") == "shortener"
    assert classify_kind(PAGE, "https://zdcs.link/avX4b?el=Airbnb", "") == "shortener"
    assert classify_kind(PAGE, "https://visit.usa1000.com/2900", "") == "redirector"
    assert classify_kind(PAGE, "https://trk.realestateexpress.com/?a=14923", "") == "redirector"
    # A merchant's own www host is not a redirector.
    assert classify_kind(PAGE, "https://www.example.com/product", "") is None


def test_bare_affiliate_id_in_the_query_counts():
    # Seen as ?aff65616 with no value at all, so parse_qs yields it as the key.
    assert classify_kind(PAGE, "https://50kloans.com/?aff65616", "") == "tagged"
    assert classify_kind(PAGE, "https://lowcreditfinance.com/?aff65627", "") == "tagged"


def test_untagged_amazon_landing_page_is_still_worth_checking():
    # No ASIN and no tag, so the old rule ignored it — but it earns nothing.
    assert classify_kind(PAGE, "https://www.amazon.com/primebigdealdays?ref=CG_ac", "") == "amazon"
    # A plain mention of the store front door is still not an affiliate link.
    assert classify_kind(PAGE, "https://www.amazon.com/", "") is None


def test_section_start_url_stays_inside_the_section():
    start = "https://www.nytimes.com/wirecutter/"
    assert in_scope(start, "https://www.nytimes.com/wirecutter/reviews/best-coffee-tables/")
    assert not in_scope(start, "https://help.nytimes.com/policies/115014893428-Terms-of-Service")
    assert not in_scope(start, "https://www.nytimes.com/account")
    assert not in_scope(start, "https://www.nytimes.com/wirecutterfoo")
    # A bare domain still crawls the whole site.
    assert in_scope("https://publisher.example/", "https://publisher.example/reviews/desk")


def test_canonical_strips_fragment_but_keeps_trailing_slash():
    assert canonical("https://Publisher.Example/reviews/desk#buy") == "https://publisher.example/reviews/desk"
    assert canonical("https://publisher.example") == "https://publisher.example/"
    # Impact's tracker 404s without the trailing slash.
    assert canonical("https://www.ojrq.net/p/?return=x") == "https://www.ojrq.net/p/?return=x"


def test_a_typo_doubled_scheme_does_not_end_the_crawl():
    # Seen in a real site footer: the second "https:" parses as a port.
    assert canonical("https://https:usa1000.com/contact-us") == "https://https/contact-us"
    page = "https://usa1000.net/footer-1"
    html = '<a href="https://https:usa1000.com/contact-us">Contact Us</a><a href="/next">Next</a>'
    links = extract_page_links(page, html, "https://usa1000.net/")
    assert links.crawl == ["https://usa1000.net/next"]
