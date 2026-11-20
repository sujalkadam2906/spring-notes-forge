"""Spring Notes Automation — High-Quality Black & White A4 Lecture Notes Pipeline.

Converts course materials into beginner-friendly, publication-grade, compact
lecture notes adhering to strict source hierarchy, page budget, and continuous
pagination.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure standard UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

ROOT = Path(__file__).parent
REPO_DIR = ROOT / "repo"
WORK_DIR = ROOT / "work"
DEFAULT_OUT_DIR = ROOT / "output"
INSTRUCTIONS_FILE = ROOT / "instructions.md"
STYLE_FILE = ROOT / "style.css"

from pipeline.gemini_client import GeminiClient, GeminiConfig
from pipeline.pdf_renderer import PDFRenderer
from pipeline.qa import run_qa_checks
from pipeline.sources import discover_sources, inspect_source_text
from pipeline.tracker import PageTracker


def build_system_prompt() -> str:
    """Loads system instructions and pipeline overrides."""
    base_instructions = ""
    if INSTRUCTIONS_FILE.exists():
        base_instructions = INSTRUCTIONS_FILE.read_text(encoding="utf-8")

    pipeline_overrides = (
        "\n\n=== PIPELINE EXECUTION MODE ===\n"
        "You are generating raw HTML content for an automated PDF pipeline.\n"
        "A Python pipeline will render your HTML to PDF and stamp the continuous running "
        "header, footer, and page numbers.\n"
        "Do not ask clarifying questions; put anything unclear or conflicting in <issues>.\n"
        "Return exactly <notes_html>...</notes_html> and <issues>...</issues>."
    )
    return base_instructions + pipeline_overrides


def extract_headings_from_html(html_body: str) -> list[str]:
    """Extracts top-level headings from generated HTML for tracker indexing."""
    headings = []
    for h in re.finditer(r"<(h[1-3])[^>]*>(.*?)</\1>", html_body, re.IGNORECASE | re.DOTALL):
        text = re.sub(r"<[^>]+>", "", h.group(2)).strip()
        text = re.sub(r"\s+", " ", text)
        if text and text not in headings:
            headings.append(text[:90])
    return headings


def run_lecture(
    lecture_num: int,
    tracker: PageTracker,
    renderer: PDFRenderer,
    client: GeminiClient,
    output_dir: Path,
    reuse: bool = False,
    force: bool = False,
    skip_qa: bool = False,
) -> bool:
    """Executes end-to-end processing for a single lecture."""
    print(f"\n{'='*25} PROCESSING LECTURE {lecture_num:02d} {'='*25}")

    # 1. Check existing output
    existing_records = {r.lecture_num: r for r in tracker.get_verified_records()}
    existing_rec = existing_records.get(lecture_num)
    existing_files = list(output_dir.glob(f"Spring_Boot_Lec_{lecture_num:02d}_*.pdf"))

    if existing_files and not force:
        if existing_rec and existing_rec.verified and existing_files[0].stat().st_size > 0:
            print(
                f"[INFO] Lecture {lecture_num} PDF already verified ({existing_files[0].name}, "
                f"Pages {existing_rec.start_page}–{existing_rec.end_page}). Use --force to regenerate."
            )
            return True
        print(
            f"[WARN] Lecture {lecture_num} file exists ({existing_files[0].name}) but is missing "
            f"or unverified in page tracker. Regenerating to restore integrity."
        )

    if force and existing_rec:
        subsequent = [r for r in tracker.get_verified_records() if r.lecture_num > lecture_num]
        if subsequent:
            print(
                f"[WARN] Regenerating Lecture {lecture_num} with --force while subsequent lectures "
                f"({', '.join(str(r.lecture_num) for r in subsequent)}) exist. "
                "If page count changes, subsequent lectures must be regenerated to maintain continuity."
            )

    # 2. Source Discovery & Verification
    sources = discover_sources(REPO_DIR, lecture_num)
    print(sources.get_summary())

    # 3. Determine verified starting page
    start_page = tracker.get_next_start_page(lecture_num)
    budget = tracker.get_budget_status(lecture_num)
    target_pages = budget["recommended_pages_this_lecture"]

    print(f"\n[PAGE TRACKING & BUDGET]")
    print(f"  - Verified Starting Page: {start_page}")
    print(f"  - Book Pages Generated So Far: {budget['pages_used']}/{budget['book_target']}")
    print(f"  - Remaining Lectures: {budget['lectures_remaining']}")
    print(f"  - Suggested Size For This Lecture: ~{target_pages} pages (editorial guidance, not strict)")

    # 4. Content Acquisition (Reuse cached HTML or Call Gemini)
    html_cache_file = WORK_DIR / f"lecture_{lecture_num:02d}.html"
    body_html = ""

    if reuse and html_cache_file.exists():
        print(f"\n[INFO] Reusing cached HTML from {html_cache_file.name} (no API quota used)...")
        body_html = html_cache_file.read_text(encoding="utf-8")
    else:
        print(f"\n[INFO] Generating lecture content via Gemini API...")
        previous_headings = tracker.get_all_headings(up_to_lecture=lecture_num)
        system_prompt = build_system_prompt()

        body_html = client.generate_lecture_notes(
            lecture_num=lecture_num,
            sources=sources,
            pages_so_far=budget["pages_used"],
            target_pages=target_pages,
            remaining_lectures=budget["lectures_remaining"],
            previous_headings=previous_headings,
            system_instruction=system_prompt,
            work_dir=WORK_DIR,
        )
        # Validate HTML before caching — never cache empty or malformed output
        if not body_html or not body_html.strip():
            raise RuntimeError(
                f"Generation returned empty HTML for Lecture {lecture_num}. "
                "Refusing to cache empty output."
            )
        if "<h1>" not in body_html.lower():
            raise RuntimeError(
                f"Generation returned HTML without <h1> tag for Lecture {lecture_num}. "
                "Refusing to cache malformed output."
            )
        # Save HTML cache atomically to prevent corruption
        import tempfile
        cache_tmp_fd, cache_tmp_path = tempfile.mkstemp(
            dir=str(WORK_DIR), suffix=".html.tmp"
        )
        try:
            with os.fdopen(cache_tmp_fd, "w", encoding="utf-8") as tmp_f:
                tmp_f.write(body_html)
            os.replace(cache_tmp_path, str(html_cache_file))
        except Exception:
            # Clean up temp file on failure; do not corrupt cache
            try:
                os.unlink(cache_tmp_path)
            except OSError:
                pass
            raise

    # 5. Extract Title and Construct Output Filename
    t_match = re.search(r"<h1>\s*Lecture\s+\d+\s*[·:\-]\s*(.*?)\s*</h1>", body_html, re.IGNORECASE | re.DOTALL)
    raw_title = t_match.group(1).strip() if t_match else "Notes"
    # Clean HTML entities from title
    clean_title = re.sub(r"&[a-z]+;", "", raw_title).strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", clean_title).strip("_")[:40]
    output_pdf_path = output_dir / f"Spring_Boot_Lec_{lecture_num:02d}_{slug}.pdf"

    # 6. Render PDF and Generate High-Resolution Previews
    staging_pdf_path = WORK_DIR / f"staging_lec_{lecture_num:02d}.pdf"
    preview_dir = WORK_DIR / f"preview_{lecture_num:02d}"
    print(f"\n[INFO] Rendering PDF with Playwright and ReportLab stamping...")
    page_count = renderer.render_lecture_pdf(
        body_html=body_html,
        output_pdf_path=staging_pdf_path,
        start_page=start_page,
        work_dir=WORK_DIR,
        preview_dir=preview_dir,
        dpi=120,
    )

    end_page = start_page + page_count - 1

    # 7. Automated Quality Assurance Checks
    if not skip_qa:
        print(f"\n[INFO] Running automated visual & structural QA checks...")
        qa_report = run_qa_checks(staging_pdf_path, expected_start_page=start_page)
        qa_report.print_summary()
        if not qa_report.is_passed:
            print(
                f"[ERROR] Quality assurance checks failed for Lecture {lecture_num}! "
                f"Staging artifact preserved in {staging_pdf_path.name} for debugging."
            )
            return False

    # Atomically commit verified PDF to output destination
    import shutil
    shutil.copy2(staging_pdf_path, output_pdf_path)
    print(f"[SUCCESS] Verified PDF committed: {output_pdf_path.name}")
    print(f"  - Pages: {page_count} (Numbered {start_page} to {end_page})")

    # 8. Record in Persistent Page Tracker
    headings = extract_headings_from_html(body_html)
    tracker.record_lecture(
        lecture_num=lecture_num,
        title=clean_title,
        start_page=start_page,
        end_page=end_page,
        page_count=page_count,
        filename=output_pdf_path.name,
        headings=headings,
        status="completed",
        verified=True,
    )
    print(f"[TRACKER] Updated state in {tracker.tracker_path.name}.")
    return True


def display_status(tracker: PageTracker) -> None:
    """Displays comprehensive book status and integrity verification."""
    print(f"\n{'='*25} SPRING BOOT STUDY BOOK STATUS {'='*25}")
    recs = tracker.get_verified_records()
    if not recs:
        print("No completed lectures recorded.")
        return

    print(f"{'Lec':<6} {'Pages':<12} {'Count':<8} {'Status':<12} {'Output Filename'}")
    print("-" * 75)
    for r in recs:
        span_str = f"{r.lecture_num}" if not r.lecture_span_end else f"{r.lecture_num}-{r.lecture_span_end}"
        pg_str = f"{r.start_page}–{r.end_page}"
        print(f"{span_str:<6} {pg_str:<12} {r.page_count:<8} {r.status:<12} {r.filename}")

    valid, issues = tracker.validate_integrity()
    print("-" * 75)
    total_pages = tracker.get_last_completed_page()
    print(f"Total Pages Generated: {total_pages} / Target ~{tracker.BOOK_TARGET} (soft estimate, warning at {tracker.HARD_CEILING})")
    print(f"Integrity Check: {'PASS (Continuous)' if valid else 'FAIL'}")
    if issues:
        for iss in issues:
            print(f"  - {iss}")
    print("=" * 75 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spring Boot Master Study Notes Automation Pipeline"
    )
    parser.add_argument("lectures", nargs="?", help="Lecture number or range, e.g. 6 or 6-10")
    parser.add_argument("--out", default="output", help="Output directory for final PDFs")
    parser.add_argument("--list", action="store_true", help="List discovered source files without processing")
    parser.add_argument("--models", action="store_true", help="List available Gemini models for current key")
    parser.add_argument("--reuse", action="store_true", help="Re-render from saved work HTML without API calls")
    parser.add_argument("--force", action="store_true", help="Regenerate lecture even if PDF exists")
    parser.add_argument("--status", action="store_true", help="Display book pagination status and integrity")
    parser.add_argument("--check", type=int, help="Run QA checks on an already generated lecture PDF")
    parser.add_argument("--diagnose", action="store_true", help="Run API diagnostic: verify each configured model with a minimal generateContent request")

    args = parser.parse_args()
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    tracker = PageTracker(output_dir)

    if args.status:
        display_status(tracker)
        return

    if args.models:
        cfg = GeminiConfig.from_env()
        client = GeminiClient(cfg)
        print("Available models supporting generateContent:")
        for m in client.client.models.list():
            if "generateContent" in (m.supported_actions or []):
                print(f"  - {m.name.replace('models/', '')}")
        return

    if args.diagnose:
        cfg = GeminiConfig.from_env()
        client = GeminiClient(cfg)
        print("\n=== API Model Diagnostic ===")
        print(f"API Key: {cfg.api_key[:4]}****{cfg.api_key[-4:]}")
        results = client.verify_models()
        for model_name, info in results.items():
            status_icon = "✓" if info.get("available") else "✗"
            print(f"  [{status_icon}] {info['role']}: {model_name} — {info['status']}")
        print("=" * 40)
        return

    if args.check is not None:
        lec_num = args.check
        recs = {r.lecture_num: r for r in tracker.get_verified_records()}
        rec = recs.get(lec_num)
        if not rec:
            print(f"[ERROR] Lecture {lec_num} is not recorded in {tracker.tracker_path.name}.")
            sys.exit(1)
        pdf_path = output_dir / rec.filename
        report = run_qa_checks(pdf_path, expected_start_page=rec.start_page)
        report.print_summary()
        sys.exit(0 if report.is_passed else 1)

    if not args.lectures:
        parser.print_help()
        sys.exit(1)

    first_str, _, last_str = args.lectures.partition("-")
    first_num = int(first_str)
    last_num = int(last_str) if last_str else first_num

    if args.list:
        for n in range(first_num, last_num + 1):
            src = discover_sources(REPO_DIR, n)
            print(src.get_summary())
        return

    # Initialize components
    renderer = PDFRenderer(STYLE_FILE)
    client = GeminiClient()

    for n in range(first_num, last_num + 1):
        success = run_lecture(
            lecture_num=n,
            tracker=tracker,
            renderer=renderer,
            client=client,
            output_dir=output_dir,
            reuse=args.reuse,
            force=args.force,
        )
        if not success:
            print(f"[STOP] Processing stopped at Lecture {n} due to errors.")
            sys.exit(1)


if __name__ == "__main__":
    main()
