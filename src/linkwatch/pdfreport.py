"""A designed PDF of an audit, matching the report on screen."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

INK = (28, 25, 21)
PAPER = (243, 239, 230)
CARD = (255, 253, 248)
CREAM = (247, 243, 234)
MUTED = (94, 88, 78)
LINE = (221, 212, 196)
BAD = (141, 43, 36)
BAD_BG = (246, 230, 225)
OK = (29, 107, 67)
OK_BG = (228, 242, 233)
WARN = (122, 84, 24)
WARN_BG = (247, 236, 214)

BUCKETS = (
    ("problem", "Failing to earn", BAD, BAD_BG),
    ("unverified", "Couldn't verify", WARN, WARN_BG),
    ("healthy", "Still healthy", OK, OK_BG),
)


class ReportPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4", unit="mm")
        self.add_font("Serif", "", str(FONT_DIR / "DejaVuSerif.ttf"))
        self.add_font("Serif", "B", str(FONT_DIR / "DejaVuSerif-Bold.ttf"))
        self.add_font("Sans", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("Sans", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(16, 16, 16)
        self.alias_nb_pages()

    def header(self) -> None:
        self.set_fill_color(*PAPER)
        self.rect(0, 0, self.w, self.h, "F")

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Sans", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"Linkwatch  ·  {self.page_no()} / {{nb}}", align="C")


def _clean(value: object) -> str:
    text = str(value or "")
    return " ".join(text.replace("\ufeff", "").replace("\u200b", "").split())


def render_pdf(report: dict) -> bytes:
    pdf = ReportPDF()
    pdf.add_page()
    _hero(pdf, report)
    _stats(pdf, report)
    _issue_breakdown(pdf, report)
    for bucket, title, ink, wash in BUCKETS:
        findings = [item for item in report.get("findings") or [] if item.get("bucket") == bucket]
        if findings:
            _section(pdf, title, len(findings), ink)
            for finding in findings:
                _finding(pdf, finding, ink, wash)
    pages = report.get("pages") or []
    if pages:
        _section(pdf, "Pages crawled", len(pages), INK)
        pdf.set_font("Sans", "", 8)
        pdf.set_text_color(*MUTED)
        for page in pages:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 4.2, str(page), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())


def _hero(pdf: ReportPDF, report: dict) -> None:
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, pdf.w, 34, "F")
    pdf.set_xy(16, 8)
    pdf.set_font("Sans", "B", 9)
    pdf.set_text_color(*CREAM)
    pdf.cell(0, 5, "LINKWATCH", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(16)
    pdf.set_font("Serif", "", 13)
    pdf.cell(0, 7, "Affiliate revenue at risk", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(42)
    title = _clean(report.get("site_title") or report.get("site") or "Audit")
    pdf.set_font("Serif", "B", 20)
    pdf.set_text_color(*INK)
    pdf.multi_cell(pdf.epw, 9, str(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Sans", "", 9)
    pdf.set_text_color(*MUTED)
    meta = str(report.get("site") or "")
    when = report.get("crawled_at") or ""
    if when:
        meta = f"{meta}    ·    {when}"
    if report.get("sample"):
        meta += "    ·    sample publisher"
    pdf.multi_cell(pdf.epw, 5, meta, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    count = int(report.get("problem_count") or 0)
    pdf.set_font("Serif", "B", 36)
    pdf.set_text_color(*(BAD if count else OK))
    pdf.cell(pdf.get_string_width(str(count)) + 2, 14, str(count), new_x=XPos.RIGHT, new_y=YPos.LAST)
    pdf.set_font("Serif", "", 12)
    pdf.set_text_color(*INK)
    label = "link looks like it's failing to earn" if count == 1 else "links look like they're failing to earn"
    pdf.set_xy(pdf.get_x() + 2, pdf.get_y() + 4)
    pdf.cell(0, 8, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    caveat = report.get("caveat") or ""
    if caveat:
        _note(pdf, caveat)
    error = report.get("crawl_error")
    if error:
        _note(pdf, str(error))


def _note(pdf: ReportPDF, text: str) -> None:
    pdf.ln(1)
    y = pdf.get_y()
    pdf.set_font("Sans", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.set_x(pdf.l_margin + 3)
    pdf.multi_cell(pdf.epw - 6, 4.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    bottom = pdf.get_y() + 2
    pdf.set_draw_color(*LINE)
    pdf.set_fill_color(*CARD)
    pdf.rect(pdf.l_margin, y - 1, pdf.epw, bottom - y, "D")
    pdf.set_y(bottom + 2)


def _stats(pdf: ReportPDF, report: dict) -> None:
    blocked = int(report.get("pages_blocked") or 0)
    pages_label = "Pages crawled" if not blocked else f"{blocked} refused"
    cells = [
        (str(report.get("pages_crawled") or 0), pages_label),
        (str(report.get("affiliate_links_found") or 0), "Affiliate links"),
        (str(report.get("healthy_count") or 0), "Healthy"),
        (str(report.get("unverified_count") or 0), "Couldn't verify"),
    ]
    if report.get("truncated"):
        cells[1] = (f"{report.get('links_checked')} of {report.get('affiliate_links_found')}", "Links checked")
    gap = 3
    width = (pdf.epw - gap * (len(cells) - 1)) / len(cells)
    y = pdf.get_y()
    x = pdf.l_margin
    for value, label in cells:
        pdf.set_fill_color(*CARD)
        pdf.set_draw_color(*LINE)
        pdf.rect(x, y, width, 18, "FD")
        pdf.set_xy(x + 2, y + 2)
        pdf.set_font("Serif", "B", 13)
        pdf.set_text_color(*INK)
        pdf.cell(width - 4, 7, value, new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.set_x(x + 2)
        pdf.set_font("Sans", "", 7.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(width - 4, 5, label)
        x += width + gap
    pdf.set_y(y + 22)


def _issue_breakdown(pdf: ReportPDF, report: dict) -> None:
    counts: dict = report.get("issue_counts") or {}
    if not counts:
        return
    titles = {}
    for finding in report.get("findings") or []:
        for issue in finding.get("issues") or []:
            titles.setdefault(issue.get("code"), issue.get("title") or issue.get("code"))
    pdf.set_font("Sans", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "WHERE THE REVENUE LEAKS", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    x = pdf.l_margin
    y = pdf.get_y()
    for code, count in counts.items():
        label = f"{titles.get(code, code)}  {count}"
        pdf.set_font("Sans", "B", 8)
        width = pdf.get_string_width(label) + 6
        if x + width > pdf.w - pdf.r_margin:
            x = pdf.l_margin
            y += 8
        pdf.set_fill_color(*BAD_BG)
        pdf.set_text_color(*BAD)
        pdf.set_xy(x, y)
        pdf.cell(width, 6, label, fill=True, align="C")
        x += width + 2
    pdf.set_y(y + 10)


def _section(pdf: ReportPDF, title: str, count: int, ink: tuple[int, int, int]) -> None:
    pdf.ln(2)
    if pdf.get_y() > pdf.page_break_trigger - 24:
        pdf.add_page()
    pdf.set_font("Serif", "B", 15)
    pdf.set_text_color(*ink)
    title_width = pdf.get_string_width(title) + 2
    pdf.cell(title_width, 8, title, new_x=XPos.RIGHT, new_y=YPos.LAST)
    pdf.set_font("Sans", "", 11)
    pdf.set_text_color(*MUTED)
    pdf.cell(pdf.epw - title_width, 8, str(count), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*LINE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)


def _finding(pdf: ReportPDF, finding: dict, ink: tuple[int, int, int], wash: tuple[int, int, int]) -> None:
    y0 = pdf.get_y()
    with pdf.offset_rendering() as probe:
        _finding_body(probe, finding, ink, wash, y0)
        height = probe.y - y0
    if probe.page_break_triggered or y0 + height > pdf.page_break_trigger:
        pdf.add_page()
        y0 = pdf.get_y()
    pdf.set_fill_color(*CARD)
    pdf.set_draw_color(*LINE)
    pdf.rect(pdf.l_margin, y0, pdf.epw, max(height, 8), "FD")
    pdf.set_fill_color(*ink)
    pdf.rect(pdf.l_margin, y0, 1.8, max(height, 8), "F")
    _finding_body(pdf, finding, ink, wash, y0)
    pdf.ln(3)


def _finding_body(pdf, finding: dict, ink: tuple[int, int, int], wash: tuple[int, int, int], y0: float) -> None:
    pdf.set_xy(pdf.l_margin + 5, y0 + 3)
    issues = finding.get("issues") or []
    labels = [issue.get("title") or issue.get("code") or "Issue" for issue in issues] or ["Healthy"]
    pill_wash = wash if issues else OK_BG
    pill_ink = ink if issues else OK
    for label in labels:
        pdf.set_font("Sans", "B", 7.5)
        width = pdf.get_string_width(label) + 5
        if pdf.get_x() + width > pdf.w - pdf.r_margin:
            pdf.ln(6)
            pdf.set_x(pdf.l_margin + 5)
        pdf.set_fill_color(*pill_wash)
        pdf.set_text_color(*pill_ink)
        pdf.cell(width, 5, label, fill=True, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_x(pdf.get_x() + 1.5)
    pdf.ln(7)
    pdf.set_x(pdf.l_margin + 5)
    heading = _clean(finding.get("anchor")) or _clean(finding.get("url")) or "Untitled link"
    pdf.set_font("Serif", "B", 12)
    pdf.set_text_color(*INK)
    pdf.multi_cell(pdf.epw - 10, 6, str(heading), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _muted_line(pdf, _clean(finding.get("url")))
    final = finding.get("final_url")
    if final and final != finding.get("url"):
        _muted_line(pdf, "Lands on  " + _clean(final))
    status = finding.get("status_code")
    kind = finding.get("kind")
    bits = []
    if kind:
        bits.append(str(kind))
    if status:
        bits.append(f"HTTP {status}")
    if bits:
        _muted_line(pdf, "  ·  ".join(bits))
    for issue in issues:
        pdf.ln(1)
        pdf.set_x(pdf.l_margin + 5)
        pdf.set_font("Sans", "", 9)
        pdf.set_text_color(*INK)
        pdf.multi_cell(pdf.epw - 10, 4.5, _clean(issue.get("summary")), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        action = issue.get("action")
        if action:
            pdf.set_x(pdf.l_margin + 5)
            pdf.set_font("Sans", "B", 9)
            pdf.set_text_color(*ink)
            pdf.multi_cell(pdf.epw - 10, 4.5, "Next: " + _clean(action), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    sources = finding.get("sources") or []
    if sources:
        pdf.ln(0.5)
        _muted_line(pdf, "Found on  " + ", ".join(_clean(source) for source in sources))
    pdf.ln(2)


def _muted_line(pdf, text: str) -> None:
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font("Sans", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(pdf.epw - 10, 4, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
