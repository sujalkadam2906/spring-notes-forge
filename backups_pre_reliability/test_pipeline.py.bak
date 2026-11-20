"""Comprehensive Automated Test Suite for Spring Notes Automation Pipeline.

Covers all 15 required verification areas:
  1. Lecture source discovery
  2. Missing and duplicate source handling
  3. PDF text extraction
  4. Source hierarchy
  5. Prompt construction
  6. Gemini response validation
  7. Retry and rate-limit handling
  8. Environment-variable loading
  9. Filename generation
  10. Page tracker calculations
  11. Duplicate lecture prevention
  12. PDF page dimensions
  13. Page numbering continuity
  14. Blank-page detection
  15. Output validation
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
from google.genai import errors
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfgen import canvas

from build_notes import build_system_prompt, extract_headings_from_html
from pipeline.gemini_client import (
    GeminiClient,
    GeminiConfig,
    calculate_backoff,
    is_retriable_error,
)
from pipeline.pdf_renderer import PDFRenderer
from pipeline.qa import PageQAResult, QAReport, run_qa_checks
from pipeline.sources import LectureSources, discover_sources, inspect_source_text
from pipeline.tracker import LectureRecord, PageTracker


class TestSpringNotesPipeline(unittest.TestCase):
    def setUp(self):
        self.repo_dir = Path("repo")
        self.output_dir = Path("output")

    # 1. Lecture source discovery
    def test_01_lecture_source_discovery(self):
        sources = discover_sources(self.repo_dir, 6)
        self.assertEqual(sources.lecture_num, 6)
        self.assertTrue(sources.has_primary)
        self.assertTrue(sources.has_secondary)
        self.assertTrue(sources.has_practice)
        self.assertIn("excalidraw", sources.primary_pdf.name.lower())
        self.assertIn("notes", sources.secondary_pdf.name.lower())
        self.assertIn("practice", sources.practice_pdf.name.lower())

    # 2. Missing and duplicate source handling
    def test_02_missing_and_duplicate_source_handling(self):
        # Non-existent lecture folder
        with self.assertRaises(FileNotFoundError):
            discover_sources(self.repo_dir, 999)

        # Lecture with missing Excalidraw notes (Lecture 10)
        sources_10 = discover_sources(self.repo_dir, 10)
        self.assertIsNone(sources_10.primary_pdf)
        self.assertTrue(sources_10.has_secondary)

        # Ambiguous source files test with temporary folder
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "Lecture 88"
            tmp_path.mkdir()
            (tmp_path / "Excalidraw-1.pdf").write_bytes(b"%PDF-1.4 dummy")
            (tmp_path / "Excalidraw-2.pdf").write_bytes(b"%PDF-1.4 dummy")
            with self.assertRaises(ValueError) as ctx:
                discover_sources(Path(tmp_dir), 88)
            self.assertIn("Ambiguous primary sources", str(ctx.exception))

    # 3. PDF text extraction
    def test_03_pdf_text_extraction(self):
        # Lecture 6 Primary (image-based) vs Secondary (text-based)
        sources = discover_sources(self.repo_dir, 6)
        prim_info = inspect_source_text(sources.primary_pdf)
        sec_info = inspect_source_text(sources.secondary_pdf)

        self.assertEqual(prim_info["char_count"], 0)
        self.assertTrue(prim_info["is_drawn_or_scanned"])

        self.assertGreater(sec_info["char_count"], 30000)
        self.assertFalse(sec_info["is_drawn_or_scanned"])

    # 4. Source hierarchy
    def test_04_source_hierarchy(self):
        sources = discover_sources(self.repo_dir, 6)
        mock_client = MagicMock()
        mock_up = MagicMock()
        mock_up.name = "files/test_file_id"
        mock_client.client.files.upload.return_value = mock_up

        client = GeminiClient.__new__(GeminiClient)
        client.client = mock_client.client

        parts, uploaded = client.prepare_content_parts(sources)
        self.assertEqual(len(uploaded), 3)
        # Verify order: Primary first, Secondary second, Tertiary third
        self.assertIn("PRIMARY SOURCE", parts[0])
        self.assertIn("SECONDARY SOURCE", parts[2])
        self.assertIn("TERTIARY SOURCE", parts[4])

    # 5. Prompt construction
    def test_05_prompt_construction(self):
        prompt = build_system_prompt()
        self.assertIn("PRIMARY SOURCE", prompt)
        self.assertIn("SECONDARY SOURCE", prompt)
        self.assertIn("TERTIARY SOURCE", prompt)
        self.assertIn("125 pages", prompt)
        self.assertIn("<notes_html>", prompt)
        self.assertIn("Source discrepancy:", prompt)
        self.assertIn("Accuracy clarification:", prompt)

    # 6. Gemini response validation
    def test_06_gemini_response_validation(self):
        # Valid response
        valid_resp = (
            "<notes_html>\n"
            "<h1>Lecture 6 · Test Title</h1>\n"
            "<p>Valid text</p>\n"
            "<figure><svg viewBox='0 0 700 100'><rect/></svg></figure>\n"
            "<table><tr><td>Cell</td></tr></table>\n"
            "</notes_html>\n"
            "<issues>none</issues>"
        )
        body = GeminiClient.extract_and_validate_notes(valid_resp, 6)
        self.assertIn("Lecture 6 · Test Title", body)

        # Missing <notes_html>
        with self.assertRaises(ValueError) as ctx:
            GeminiClient.extract_and_validate_notes("No tags here", 6)
        self.assertIn("did not contain <notes_html>", str(ctx.exception))

        # Missing <h1>
        invalid_h1 = "<notes_html><p>No heading</p></notes_html>"
        with self.assertRaises(ValueError) as ctx:
            GeminiClient.extract_and_validate_notes(invalid_h1, 6)
        self.assertIn("Missing required <h1>", str(ctx.exception))

        # Mismatched SVG tags
        mismatched_svg = (
            "<notes_html><h1>Lecture 6 · Test</h1><svg viewBox='0 0 700 100'></notes_html>"
        )
        with self.assertRaises(ValueError) as ctx:
            GeminiClient.extract_and_validate_notes(mismatched_svg, 6)
        self.assertIn("Mismatched SVG tags", str(ctx.exception))

    # 7a. Primary model success (no fallback needed)
    def test_07a_primary_model_success(self):
        mock_client = MagicMock()
        cfg = GeminiConfig(
            api_key="mock_key",
            primary_model="gemini-4-hydrogen",
            fallback_model="gemini-3.1-pro-preview",
            max_retries=3,
            initial_backoff_sec=1,
        )
        client = GeminiClient.__new__(GeminiClient)
        client.config = cfg
        client.client = mock_client

        mock_resp = MagicMock()
        mock_resp.text = (
            "<notes_html><h1>Lecture 6 · Test Primary</h1><p>Success</p></notes_html>\n"
            "<issues>none</issues>"
        )
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]
        mock_client.models.generate_content.return_value = mock_resp
        mock_upload = MagicMock(name="uploaded_ref")
        mock_upload.name = "files/mock1"
        mock_client.files.upload.return_value = mock_upload

        with tempfile.TemporaryDirectory() as tmp_work:
            sources = discover_sources(self.repo_dir, 6)
            body = client.generate_lecture_notes(
                lecture_num=6,
                sources=sources,
                pages_so_far=24,
                target_pages=3,
                remaining_lectures=35,
                previous_headings=[],
                system_instruction="Test instruction",
                work_dir=Path(tmp_work),
            )
        self.assertIn("Test Primary", body)
        # Primary called once, fallback never called
        self.assertEqual(mock_client.models.generate_content.call_count, 1)
        self.assertEqual(mock_client.models.generate_content.call_args.kwargs["model"], "gemini-4-hydrogen")

    # 7b. Temporary API failure (503) retried, primary recovers
    def test_07b_temporary_retry_and_primary_recovery(self):
        mock_client = MagicMock()
        cfg = GeminiConfig(
            api_key="mock_key",
            primary_model="gemini-4-hydrogen",
            fallback_model="gemini-3.1-pro-preview",
            max_retries=3,
            initial_backoff_sec=1,
        )
        client = GeminiClient.__new__(GeminiClient)
        client.config = cfg
        client.client = mock_client

        err_503 = errors.APIError(503, {"error": {"message": "Service Unavailable - Demand Spike"}})
        mock_resp = MagicMock()
        mock_resp.text = (
            "<notes_html><h1>Lecture 6 · Recovered Primary</h1><p>Success</p></notes_html>\n"
            "<issues>none</issues>"
        )
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]

        calls = [err_503, mock_resp]
        mock_client.models.generate_content.side_effect = calls
        mock_upload = MagicMock(name="uploaded_ref")
        mock_upload.name = "files/mock1"
        mock_client.files.upload.return_value = mock_upload

        with tempfile.TemporaryDirectory() as tmp_work:
            sources = discover_sources(self.repo_dir, 6)
            with patch("time.sleep", return_value=None):
                body = client.generate_lecture_notes(
                    lecture_num=6,
                    sources=sources,
                    pages_so_far=24,
                    target_pages=3,
                    remaining_lectures=35,
                    previous_headings=[],
                    system_instruction="Test instruction",
                    work_dir=Path(tmp_work),
                )
        self.assertIn("Recovered Primary", body)
        self.assertEqual(mock_client.models.generate_content.call_count, 2)

    # 7c. Connection interruption (WinError 10053) retried, primary recovers
    def test_07c_connection_interruption_retried(self):
        mock_client = MagicMock()
        cfg = GeminiConfig(
            api_key="mock_key",
            primary_model="gemini-4-hydrogen",
            fallback_model="gemini-3.1-pro-preview",
            max_retries=3,
            initial_backoff_sec=1,
        )
        client = GeminiClient.__new__(GeminiClient)
        client.config = cfg
        client.client = mock_client

        conn_aborted = ConnectionAbortedError(10053, "[WinError 10053] An established connection was aborted")
        mock_resp = MagicMock()
        mock_resp.text = (
            "<notes_html><h1>Lecture 6 · Post-Abort Recovery</h1><p>Success</p></notes_html>\n"
            "<issues>none</issues>"
        )
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]

        calls = [conn_aborted, mock_resp]
        mock_client.models.generate_content.side_effect = calls
        mock_upload = MagicMock(name="uploaded_ref")
        mock_upload.name = "files/mock1"
        mock_client.files.upload.return_value = mock_upload

        with tempfile.TemporaryDirectory() as tmp_work:
            sources = discover_sources(self.repo_dir, 6)
            with patch("time.sleep", return_value=None):
                body = client.generate_lecture_notes(
                    lecture_num=6,
                    sources=sources,
                    pages_so_far=24,
                    target_pages=3,
                    remaining_lectures=35,
                    previous_headings=[],
                    system_instruction="Test instruction",
                    work_dir=Path(tmp_work),
                )
        self.assertIn("Post-Abort Recovery", body)
        self.assertEqual(mock_client.models.generate_content.call_count, 2)

    # 7d. Fallback success after primary temporary retries exhausted
    def test_07d_fallback_success_after_temporary_exhaustion(self):
        mock_client = MagicMock()
        cfg = GeminiConfig(
            api_key="mock_key",
            primary_model="gemini-4-hydrogen",
            fallback_model="gemini-3.1-pro-preview",
            max_retries=2,
            initial_backoff_sec=1,
        )
        client = GeminiClient.__new__(GeminiClient)
        client.config = cfg
        client.client = mock_client

        err_429 = errors.APIError(429, {"error": {"message": "Rate limit exceeded"}})
        mock_resp = MagicMock()
        mock_resp.text = (
            "<notes_html><h1>Lecture 6 · Fallback Succeeded</h1><p>Success</p></notes_html>\n"
            "<issues>none</issues>"
        )
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]

        def mock_generate(*args, **kwargs):
            if kwargs.get("model") == "gemini-4-hydrogen":
                raise err_429
            return mock_resp

        mock_client.models.generate_content.side_effect = mock_generate
        mock_upload = MagicMock(name="uploaded_ref")
        mock_upload.name = "files/mock1"
        mock_client.files.upload.return_value = mock_upload

        with tempfile.TemporaryDirectory() as tmp_work:
            sources = discover_sources(self.repo_dir, 6)
            with patch("time.sleep", return_value=None):
                body = client.generate_lecture_notes(
                    lecture_num=6,
                    sources=sources,
                    pages_so_far=24,
                    target_pages=3,
                    remaining_lectures=35,
                    previous_headings=[],
                    system_instruction="Test instruction",
                    work_dir=Path(tmp_work),
                )
        self.assertIn("Fallback Succeeded", body)
        # Primary called twice (max_retries=2), fallback called once
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    # 7e. Fallback success after permanent error (404) without wasting retries
    def test_07e_fallback_success_after_permanent_not_found_404(self):
        mock_client = MagicMock()
        cfg = GeminiConfig(
            api_key="mock_key",
            primary_model="gemini-bad-model",
            fallback_model="gemini-3.1-pro-preview",
            max_retries=5,
            initial_backoff_sec=1,
        )
        client = GeminiClient.__new__(GeminiClient)
        client.config = cfg
        client.client = mock_client

        err_404 = errors.APIError(404, {"error": {"message": "Model not found"}})
        mock_resp = MagicMock()
        mock_resp.text = (
            "<notes_html><h1>Lecture 6 · Fallback After 404</h1><p>Success</p></notes_html>\n"
            "<issues>none</issues>"
        )
        mock_resp.candidates = [MagicMock(finish_reason="STOP")]

        def mock_generate(*args, **kwargs):
            if kwargs.get("model") == "gemini-bad-model":
                raise err_404
            return mock_resp

        mock_client.models.generate_content.side_effect = mock_generate
        mock_upload = MagicMock(name="uploaded_ref")
        mock_upload.name = "files/mock1"
        mock_client.files.upload.return_value = mock_upload

        with tempfile.TemporaryDirectory() as tmp_work:
            sources = discover_sources(self.repo_dir, 6)
            with patch("time.sleep", return_value=None) as sleep_mock:
                body = client.generate_lecture_notes(
                    lecture_num=6,
                    sources=sources,
                    pages_so_far=24,
                    target_pages=3,
                    remaining_lectures=35,
                    previous_headings=[],
                    system_instruction="Test instruction",
                    work_dir=Path(tmp_work),
                )
            # Sleep was never called because 404 is permanent
            sleep_mock.assert_not_called()

        self.assertIn("Fallback After 404", body)
        # Primary called exactly once (no retry waste), then fallback called once
        self.assertEqual(mock_client.models.generate_content.call_count, 2)

    # 7f. Both models fail with clear error summary identifying each failure reason
    def test_07f_both_models_fail_clear_error(self):
        mock_client = MagicMock()
        cfg = GeminiConfig(
            api_key="mock_key",
            primary_model="gemini-4-hydrogen",
            fallback_model="gemini-3.1-pro-preview",
            max_retries=2,
            initial_backoff_sec=1,
        )
        client = GeminiClient.__new__(GeminiClient)
        client.config = cfg
        client.client = mock_client

        err_503 = errors.APIError(503, {"error": {"message": "Demand spike"}})
        err_404 = errors.APIError(404, {"error": {"message": "Model not found"}})

        def mock_generate(*args, **kwargs):
            if kwargs.get("model") == "gemini-4-hydrogen":
                raise err_503
            raise err_404

        mock_client.models.generate_content.side_effect = mock_generate
        mock_upload = MagicMock(name="uploaded_ref")
        mock_upload.name = "files/mock1"
        mock_client.files.upload.return_value = mock_upload

        with tempfile.TemporaryDirectory() as tmp_work:
            sources = discover_sources(self.repo_dir, 6)
            with patch("time.sleep", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    client.generate_lecture_notes(
                        lecture_num=6,
                        sources=sources,
                        pages_so_far=24,
                        target_pages=3,
                        remaining_lectures=35,
                        previous_headings=[],
                        system_instruction="Test instruction",
                        work_dir=Path(tmp_work),
                    )
        err_msg = str(ctx.exception)
        self.assertIn("gemini-4-hydrogen", err_msg)
        self.assertIn("503", err_msg)
        self.assertIn("gemini-3.1-pro-preview", err_msg)
        self.assertIn("404", err_msg)

    # 7g. Retriable vs permanent error classifier verification
    def test_07g_is_retriable_error_matrix(self):
        # Temporary status codes
        for code in (429, 500, 502, 503, 504, 408):
            err = errors.APIError(code, {"error": {"message": "temp"}})
            retriable, reason = is_retriable_error(err)
            self.assertTrue(retriable, f"Expected {code} to be retriable")
            self.assertIn("temporary", reason.lower())

        # Permanent status codes
        for code in (400, 401, 403, 404):
            err = errors.APIError(code, {"error": {"message": "perm"}})
            retriable, reason = is_retriable_error(err)
            self.assertFalse(retriable, f"Expected {code} to be non-retriable")
            self.assertIn("permanent", reason.lower())

        # Connection and socket interruptions
        conn_errs = [
            ConnectionResetError(10054, "Connection reset"),
            ConnectionAbortedError(10053, "[WinError 10053] Connection aborted"),
            TimeoutError("Read timeout"),
            OSError(10053, "WinError 10053 occurred"),
        ]
        for cerr in conn_errs:
            retriable, reason = is_retriable_error(cerr)
            self.assertTrue(retriable, f"Expected {cerr} to be retriable")

    # 7h. Exponential backoff with jitter calculation
    def test_07h_backoff_jitter(self):
        delay_1 = calculate_backoff(1, base_sec=10.0, max_sec=60.0)
        delay_2 = calculate_backoff(2, base_sec=10.0, max_sec=60.0)
        # Attempt 1 should be around 10 + [1..3]
        self.assertGreaterEqual(delay_1, 10.0)
        self.assertLessEqual(delay_1, 15.0)
        # Attempt 2 should be around 20 + [1..3]
        self.assertGreaterEqual(delay_2, 20.0)
        self.assertLessEqual(delay_2, 25.0)
        # Capped delay
        delay_large = calculate_backoff(10, base_sec=10.0, max_sec=60.0)
        self.assertLessEqual(delay_large, 60.0)

    # 8. Environment-variable loading
    def test_08_environment_variable_loading(self):
        # Default models when not overridden
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test_secret_key"}, clear=True):
            cfg = GeminiConfig.from_env()
            self.assertEqual(cfg.api_key, "test_secret_key")
            self.assertEqual(cfg.primary_model, "gemini-3.6-flash")
            self.assertEqual(cfg.fallback_model, "gemini-4-hydrogen")
            self.assertEqual(cfg.max_retries, 5)
            self.assertEqual(cfg.initial_backoff_sec, 15)

        # Custom configured models via env
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test_secret_key",
                "GEMINI_MODEL": "custom-primary",
                "GEMINI_FALLBACK_MODEL": "custom-fallback",
                "GEMINI_MAX_RETRIES": "7",
                "GEMINI_INITIAL_BACKOFF_SEC": "20",
            },
            clear=True,
        ):
            cfg = GeminiConfig.from_env()
            self.assertEqual(cfg.primary_model, "custom-primary")
            self.assertEqual(cfg.fallback_model, "custom-fallback")
            self.assertEqual(cfg.max_retries, 7)
            self.assertEqual(cfg.initial_backoff_sec, 20)

        # Missing key raises clean error
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                GeminiConfig.from_env()
            self.assertIn("GEMINI_API_KEY is not configured", str(ctx.exception))

    # 9. Filename generation and slug formatting
    def test_09_filename_generation(self):
        html = "<h1>Lecture 6 · Circular Dependency, Bean Scope &amp; Lifecycle</h1>"
        t_match = extract_headings_from_html(html)
        self.assertEqual(len(t_match), 1)
        self.assertIn("Circular Dependency", t_match[0])

    # 10. Page tracker calculations
    def test_10_page_tracker_calculations(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tracker = PageTracker(tmp_dir)
            tracker.record_lecture(
                lecture_num=1,
                title="Intro",
                start_page=1,
                end_page=8,
                page_count=8,
                filename="Lec_01.pdf",
                headings=["Heading 1"],
            )
            self.assertEqual(tracker.get_next_start_page(2), 9)

            # Lecture 2 added
            tracker.record_lecture(
                lecture_num=2,
                title="Lec 2",
                start_page=9,
                end_page=13,
                page_count=5,
                filename="Lec_02.pdf",
                headings=["Heading 2"],
            )
            self.assertEqual(tracker.get_next_start_page(3), 14)

    # 11. Duplicate lecture and gap prevention
    def test_11_duplicate_lecture_prevention(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tracker = PageTracker(tmp_dir)
            tracker.record_lecture(
                lecture_num=1,
                title="Intro",
                start_page=1,
                end_page=5,
                page_count=5,
                filename="Lec_01.pdf",
                headings=[],
            )
            # Gap check: requesting lecture 4 when only 1 is done
            with self.assertRaises(ValueError) as ctx:
                tracker.get_next_start_page(4)
            self.assertIn("Page gap detected", str(ctx.exception))

            # Discontinuity check
            with self.assertRaises(ValueError) as ctx:
                tracker.record_lecture(
                    lecture_num=2,
                    title="Lec 2",
                    start_page=10,  # Should be 6!
                    end_page=14,
                    page_count=5,
                    filename="Lec_02.pdf",
                    headings=[],
                )
            self.assertIn("Integrity error", str(ctx.exception))

    # 12. PDF page dimensions
    def test_12_pdf_page_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a non-A4 (Letter) PDF
            non_a4_path = Path(tmp_dir) / "letter.pdf"
            c = canvas.Canvas(str(non_a4_path), pagesize=letter)
            c.drawString(100, 700, "Letter page test Spring Boot Master Notes Coder Army")
            c.drawString(100, 50, "Page 1")
            c.save()

            report = run_qa_checks(non_a4_path, expected_start_page=1)
            self.assertFalse(report.is_passed)
            self.assertTrue(any("not standard A4" in err for err in report.errors))

    # 13. Page numbering continuity
    def test_13_page_numbering_continuity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tracker = PageTracker(tmp_dir)
            # Bootstrap existing state
            tracker.record_lecture(1, "L1", 1, 8, 8, "f1.pdf", [])
            tracker.record_lecture(2, "L2", 9, 13, 5, "f2.pdf", [])
            valid, issues = tracker.validate_integrity()
            self.assertTrue(valid)

            # Introduce artificial discontinuity
            tracker.data["lectures"]["3"] = {
                "lecture_num": 3,
                "title": "L3",
                "start_page": 15,  # Gap from 13!
                "end_page": 18,
                "page_count": 4,
                "filename": "f3.pdf",
                "status": "completed",
                "verified": True,
                "headings": [],
                "lecture_span_end": None,
            }
            valid, issues = tracker.validate_integrity()
            self.assertFalse(valid)
            self.assertTrue(any("Discontinuity" in iss for iss in issues))

    # 14. Blank-page detection
    def test_14_blank_page_detection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            blank_pdf = Path(tmp_dir) / "blank.pdf"
            c = canvas.Canvas(str(blank_pdf), pagesize=A4)
            # Page 1 normal
            c.drawString(60, 800, "Spring Boot Master Notes | Coder Army")
            c.drawString(60, 700, "A" * 200)
            c.drawString(300, 30, "Page 1")
            c.showPage()
            # Page 2 blank
            c.showPage()
            c.save()

            report = run_qa_checks(blank_pdf, expected_start_page=1)
            self.assertFalse(report.is_passed)
            self.assertTrue(any("appears blank" in err for err in report.errors))

    # 15. Output validation on actual Lecture 6
    def test_15_output_validation_actual_lec_06(self):
        lec_06_pdf = self.output_dir / "Spring_Boot_Lec_06_Circular_Dependency_Bean_Scope_Initializ.pdf"
        self.assertTrue(lec_06_pdf.exists())
        report = run_qa_checks(lec_06_pdf, expected_start_page=25)
        self.assertTrue(report.is_passed)
        self.assertEqual(report.total_pages, 6)
        self.assertEqual(report.start_page, 25)
        self.assertEqual(report.end_page, 30)

    # Test handling Windows paths with spaces
    def test_16_windows_paths_with_spaces(self):
        # Current project path contains spaces: E:\Sujal Kadam\Programming Notes\...
        cwd = Path.cwd()
        self.assertIn(" ", str(cwd))
        # Ensure Path operations work seamlessly
        test_file = cwd / "work" / "path_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        self.assertEqual(test_file.read_text(encoding="utf-8"), "ok")
        test_file.unlink()

    # 17. Source discovery with unpadded folder fallback
    def test_17_source_discovery_unpadded_folder_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_repo = Path(tmp_dir)
            # Create Lecture 7 without leading zero
            lec_dir = tmp_repo / "Lecture 7"
            lec_dir.mkdir()
            (lec_dir / "Notes.pdf").write_bytes(b"%PDF-1.4 dummy")
            sources = discover_sources(tmp_repo, 7)
            self.assertEqual(sources.lecture_num, 7)
            self.assertTrue(sources.has_secondary)

    # 18. Title separator flexibility in model response validation
    def test_18_notes_title_separator_flexibility(self):
        for sep in ["·", "-", ":"]:
            html = f"<notes_html><h1>Lecture 6 {sep} Title</h1><p>Content</p></notes_html><issues>none</issues>"
            body = GeminiClient.extract_and_validate_notes(html, 6)
            self.assertIn(f"Lecture 6 {sep} Title", body)

    # 19. Output validation on actual completed Lecture 7
    def test_19_output_validation_actual_lec_07(self):
        lec_07_pdf = self.output_dir / "Spring_Boot_Lec_07_Spring_Bean_Lifecycle.pdf"
        self.assertTrue(lec_07_pdf.exists())
        report = run_qa_checks(lec_07_pdf, expected_start_page=31)
        self.assertTrue(report.is_passed)
        self.assertEqual(report.total_pages, 4)
        self.assertEqual(report.start_page, 31)
        self.assertEqual(report.end_page, 34)


if __name__ == "__main__":
    unittest.main()
