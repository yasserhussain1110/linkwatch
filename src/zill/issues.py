from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IssueInfo:
    code: str
    title: str
    action: str


ISSUES: dict[str, IssueInfo] = {
    "broken": IssueInfo(
        "broken",
        "Dead link",
        "Replace it with a live product link, or remove it.",
    ),
    "unreachable": IssueInfo(
        "unreachable",
        "Link doesn't resolve",
        "The domain doesn't resolve. Replace the link.",
    ),
    "timeout": IssueInfo(
        "timeout",
        "Timed out",
        "The destination didn't respond. Check it in a browser before you replace it.",
    ),
    "server_error": IssueInfo(
        "server_error",
        "Server error",
        "The product page is erroring. Recheck it before you send more traffic.",
    ),
    "network_failure": IssueInfo(
        "network_failure",
        "Tracking failed",
        "Rebuild this link from your affiliate dashboard.",
    ),
    "discontinued": IssueInfo(
        "discontinued",
        "Discontinued",
        "This product won't come back. Replace it.",
    ),
    "out_of_stock": IssueInfo(
        "out_of_stock",
        "Out of stock",
        "Point the review at an in-stock alternative, or check the offer again.",
    ),
    "region_unavailable": IssueInfo(
        "region_unavailable",
        "Wrong region",
        "Shoppers in this region can't buy it. Confirm the offer you meant to promote.",
    ),
    "soft_not_found": IssueInfo(
        "soft_not_found",
        "Missing product",
        "The merchant kept a URL, but the product is gone. Replace the link.",
    ),
    "wrong_product": IssueInfo(
        "wrong_product",
        "Wrong product",
        "The link now lands on a different product than the one you picked.",
    ),
    "homepage_redirect": IssueInfo(
        "homepage_redirect",
        "Lands on homepage",
        "Deep-link to a specific product instead of the store homepage or a search page.",
    ),
    "tracking_lost": IssueInfo(
        "tracking_lost",
        "Tag stripped",
        "Put your affiliate tag back on the final product URL.",
    ),
    "missing_attribution": IssueInfo(
        "missing_attribution",
        "No affiliate tag",
        "Add your affiliate tag so the sale is credited to you.",
    ),
    "blocked": IssueInfo(
        "blocked",
        "Couldn't verify",
        "Open the link in a browser. The site blocked an automated check.",
    ),
}

SEVERITY: list[str] = list(ISSUES)


@dataclass(frozen=True)
class IssueHit:
    code: str
    title: str
    summary: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "title": self.title,
            "summary": self.summary,
            "action": self.action,
        }


def hit(code: str, summary: str) -> IssueHit:
    info = ISSUES[code]
    return IssueHit(code=code, title=info.title, summary=summary, action=info.action)
