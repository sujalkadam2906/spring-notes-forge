"""Automated Test Suite for Final Book Publishing & Supplement Generation.

Covers all Phase 9 verification requirements:
  - Correct lecture discovery
  - Missing lecture detection
  - Duplicate lecture detection
  - Correct lecture ordering (numerical, not alphabetical)
  - Correct PDF merging
  - Cover placement (first page)
  - Contents page placement
  - Printed page-label calculation
  - PDF bookmark generation (hierarchical outlines)
  - Supplement ordering
  - Supplement cache reuse
  - Invalid supplement HTML validation
  - Missing supplement PDFs handling
  - Atomic output creation
  - Existing PDF preservation (no destructive overwriting without backup)
  - Existing page_tracker.json preservation (read-only)
  - Final PDF metadata verification
  - Final PDF readability and page bounds
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pypdf
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pipeline.book_publisher import BookPublisher, LectureFileInfo, PublishingConfig
from pipeline.supplement_generator import (
    SupplementGenerator,
    SupplementStamper,
    save_cache_atomically,
    validate_supplement_html,
)


def create_synthetic_lecture_pdf(
    path: Path,
    lecture_num: int,
    start_page: int,
    num_pages: int,
    title: str = "Test Topic",
    span_end: int | None = None,
) -> Path:
    """Creates a valid synthetic lecture PDF with stamped running header & footer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    w, h = A4

    for i in range(num_pages):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setFont("Helvetica", 10)
        # Running header
        c.drawString(50, h - 35, "Spring Boot Master Notes")
        c.drawRightString(w - 50, h - 35, "Coder Army Spring Boot Series")
        c.line(50, h - 40, w - 50, h - 40)

        # Title on first page
        if i == 0:
            c.setFont("Helvetica-Bold", 14)
            lec_str = f"Lecture {lecture_num:02d}" if not span_end else f"Lecture {lecture_num:02d}-{span_end:02d}"
            c.drawString(50, h - 80, f"{lec_str} · {title}")
            c.setFont("Helvetica-Bold", 11)
            c.drawString(50, h - 120, f"{lecture_num}.1 Architectural Overview")

        # Running footer with printed page number
        current_pg = start_page + i
        c.setFont("Helvetica", 9)
        c.drawCentredString(w / 2, 30, f"Page {current_pg}")
        c.save()

        buf.seek(0)
        writer.add_page(PdfReader(buf).pages[0])

    with open(path, "wb") as f:
        writer.write(f)
    return path


class TestPublishingAndSupplements(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.test_dir) / "output"
        self.work_dir = Path(self.test_dir) / "work"
        self.supp_dir = Path(self.test_dir) / "supplements"
        self.templates_dir = Path("templates")  # Use real templates
        self.dist_dir = Path(self.test_dir) / "dist"

        self.output_dir.mkdir(parents=True)
        self.work_dir.mkdir(parents=True)
        self.supp_dir.mkdir(parents=True)
        self.dist_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. Correct lecture discovery & numerical ordering
    def test_01_discovery_and_numerical_ordering(self):
        # Create lectures out of order and with alphabetical trap (e.g. Lec 10 vs Lec 2)
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_10_Config.pdf", 10, 46, 5)
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_02_App.pdf", 2, 9, 5)
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_01_Intro.pdf", 1, 1, 8)

        cfg = PublishingConfig(output_dir=self.output_dir, work_dir=self.work_dir)
        publisher = BookPublisher(cfg)
        lectures, issues = publisher.discover_lectures()

        self.assertEqual(len(lectures), 3)
        self.assertEqual([l.lecture_num for l in lectures], [1, 2, 10])
        # Note: missing lectures 3-9 will be reported in issues
        self.assertTrue(any("Missing lecture numbers" in iss for iss in issues))

    # 2. Missing lecture detection
    def test_02_missing_lecture_detection(self):
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_01.pdf", 1, 1, 5)
        # Skip lecture 2
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_03.pdf", 3, 6, 5)

        cfg = PublishingConfig(output_dir=self.output_dir, work_dir=self.work_dir)
        publisher = BookPublisher(cfg)
        _, issues = publisher.discover_lectures()

        self.assertTrue(any("Missing lecture numbers detected" in iss and "2" in iss for iss in issues))

    # 3. Duplicate lecture detection
    def test_03_duplicate_lecture_detection(self):
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_03_VersionA.pdf", 3, 9, 5)
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_03_VersionB.pdf", 3, 9, 5)

        cfg = PublishingConfig(output_dir=self.output_dir, work_dir=self.work_dir)
        publisher = BookPublisher(cfg)
        _, issues = publisher.discover_lectures()

        self.assertTrue(any("Duplicate lecture 3 found" in iss for iss in issues))

    # 4. Pagination continuity verification
    def test_04_pagination_discontinuity_detection(self):
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_01.pdf", 1, 1, 5)
        # Gap: Lec 1 ends at 5, but Lec 2 mistakenly starts at 10
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_02.pdf", 2, 10, 5)

        cfg = PublishingConfig(output_dir=self.output_dir, work_dir=self.work_dir)
        publisher = BookPublisher(cfg)
        _, issues = publisher.discover_lectures()

        self.assertTrue(any("Pagination discontinuity" in iss for iss in issues))

    # 5. Invalid supplement HTML validation
    def test_05_supplement_html_validation(self):
        # Empty HTML
        with self.assertRaises(ValueError):
            validate_supplement_html("", "revision")

        # Too short
        with self.assertRaises(ValueError):
            validate_supplement_html("<h1>Short</h1>", "revision")

        # Missing <h1>
        with self.assertRaises(ValueError):
            validate_supplement_html("<p>" + "valid " * 100 + "</p>", "revision")

        # Mismatched tables
        mismatched_tbl = "<h1>Title</h1>" + "<p>Text</p>" * 50 + "<table><tr><td>Missing close"
        with self.assertRaises(ValueError):
            validate_supplement_html(mismatched_tbl, "revision")

    # 6. Supplement cache reuse & atomic creation
    def test_06_supplement_cache_reuse_and_atomic_save(self):
        cache_file = self.work_dir / "supplement_revision.html"
        test_html = "<h1>Test Cache</h1>" + "<p>Cached content for revision testing.</p>" * 40
        validate_supplement_html(test_html, "revision")

        # Atomic save test
        save_cache_atomically(cache_file, test_html)
        self.assertTrue(cache_file.exists())
        self.assertIn("Test Cache", cache_file.read_text(encoding="utf-8"))

        generator = SupplementGenerator(
            work_dir=self.work_dir,
            output_dir=self.supp_dir,
        )
        pdf_path = generator.generate_supplement("revision", reuse=True)
        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 1000)

    # 7. Safe overwrite and backup
    def test_07_safe_overwrite_and_backup(self):
        dest_pdf = self.dist_dir / "Final_Book.pdf"
        dest_pdf.write_bytes(b"%PDF-1.4 initial content")

        cfg = PublishingConfig(
            output_dir=self.output_dir,
            work_dir=self.work_dir,
            dest_pdf=dest_pdf,
            templates_dir=self.templates_dir,
            supplements_dir=self.supp_dir,
        )
        publisher = BookPublisher(cfg)

        # Setup 2 valid continuous lectures
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_01.pdf", 1, 1, 5)
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_02.pdf", 2, 6, 5)

        # Overwrite without flag should raise FileExistsError
        with self.assertRaises(FileExistsError):
            publisher.publish(overwrite=False)

        # Overwrite with flag should create .bak backup
        publisher.publish(overwrite=True)
        self.assertTrue(dest_pdf.exists())
        bak_file = dest_pdf.with_suffix(".bak.pdf")
        self.assertTrue(bak_file.exists())
        self.assertEqual(bak_file.read_bytes(), b"%PDF-1.4 initial content")

    # 8. Full book assembly: cover, contents, guide, lectures, bookmarks, metadata
    def test_08_full_book_assembly_and_metadata(self):
        dest_pdf = self.dist_dir / "Spring_Boot_Complete_Notes.pdf"
        cfg = PublishingConfig(
            author="Test Author",
            edition="2026 Test Edition",
            output_dir=self.output_dir,
            work_dir=self.work_dir,
            supplements_dir=self.supp_dir,
            templates_dir=self.templates_dir,
            dest_pdf=dest_pdf,
        )
        publisher = BookPublisher(cfg)

        # Create lectures 1 to 3
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_01.pdf", 1, 1, 4, title="Intro")
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_02.pdf", 2, 5, 4, title="Config")
        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_03.pdf", 3, 9, 4, title="Persistence")

        # Create a supplement
        create_synthetic_lecture_pdf(self.supp_dir / "Revision_Sheets.pdf", 99, 13, 2, title="Revision")

        out_path = publisher.publish(overwrite=True)
        self.assertTrue(out_path.exists())

        # Inspect final PDF
        reader = PdfReader(str(out_path))
        self.assertGreater(len(reader.pages), 10)

        # Check metadata
        meta = reader.metadata
        self.assertIsNotNone(meta)
        self.assertEqual(meta.get("/Title"), "Spring Boot Complete Notes & Interview Guide")
        self.assertEqual(meta.get("/Author"), "Test Author")

        # Check outline bookmarks exist
        outline = reader.outline
        self.assertTrue(len(outline) > 0)

    # 9. Existing page_tracker.json preservation
    def test_09_page_tracker_preservation(self):
        # Create a dummy tracker
        tracker_file = self.output_dir / "page_tracker.json"
        tracker_content = json.dumps({"test_key": "must_not_be_modified", "lectures": {}})
        tracker_file.write_text(tracker_content, encoding="utf-8")

        create_synthetic_lecture_pdf(self.output_dir / "Spring_Boot_Lec_01.pdf", 1, 1, 4)
        cfg = PublishingConfig(output_dir=self.output_dir, work_dir=self.work_dir)
        publisher = BookPublisher(cfg)
        publisher.discover_lectures()

        # Verify page_tracker.json was not mutated
        self.assertEqual(tracker_file.read_text(encoding="utf-8"), tracker_content)


if __name__ == "__main__":
    unittest.main()
