import asyncio

from fastapi.testclient import TestClient

from linkwatch.app import app
from linkwatch.audit import audit_site
from linkwatch.pdfreport import render_pdf
from linkwatch.sample import SAMPLE_START, SampleNet


def test_sample_report_becomes_a_multi_page_pdf():
    report = asyncio.run(audit_site(SAMPLE_START, fetcher=SampleNet(), max_pages=10))
    payload = render_pdf(report.to_dict())
    assert payload.startswith(b"%PDF")
    # A designed report of 11 findings is more than a one-page stub.
    assert len(payload) > 8_000
    text = _text(payload)
    assert "Fieldnote" in text
    assert "Failing to earn" in text
    assert "Dead link" in text
    assert "Missing kettle" in text
    assert "Replace it with a live product link" in text
    assert "Pages crawled" in text


def test_export_endpoint_returns_the_pdf():
    report = asyncio.run(audit_site(SAMPLE_START, fetcher=SampleNet(), max_pages=10)).to_dict()
    with TestClient(app) as client:
        response = client.post("/api/report.pdf", json=report)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "linkwatch-publisher.example.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    assert "Fieldnote" in _text(response.content)


def _text(payload: bytes) -> str:
    import subprocess

    result = subprocess.run(
        ["pdftotext", "-", "-"],
        input=payload,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode()
