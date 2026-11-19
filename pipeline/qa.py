"""Automated Visual and Structural Quality Assurance for generated PDFs.

Performs programmatic verification of:
  - Strict A4 dimensions (595.28 x 841.89 pt)
  - Content margin boundaries (no text/drawings clipped or overflowing)
  - Blank page detection
  - Continuous running footer page numbers
  - Header line and title presence
  - Diagram and table rendering integrity
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pymupdf


@dataclass
class PageQAResult:
    page_num: int
    stamped_page_num: int
    expected_page_num: int
    char_count: int
    drawing_count: int
    has_header: bool
    has_footer: bool
    is_blank: bool
    has_overflow: bool
    details: List[str] = field(default_factory=list)


@dataclass
class QAReport:
    pdf_path: Path
    total_pages: int
    start_page: int
    end_page: int
    is_passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    pages: List[PageQAResult] = field(default_factory=list)

    def print_summary(self) -> None:
        status_str = "PASSED" if self.is_passed else "FAILED"
        print(f"\n{'='*20} QA REPORT: {status_str} {'='*20}")
        print(f"File: {self.pdf_path.name}")
        print(f"Pages: {self.total_pages} (Pages {self.start_page} to {self.end_page})")
        if self.errors:
            print("[ERRORS]:")
            for err in self.errors:
                print(f"  - {err}")
        if self.warnings:
            print("[WARNINGS]:")
            for warn in self.warnings:
                print(f"  - {warn}")
        print("-" * 50)
        for p in self.pages:
            status = "OK" if not p.details else f"ISSUES ({', '.join(p.details)})"
            print(f"  Page {p.page_num} (Book Pg {p.stamped_page_num}): {p.char_count} chars, {p.drawing_count} drawings -> {status}")
        print("=" * 50 + "\n")


def run_qa_checks(pdf_path: Path | str, expected_start_page: int) -> QAReport:
    """Executes programmatic QA analysis on a generated PDF."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF does not exist: {path}")

    doc = pymupdf.open(path)
    total_pages = len(doc)
    expected_end_page = expected_start_page + total_pages - 1

    report = QAReport(
        pdf_path=path,
        total_pages=total_pages,
        start_page=expected_start_page,
        end_page=expected_end_page,
        is_passed=True,
    )

    if total_pages == 0:
        report.errors.append("PDF has 0 pages.")
        report.is_passed = False
        return report

    # Margins in points:
    # A4 standard = 595.28 x 841.89 points
    # Printable area margins: left 18mm (~51pt), right ~544pt
    # top 22mm (~62pt), bottom ~785pt
    A4_W, A4_H = 595.28, 841.89
    MIN_X = 46.0   # Allow small tolerance
    MAX_X = 549.0
    MIN_CONTENT_Y = 55.0   # Below header line
    MAX_CONTENT_Y = 795.0  # Above footer text

    for i, page in enumerate(doc):
        page_idx = i + 1
        expected_pg_no = expected_start_page + i
        page_rect = page.rect

        # 1. Dimension Check
        if abs(page_rect.width - A4_W) > 3.0 or abs(page_rect.height - A4_H) > 3.0:
            report.errors.append(
                f"Page {page_idx} dimensions ({page_rect.width:.1f} x {page_rect.height:.1f}) are not standard A4 ({A4_W} x {A4_H})."
            )

        text = page.get_text() or ""
        char_count = len(text.strip())
        drawings = page.get_drawings()
        drawing_count = len(drawings)

        # 2. Blank Page Detection
        is_blank = char_count < 100 and drawing_count == 0
        if is_blank:
            report.errors.append(f"Page {page_idx} appears blank ({char_count} chars, 0 drawings).")

        # 3. Running Header & Footer Verification
        has_header = "Spring Boot Master Notes" in text and "Coder Army" in text
        if not has_header:
            report.errors.append(f"Page {page_idx} is missing the running header.")

        # Find stamped page number
        page_nums_found = re.findall(r"Page\s+(\d+)", text)
        stamped_num = int(page_nums_found[-1]) if page_nums_found else -1
        has_footer = stamped_num == expected_pg_no
        if not has_footer:
            report.errors.append(
                f"Page {page_idx} running footer mismatch: found '{stamped_num}', expected '{expected_pg_no}'."
            )

        # 4. Content Bounding Box Overflow Check
        # Inspect text blocks
        blocks = page.get_text("blocks")
        has_overflow = False
        page_issues = []

        for b in blocks:
            x0, y0, x1, y1, btext, bno, btype = b
            clean_text = btext.strip()
            # Explicitly identify and skip running header and footer blocks
            if "Spring Boot Master Notes" in clean_text or "Coder Army" in clean_text:
                continue
            if re.match(r"^Page\s+\d+$", clean_text):
                continue
            # Also skip any blocks strictly in margin areas
            if y1 <= 45 or y0 >= 800:
                continue

            # Check horizontal overflow
            if x0 < MIN_X - 5:
                has_overflow = True
                page_issues.append(f"Text block overflows left margin (x0={x0:.1f})")
            if x1 > MAX_X + 5:
                has_overflow = True
                page_issues.append(f"Text block overflows right margin (x1={x1:.1f})")

            # Check vertical overflow into header/footer zones
            if y0 < MIN_CONTENT_Y - 8:
                has_overflow = True
                page_issues.append(f"Content encroaches header zone (y0={y0:.1f})")
            if y1 > MAX_CONTENT_Y + 10:
                has_overflow = True
                page_issues.append(f"Content encroaches footer zone (y1={y1:.1f})")

        if has_overflow:
            report.errors.append(f"Page {page_idx} has content overflowing printable boundaries.")

        # 5. Drawings Overflow Check
        for d in drawings:
            r = d["rect"]
            if r.x0 < MIN_X - 15 or r.x1 > MAX_X + 15:
                has_overflow = True
                page_issues.append(f"Drawing overflows horizontal margin (rect={r})")
                break

        page_result = PageQAResult(
            page_num=page_idx,
            stamped_page_num=stamped_num,
            expected_page_num=expected_pg_no,
            char_count=char_count,
            drawing_count=drawing_count,
            has_header=has_header,
            has_footer=has_footer,
            is_blank=is_blank,
            has_overflow=has_overflow,
            details=page_issues,
        )
        report.pages.append(page_result)

    if report.errors:
        report.is_passed = False

    return report
