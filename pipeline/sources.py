"""Source discovery and classification for course lecture materials.

Identifies, classifies, and validates source files per lecture according to
the defined hierarchy:
  1. Primary: Instructor's handwritten / Excalidraw / iPad notes
  2. Secondary: Supplementary Notes.pdf
  3. Tertiary: PracticeQuestions.pdf
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pymupdf


@dataclass
class LectureSources:
    lecture_num: int
    folder: Path
    primary_pdf: Optional[Path] = None
    secondary_pdf: Optional[Path] = None
    practice_pdf: Optional[Path] = None
    supplementary_files: List[Path] = field(default_factory=list)

    @property
    def has_primary(self) -> bool:
        return self.primary_pdf is not None and self.primary_pdf.exists()

    @property
    def has_secondary(self) -> bool:
        return self.secondary_pdf is not None and self.secondary_pdf.exists()

    @property
    def has_practice(self) -> bool:
        return self.practice_pdf is not None and self.practice_pdf.exists()

    def all_source_files(self) -> List[Path]:
        files = []
        if self.primary_pdf:
            files.append(self.primary_pdf)
        if self.secondary_pdf:
            files.append(self.secondary_pdf)
        if self.practice_pdf:
            files.append(self.practice_pdf)
        files.extend(self.supplementary_files)
        return files

    def get_summary(self) -> str:
        lines = [f"Lecture {self.lecture_num:02d} Sources ({self.folder}):"]
        lines.append(f"  - Primary (Excalidraw/Handwritten): {self.primary_pdf.name if self.primary_pdf else 'NONE'}")
        lines.append(f"  - Secondary (Notes):               {self.secondary_pdf.name if self.secondary_pdf else 'NONE'}")
        lines.append(f"  - Tertiary (Practice Questions):   {self.practice_pdf.name if self.practice_pdf else 'NONE'}")
        if self.supplementary_files:
            lines.append(f"  - Other Files:                     {[f.name for f in self.supplementary_files]}")
        return "\n".join(lines)


def discover_sources(repo_dir: Path | str, lecture_num: int) -> LectureSources:
    """Discovers and categorizes source files for a given lecture.

    Handles inconsistent naming across all 40 lectures (e.g. 'Ipad-screens.pdf',
    'Ecalidraw-Notes.pdf', lowercase 'notes.pdf', etc.).
    """
    repo = Path(repo_dir)
    folder = repo / f"Lecture {lecture_num:02d}"
    if not folder.exists():
        fallback_folder = repo / f"Lecture {lecture_num}"
        if fallback_folder.exists():
            folder = fallback_folder
        else:
            raise FileNotFoundError(
                f"Lecture directory does not exist: {folder}. Please check repository path or run git pull."
            )

    # Find all PDFs excluding those in code build folders
    all_pdfs = [
        p for p in folder.rglob("*.pdf")
        if not any(part.lower() in ("target", ".mvn", "bin", "build") for part in p.parts)
        and "code" not in [part.lower() for part in p.parts]
    ]

    primary: Optional[Path] = None
    secondary: Optional[Path] = None
    practice: Optional[Path] = None
    other: List[Path] = []

    # Patterns for categorization
    primary_keywords = ("excalidraw", "ipad", "ecalidraw", "handwritten", "board")
    practice_keywords = ("practice", "question", "assignment", "quiz")

    for pdf in all_pdfs:
        name_lower = pdf.name.lower()
        if any(kw in name_lower for kw in primary_keywords):
            if primary is not None:
                raise ValueError(
                    f"Ambiguous primary sources found in {folder}: {primary.name} and {pdf.name}."
                )
            primary = pdf
        elif any(kw in name_lower for kw in practice_keywords):
            if practice is not None:
                raise ValueError(
                    f"Ambiguous practice questions found in {folder}: {practice.name} and {pdf.name}."
                )
            practice = pdf
        elif "note" in name_lower:
            if secondary is not None:
                raise ValueError(
                    f"Ambiguous supplementary notes found in {folder}: {secondary.name} and {pdf.name}."
                )
            secondary = pdf
        else:
            other.append(pdf)

    # Edge-case handling: Some lectures (e.g. Lec 10, Lec 13) lack Excalidraw notes
    if not primary and secondary:
        print(
            f"[INFO] Lecture {lecture_num:02d} has no handwritten/Excalidraw notes. "
            f"Using secondary notes ({secondary.name}) as main reference."
        )
    elif not primary and not secondary:
        raise FileNotFoundError(
            f"No usable note sources found for Lecture {lecture_num:02d} in {folder}."
        )

    return LectureSources(
        lecture_num=lecture_num,
        folder=folder,
        primary_pdf=primary,
        secondary_pdf=secondary,
        practice_pdf=practice,
        supplementary_files=other,
    )


def inspect_source_text(pdf_path: Path) -> dict:
    """Extracts text metrics from a PDF to determine if it is text-based or scanned/drawn."""
    try:
        doc = pymupdf.open(pdf_path)
        total_text = ""
        total_images = 0
        for page in doc:
            total_text += page.get_text()
            total_images += len(page.get_images())
        char_count = len(total_text.strip())
        is_drawn_or_scanned = char_count < 100 and total_images > 0
        return {
            "page_count": len(doc),
            "char_count": char_count,
            "image_count": total_images,
            "is_drawn_or_scanned": is_drawn_or_scanned,
        }
    except Exception as e:
        return {"error": str(e), "page_count": 0, "char_count": 0, "is_drawn_or_scanned": True}
