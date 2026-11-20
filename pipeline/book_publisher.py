"""Final Book Publishing System for SpringNotes Forge.

Discovers completed, verified lecture PDFs, validates sequence integrity,
generates professional front matter (Cover, TOC, Learning Guide), stitches
supplements, attaches hierarchical PDF bookmarks, and atomically publishes
the complete master book.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pypdf
from pypdf import PdfReader, PdfWriter

from pipeline.pdf_renderer import PDFRenderer
from pipeline.tracker import PageTracker


@dataclass
class PublishingConfig:
    author: str = "Coder Army & SpringNotes Forge"
    edition: str = "2026 Master Reference Edition"
    title: str = "Spring Boot Complete Notes & Interview Guide"
    subject: str = "Spring Boot Learning and Interview Preparation"
    keywords: str = "Java, Spring, Spring Boot, REST API, Hibernate, JPA, Interview Preparation"
    creator: str = "SpringNotes Forge Publishing System"
    output_dir: Path = field(default_factory=lambda: Path("output"))
    supplements_dir: Path = field(default_factory=lambda: Path("supplements"))
    work_dir: Path = field(default_factory=lambda: Path("work"))
    templates_dir: Path = field(default_factory=lambda: Path("templates"))
    dest_pdf: Path = field(default_factory=lambda: Path("dist/Spring_Boot_Complete_Notes.pdf"))


@dataclass
class LectureFileInfo:
    lecture_num: int
    title: str
    pdf_path: Path
    start_page: int
    end_page: int
    page_count: int
    headings: List[str] = field(default_factory=list)
    span_end: Optional[int] = None


class BookPublisher:
    """Orchestrates validation, front-matter rendering, PDF merging, bookmarking, and publishing."""

    # Curriculum Part Definitions for Bookmarks and Table of Contents
    CURRICULUM_PARTS = [
        (1, 8, "Part I: Spring Core & Dependency Injection", "Core IoC architecture, bean lifecycle, and configuration models."),
        (9, 21, "Part II: Spring Boot Fundamentals & Web MVC", "Auto-configuration, externalized properties, REST controllers, DTOs, and filters."),
        (22, 25, "Part III: Spring AOP & Proxy Architecture", "Cross-cutting concerns, pointcut expressions, and dynamic proxy mechanics."),
        (26, 34, "Part IV: Persistence, Hibernate & Transactions", "JDBC, JdbcTemplate, Hibernate ORM, entity mappings, and transaction propagation."),
        (35, 38, "Part V: Spring Security & JWT Architecture", "Authentication filter pipelines, database security, and stateless token authorization."),
        (39, 40, "Part VI: Advanced Integrations & Testing", "OAuth2/OIDC social authentication and automated JUnit/Mockito test strategies."),
    ]

    def __init__(self, config: Optional[PublishingConfig] = None):
        self.config = config or PublishingConfig()
        self.renderer = PDFRenderer("style.css")
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        self.config.dest_pdf.parent.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1. DISCOVERY & INTEGRITY AUDIT
    # -------------------------------------------------------------------------
    def discover_lectures(self) -> Tuple[List[LectureFileInfo], List[str]]:
        """Discovers, validates, and sorts all completed lecture PDFs strictly by lecture number."""
        issues: List[str] = []
        discovered_map: Dict[int, LectureFileInfo] = {}
        duplicate_records: List[str] = []

        # Load headings and metadata from page_tracker.json if present (READ-ONLY)
        tracker_file = self.config.output_dir / "page_tracker.json"
        tracker_data = {}
        if tracker_file.exists():
            try:
                with open(tracker_file, "r", encoding="utf-8") as f:
                    tracker_data = json.load(f).get("lectures", {})
            except Exception as e:
                issues.append(f"Could not read tracker file {tracker_file.name}: {e}")

        # Scan output directory for lecture PDFs
        all_pdfs = sorted(self.config.output_dir.glob("*.pdf"))
        lecture_pdfs = [
            p for p in all_pdfs
            if re.search(r"Lec_(\d+)", p.name, re.IGNORECASE)
        ]

        for pdf in lecture_pdfs:
            # Check readability and page count
            try:
                reader = PdfReader(str(pdf))
                num_pages = len(reader.pages)
                if num_pages == 0:
                    issues.append(f"PDF {pdf.name} contains 0 pages.")
                    continue
            except Exception as e:
                issues.append(f"Failed to read PDF {pdf.name}: {e}")
                continue

            # Extract lecture span
            span_m = re.search(r"Lec_(\d+)(?:-(\d+))?", pdf.name, re.IGNORECASE)
            if not span_m:
                continue
            lec_num = int(span_m.group(1))
            span_end = int(span_m.group(2)) if span_m.group(2) else None

            # Detect duplicate lecture records
            if lec_num in discovered_map:
                duplicate_records.append(
                    f"Duplicate lecture {lec_num} found: {pdf.name} conflicts with {discovered_map[lec_num].pdf_path.name}"
                )

            # Determine start and end pages from text or tracker
            tr_rec = tracker_data.get(str(lec_num))
            headings: List[str] = []
            title = pdf.stem.replace("Spring_Boot_Lec_", "").replace("_", " ")

            if tr_rec:
                start_page = tr_rec.get("start_page", 1)
                end_page = tr_rec.get("end_page", start_page + num_pages - 1)
                headings = tr_rec.get("headings", [])
                if tr_rec.get("title"):
                    title = tr_rec["title"]
                if tr_rec.get("lecture_span_end"):
                    span_end = tr_rec["lecture_span_end"]
            else:
                # Extract printed page labels from PDF text
                first_pg_text = reader.pages[0].extract_text() or ""
                last_pg_text = reader.pages[-1].extract_text() or ""
                first_nums = re.findall(r"Page\s+(\d+)", first_pg_text)
                last_nums = re.findall(r"Page\s+(\d+)", last_pg_text)
                start_page = int(first_nums[-1]) if first_nums else 1
                end_page = int(last_nums[-1]) if last_nums else (start_page + num_pages - 1)

                # Extract headings directly from text
                for pg in reader.pages:
                    for line in (pg.extract_text() or "").splitlines():
                        line = line.strip()
                        h_m = re.match(r"^(Lecture \d+ · .+|\d{1,2}\.\d{1,2} \S.+)$", line)
                        if h_m and h_m.group(1)[:90] not in headings:
                            headings.append(h_m.group(1)[:90])
                        t_m = re.search(r"Lecture \d+ · (.+)", line)
                        if t_m:
                            title = t_m.group(1).strip()

            info = LectureFileInfo(
                lecture_num=lec_num,
                title=title,
                pdf_path=pdf,
                start_page=start_page,
                end_page=end_page,
                page_count=num_pages,
                headings=headings,
                span_end=span_end,
            )
            discovered_map[lec_num] = info

        # Sort strictly by lecture number
        sorted_lectures = sorted(discovered_map.values(), key=lambda x: x.lecture_num)

        # Detect missing lectures across the span (expecting 1 to 40)
        covered_lectures = set()
        for l in sorted_lectures:
            if l.span_end:
                for n in range(l.lecture_num, l.span_end + 1):
                    covered_lectures.add(n)
            else:
                covered_lectures.add(l.lecture_num)

        max_lec = max(covered_lectures) if covered_lectures else 0
        missing = [n for n in range(1, max_lec + 1) if n not in covered_lectures]
        if missing:
            issues.append(f"Missing lecture numbers detected: {missing}")

        if duplicate_records:
            issues.extend(duplicate_records)

        # Verify printed page continuity
        prev_end = 0
        for l in sorted_lectures:
            if prev_end > 0 and l.start_page != prev_end + 1:
                issues.append(
                    f"Pagination discontinuity before Lecture {l.lecture_num}: "
                    f"previous ended at page {prev_end}, but Lecture {l.lecture_num} starts at page {l.start_page}."
                )
            expected_end = l.start_page + l.page_count - 1
            if l.end_page != expected_end:
                issues.append(
                    f"Page count mismatch in Lecture {l.lecture_num}: "
                    f"starts at {l.start_page}, count is {l.page_count}, recorded end is {l.end_page} (expected {expected_end})."
                )
            prev_end = l.end_page

        return sorted_lectures, issues

    def check_readiness(self) -> Dict[str, Any]:
        """Runs pre-flight verification of all book components."""
        lectures, issues = self.discover_lectures()
        supplements_found = {}
        for stype, fname in [
            ("revision", "Revision_Sheets.pdf"),
            ("theory", "Interview_Theory.pdf"),
            ("practical", "Interview_Practical.pdf"),
        ]:
            p = self.config.supplements_dir / fname
            if p.exists() and p.stat().st_size > 0:
                supplements_found[stype] = p

        templates_ok = (
            (self.config.templates_dir / "cover.html").exists()
            and (self.config.templates_dir / "toc.html").exists()
            and (self.config.templates_dir / "guide.html").exists()
        )
        if not templates_ok:
            issues.append("Required publishing HTML templates are missing in templates/ directory.")

        is_ready = len(issues) == 0 and len(lectures) > 0
        total_lecture_pages = sum(l.page_count for l in lectures)

        return {
            "is_ready": is_ready,
            "issues": issues,
            "lecture_count": len(lectures),
            "total_lecture_pages": total_lecture_pages,
            "supplements": supplements_found,
            "lectures": lectures,
        }

    # -------------------------------------------------------------------------
    # 2. FRONT MATTER RENDERING
    # -------------------------------------------------------------------------
    def render_cover(self) -> Path:
        """Renders the professional technical-book cover page."""
        template_file = self.config.templates_dir / "cover.html"
        cover_html = template_file.read_text(encoding="utf-8")
        cover_html = cover_html.replace("{{AUTHOR}}", self.config.author)
        cover_html = cover_html.replace("{{EDITION}}", self.config.edition)

        cover_raw_pdf = self.config.work_dir / "pub_cover.pdf"
        self.renderer.render_html_to_pdf(cover_html, cover_raw_pdf)
        return cover_raw_pdf

    def render_guide(self) -> Path:
        """Renders the Learning Guide ('How to Use This Book')."""
        template_file = self.config.templates_dir / "guide.html"
        guide_html = template_file.read_text(encoding="utf-8")
        guide_raw_pdf = self.config.work_dir / "pub_guide.pdf"
        self.renderer.render_html_to_pdf(guide_html, guide_raw_pdf)
        return guide_raw_pdf

    def render_divider(self, part_num: str, part_title: str, part_desc: str) -> Path:
        """Renders a section divider page for supplements."""
        template_file = self.config.templates_dir / "divider.html"
        html = template_file.read_text(encoding="utf-8")
        html = html.replace("{{PART_NUM}}", part_num)
        html = html.replace("{{PART_TITLE}}", part_title)
        html = html.replace("{{PART_DESC}}", part_desc)

        slug = re.sub(r"[^A-Za-z0-9]+", "_", part_title).strip("_")[:20]
        divider_pdf = self.config.work_dir / f"divider_{slug}.pdf"
        self.renderer.render_html_to_pdf(html, divider_pdf)
        return divider_pdf

    def generate_toc(
        self,
        lectures: List[LectureFileInfo],
        supplements: Dict[str, Path],
    ) -> Path:
        """Generates Table of Contents HTML and renders to PDF using actual printed page labels."""
        toc_lines = []

        # Front Matter
        toc_lines.append('<div class="toc-part-title">FRONT MATTER</div>')
        toc_lines.append(
            '<div class="toc-entry lecture-entry">'
            '<span class="toc-title">How to Use This Book</span>'
            '<span class="toc-dots"></span>'
            '<span class="toc-page">iii</span>'
            '</div>'
        )

        # Organize lectures into Curriculum Parts
        for start_lec, end_lec, part_title, _ in self.CURRICULUM_PARTS:
            part_lectures = [
                l for l in lectures
                if (start_lec <= l.lecture_num <= end_lec)
                or (l.span_end and (start_lec <= l.span_end <= end_lec))
            ]
            if not part_lectures:
                continue

            toc_lines.append(f'<div class="toc-part-title">{part_title.upper()}</div>')
            for l in part_lectures:
                lec_label = (
                    f"Lecture {l.lecture_num:02d}–{l.span_end:02d}"
                    if l.span_end
                    else f"Lecture {l.lecture_num:02d}"
                )
                toc_lines.append(
                    '<div class="toc-entry lecture-entry">'
                    f'<span class="toc-title">{lec_label} · {l.title}</span>'
                    '<span class="toc-dots"></span>'
                    f'<span class="toc-page">Page {l.start_page}</span>'
                    '</div>'
                )

                # Add major section headings (filter out duplicate titles or generic self-checks)
                for h in l.headings:
                    if re.match(r"^\d{1,2}\.\d{1,2}\s+\S+", h):
                        toc_lines.append(
                            '<div class="toc-entry section-entry">'
                            f'<span class="toc-title">{h}</span>'
                            '<span class="toc-dots"></span>'
                            f'<span class="toc-page">·</span>'
                            '</div>'
                        )

        # Educational Supplements
        if supplements:
            toc_lines.append('<div class="toc-part-title">EDUCATIONAL SUPPLEMENTS</div>')
            last_lec_end = lectures[-1].end_page if lectures else 238
            supp_page = last_lec_end + 1

            if "revision" in supplements:
                r_pages = len(PdfReader(str(supplements["revision"])).pages)
                toc_lines.append(
                    '<div class="toc-entry lecture-entry">'
                    '<span class="toc-title">Part VII: Spring Boot Master Revision Sheets (20 Categories)</span>'
                    '<span class="toc-dots"></span>'
                    f'<span class="toc-page">Page {supp_page}</span>'
                    '</div>'
                )
                supp_page += r_pages

            if "theory" in supplements:
                t_pages = len(PdfReader(str(supplements["theory"])).pages)
                toc_lines.append(
                    '<div class="toc-entry lecture-entry">'
                    '<span class="toc-title">Part VIII: Interview Questions — Theory (100+ Questions)</span>'
                    '<span class="toc-dots"></span>'
                    f'<span class="toc-page">Page {supp_page}</span>'
                    '</div>'
                )
                supp_page += t_pages

            if "practical" in supplements:
                toc_lines.append(
                    '<div class="toc-entry lecture-entry">'
                    '<span class="toc-title">Part IX: Interview Questions — Practical Workbook &amp; Code</span>'
                    '<span class="toc-dots"></span>'
                    f'<span class="toc-page">Page {supp_page}</span>'
                    '</div>'
                )

        template_file = self.config.templates_dir / "toc.html"
        toc_template = template_file.read_text(encoding="utf-8")
        full_toc_html = toc_template.replace("{{TOC_CONTENT}}", "\n".join(toc_lines))

        toc_raw_pdf = self.config.work_dir / "pub_toc.pdf"
        self.renderer.render_html_to_pdf(full_toc_html, toc_raw_pdf)
        return toc_raw_pdf

    # -------------------------------------------------------------------------
    # 3. MERGING, BOOKMARKING & ATOMIC PUBLISHING
    # -------------------------------------------------------------------------
    def publish(self, overwrite: bool = False) -> Path:
        """Executes full book publishing with PDF bookmarks, metadata, and safe atomic save."""
        readiness = self.check_readiness()
        if not readiness["is_ready"]:
            error_details = "\n  - ".join(readiness["issues"])
            raise RuntimeError(f"Publishing readiness check failed:\n  - {error_details}")

        dest_pdf = self.config.dest_pdf
        if dest_pdf.exists() and not overwrite:
            raise FileExistsError(
                f"Destination book already exists at {dest_pdf}. "
                "Use --overwrite or -f to replace with a safe backup."
            )

        print(f"\n{'='*25} PUBLISHING MASTER BOOK {'='*25}")
        print(f"Destination: {dest_pdf.resolve()}")
        print(f"Lectures: {len(readiness['lectures'])} ({readiness['total_lecture_pages']} pages)")
        print(f"Supplements: {list(readiness['supplements'].keys())}\n")

        # Step 1: Render Front Matter
        print("[1/5] Rendering Cover page...")
        cover_pdf = self.render_cover()

        print("[2/5] Rendering Learning Guide...")
        guide_pdf = self.render_guide()

        print("[3/5] Generating and rendering Table of Contents...")
        toc_pdf = self.generate_toc(readiness["lectures"], readiness["supplements"])

        # Step 2: Assemble sections in strict sequence
        # Front Matter -> Lectures -> Dividers & Supplements
        print("[4/5] Merging all documents and building clickable PDF bookmarks...")
        writer = PdfWriter()
        current_phys_page = 0

        # Helper to add pages and track physical page indices
        def append_doc(pdf_path: Path) -> Tuple[int, int]:
            nonlocal current_phys_page
            r = PdfReader(str(pdf_path))
            start_idx = current_phys_page
            for p in r.pages:
                writer.add_page(p)
                current_phys_page += 1
            return start_idx, len(r.pages)

        # 1. Front Matter Bookmarks
        front_bm = writer.add_outline_item(title="Front Matter", page_number=0)
        c_start, _ = append_doc(cover_pdf)
        writer.add_outline_item(title="Cover Page", page_number=c_start, parent=front_bm)

        t_start, _ = append_doc(toc_pdf)
        writer.add_outline_item(title="Table of Contents", page_number=t_start, parent=front_bm)

        g_start, _ = append_doc(guide_pdf)
        writer.add_outline_item(title="How to Use This Book", page_number=g_start, parent=front_bm)

        # 2. Curriculum Lectures with Part Headers and Section Sub-bookmarks
        lectures = readiness["lectures"]
        for start_lec, end_lec, part_title, _ in self.CURRICULUM_PARTS:
            part_lectures = [
                l for l in lectures
                if (start_lec <= l.lecture_num <= end_lec)
                or (l.span_end and (start_lec <= l.span_end <= end_lec))
            ]
            if not part_lectures:
                continue

            first_lec_start = current_phys_page
            part_bm = writer.add_outline_item(title=part_title, page_number=first_lec_start)

            for l in part_lectures:
                lec_phys_start, _ = append_doc(l.pdf_path)
                lec_label = (
                    f"Lecture {l.lecture_num:02d}–{l.span_end:02d}: {l.title} (Page {l.start_page})"
                    if l.span_end
                    else f"Lecture {l.lecture_num:02d}: {l.title} (Page {l.start_page})"
                )
                lec_bm = writer.add_outline_item(title=lec_label, page_number=lec_phys_start, parent=part_bm)

                # Add major section headings under each lecture
                for h in l.headings:
                    if re.match(r"^\d{1,2}\.\d{1,2}\s+\S+", h):
                        writer.add_outline_item(title=h, page_number=lec_phys_start, parent=lec_bm)

        # 3. Educational Supplements
        supplements = readiness["supplements"]
        if supplements:
            supp_bm = writer.add_outline_item(title="Educational Supplements", page_number=current_phys_page)

            if "revision" in supplements:
                div_rev = self.render_divider(
                    "PART VII",
                    "Revision Sheets",
                    "High-yield 20-category revision maps, core annotations, and architecture summaries.",
                )
                append_doc(div_rev)
                r_start, _ = append_doc(supplements["revision"])
                writer.add_outline_item(title="Part VII: Revision Sheets (20 Categories)", page_number=r_start, parent=supp_bm)

            if "theory" in supplements:
                div_th = self.render_divider(
                    "PART VIII",
                    "Interview Questions — Theory",
                    "Conceptual, scenario-based, and multi-concept questions covering Beginner, Intermediate, and Advanced tiers.",
                )
                append_doc(div_th)
                t_start, _ = append_doc(supplements["theory"])
                writer.add_outline_item(title="Part VIII: Interview Questions — Theory", page_number=t_start, parent=supp_bm)

            if "practical" in supplements:
                div_pr = self.render_divider(
                    "PART IX",
                    "Interview Questions — Practical",
                    "Production-grade coding exercises, DTO patterns, JPA relationships, and Security filter implementations.",
                )
                append_doc(div_pr)
                p_start, _ = append_doc(supplements["practical"])
                writer.add_outline_item(title="Part IX: Interview Questions — Practical", page_number=p_start, parent=supp_bm)

        # Step 3: Inject PDF Metadata
        print("[5/5] Injecting PDF metadata and saving atomically...")
        writer.add_metadata({
            "/Title": self.config.title,
            "/Author": self.config.author,
            "/Subject": self.config.subject,
            "/Keywords": self.config.keywords,
            "/Creator": self.config.creator,
        })

        # Step 4: Atomic Write & Safe Backup
        tmp_target = dest_pdf.with_suffix(".tmp.pdf")
        with open(tmp_target, "wb") as f:
            writer.write(f)

        if dest_pdf.exists():
            bak_path = dest_pdf.with_suffix(".bak.pdf")
            print(f"[BACKUP] Existing book backed up to {bak_path.name}")
            shutil.copy2(dest_pdf, bak_path)

        os.replace(tmp_target, dest_pdf)
        print(f"\n[SUCCESS] Master book published successfully: {dest_pdf.resolve()}")
        print(f"  - Total Physical Pages: {current_phys_page}")
        print(f"  - File Size: {dest_pdf.stat().st_size / (1024*1024):.2f} MB")
        return dest_pdf
