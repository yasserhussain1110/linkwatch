import socket

from zill.fetch import assess


def _resolver(ip: str):
    def resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return resolve


def test_blocks_loopback_and_metadata_and_allows_public():
    assert assess("http://127.0.0.1/")[0] == "denied"
    assert assess("http://169.254.169.254/latest")[0] == "denied"
    assert assess("https://localhost/admin")[0] == "denied"
    assert assess("https://evil.example/path", resolver=_resolver("127.0.0.1"))[0] == "denied"
    assert assess("https://example.com/", resolver=_resolver("1.1.1.1"))[0] == "ok"


def test_dns_failure():
    def resolve(host, port, *args, **kwargs):
        raise socket.gaierror("fail")

    assert assess("https://missing.example/", resolver=resolve)[0] == "dns"
