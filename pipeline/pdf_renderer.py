"""PDF rendering via Playwright (MS Edge) and ReportLab running header/footer stamping.

Ensures strict A4 portrait dimensions, clean CSS page-break behavior, and
continuous page numbering.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import pymupdf
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


class PDFRenderer:
    def __init__(self, style_path: Path | str = "style.css"):
        self.style_path = Path(style_path)
        if not self.style_path.exists():
            raise FileNotFoundError(f"Style file not found at {self.style_path}")
        self.css = self.style_path.read_text(encoding="utf-8")

    def build_full_html(self, body_html: str) -> str:
        """Wraps inner body HTML into a complete standards-compliant HTML document with print CSS."""
        return (
            "<!doctype html>\n"
            "<html lang='en'>\n"
            "<head>\n"
            "  <meta charset='utf-8'>\n"
            "  <meta name='viewport' content='width=device-width, initial-scale=1.0'>\n"
            f"  <style>\n{self.css}\n</style>\n"
            "</head>\n"
            f"<body>\n{body_html}\n</body>\n"
            "</html>"
        )

    def render_html_to_pdf(self, html_doc: str, raw_pdf_path: Path) -> Path:
        """Renders HTML to un-stamped PDF using Playwright (Microsoft Edge with Chromium fallback)."""
        raw_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge")
            except Exception:
                browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html_doc, wait_until="load")
            page.pdf(
                path=str(raw_pdf_path),
                prefer_css_page_size=True,
                print_background=True,
            )
            browser.close()
        return raw_pdf_path

    @staticmethod
    def stamp_running_headers_and_footers(
        raw_pdf_path: Path,
        final_pdf_path: Path,
        start_page: int,
    ) -> int:
        """Stamps continuous page numbers and running header/footer onto every page."""
        final_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        reader = PdfReader(str(raw_pdf_path))
        writer = PdfWriter()
        w, h = A4
        num_pages = len(reader.pages)

        for i, src_page in enumerate(reader.pages):
            page = writer.add_page(src_page)
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            c.setFont("Helvetica", 8.5)

            # Running Header
            c.drawString(18 * mm, h - 12 * mm, "Spring Boot Master Notes")
            c.drawRightString(w - 18 * mm, h - 12 * mm, "Coder Army Spring Boot Series")
            c.setLineWidth(0.4)
            c.line(18 * mm, h - 14 * mm, w - 18 * mm, h - 14 * mm)

            # Continuous Running Footer
            current_page_number = start_page + i
            c.drawCentredString(w / 2, 10 * mm, f"Page {current_page_number}")
            c.save()

            buf.seek(0)
            overlay = PdfReader(buf).pages[0]
            page.merge_page(overlay)

        # Write to temporary file first then replace for safe atomic write
        tmp_final = final_pdf_path.with_suffix(".tmp.pdf")
        with open(tmp_final, "wb") as f:
            writer.write(f)
        tmp_final.replace(final_pdf_path)

        return num_pages

    def generate_previews(self, pdf_path: Path, preview_dir: Path, dpi: int = 100) -> list[Path]:
        """Generates PNG images of each page for visual QA inspection."""
        preview_dir.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open(pdf_path)
        generated_images = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            out_img = preview_dir / f"page_{i + 1}.png"
            pix.save(str(out_img))
            generated_images.append(out_img)
        return generated_images

    def render_lecture_pdf(
        self,
        body_html: str,
        output_pdf_path: Path,
        start_page: int,
        work_dir: Path,
        preview_dir: Optional[Path] = None,
        dpi: int = 100,
    ) -> int:
        """Full pipeline: HTML -> Raw PDF -> Stamped Final PDF -> Previews."""
        work_dir.mkdir(parents=True, exist_ok=True)
        raw_pdf = work_dir / "tmp_raw_render.pdf"
        full_html = self.build_full_html(body_html)

        # 1. Playwright HTML -> PDF
        self.render_html_to_pdf(full_html, raw_pdf)

        # 2. ReportLab Stamping
        page_count = self.stamp_running_headers_and_footers(
            raw_pdf_path=raw_pdf,
            final_pdf_path=output_pdf_path,
            start_page=start_page,
        )

        # 3. Previews
        if preview_dir:
            self.generate_previews(output_pdf_path, preview_dir, dpi=dpi)

        return page_count
