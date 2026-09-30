from linkwatch.browser import _chain


class FakeRequest:
    def __init__(self, url, redirected_from=None):
        self.url = url
        self.redirected_from = redirected_from


class FakeResponse:
    def __init__(self, request):
        self.request = request


def test_redirect_chain_is_read_in_visiting_order():
    first = FakeRequest("https://www.nytimes.com/wirecutter/out/deals/1")
    second = FakeRequest("https://wclink.co/deals/1", redirected_from=first)
    last = FakeRequest("https://www.amazon.com/dp/B0TEST1234", redirected_from=second)
    assert _chain(FakeResponse(last), first.url) == [
        "https://www.nytimes.com/wirecutter/out/deals/1",
        "https://wclink.co/deals/1",
        "https://www.amazon.com/dp/B0TEST1234",
    ]
