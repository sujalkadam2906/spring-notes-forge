"""Persistent Page Tracker and Lecture State Manager.

Ensures continuous page numbering across standalone lecture PDFs, detects
overlaps or gaps, tracks total page count against the 105–120 page editorial estimate
(125-page soft warning), and maintains a reusable index of covered headings.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pypdf import PdfReader


@dataclass
class LectureRecord:
    lecture_num: int
    title: str
    start_page: int
    end_page: int
    page_count: int
    filename: str
    status: str = "completed"
    verified: bool = True
    headings: List[str] = field(default_factory=list)
    lecture_span_end: Optional[int] = None  # For combined lectures like 1-2


class PageTracker:
    TRACKER_FILE = "page_tracker.json"
    BOOK_TARGET = 115
    HARD_CEILING = 125
    TOTAL_LECTURES = 40

    def __init__(self, output_dir: Path | str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tracker_path = self.output_dir / self.TRACKER_FILE
        self.data: Dict = self._load()

    def _load(self) -> Dict:
        if self.tracker_path.exists():
            try:
                with open(self.tracker_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARN] Failed to load {self.tracker_path}: {e}. Re-indexing.")
        # Bootstrap if tracker does not exist
        return self._bootstrap_from_disk()

    def _save(self) -> None:
        temp_path = self.tracker_path.with_suffix(".json.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, self.tracker_path)

    def _bootstrap_from_disk(self) -> Dict:
        """Inspects existing output PDFs and builds verified state."""
        records: Dict[str, dict] = {}
        pdf_files = sorted(self.output_dir.glob("*.pdf"), key=self._pdf_sort_key)

        for pdf in pdf_files:
            rec = self._inspect_pdf(pdf)
            if rec:
                key = str(rec.lecture_num)
                records[key] = asdict(rec)

        data = {
            "version": "1.0",
            "book_target": self.BOOK_TARGET,
            "hard_ceiling": self.HARD_CEILING,
            "total_lectures": self.TOTAL_LECTURES,
            "lectures": records,
        }
        self.data = data
        if records:
            self._save()
        return data

    @staticmethod
    def _pdf_sort_key(p: Path) -> int:
        m = re.search(r"Lec_(\d+)", p.name, re.IGNORECASE)
        return int(m.group(1)) if m else 999

    def _inspect_pdf(self, pdf: Path) -> Optional[LectureRecord]:
        try:
            reader = PdfReader(pdf)
            num_pages = len(reader.pages)
            if num_pages == 0:
                return None

            # Detect lecture number, optional span, and title
            span_m = re.search(r"Lec_(\d+)(?:-(\d+))?", pdf.name, re.IGNORECASE)
            if not span_m:
                return None
            lec_num = int(span_m.group(1))
            span_end = int(span_m.group(2)) if span_m.group(2) else None
            slug = pdf.stem

            # Extract headings and verified page numbers from text
            first_pg_text = reader.pages[0].extract_text() or ""
            last_pg_text = reader.pages[-1].extract_text() or ""

            first_nums = re.findall(r"Page\s+(\d+)", first_pg_text)
            last_nums = re.findall(r"Page\s+(\d+)", last_pg_text)

            # Fallback to cumulative numbering if stamped numbers not parsed
            start_page = int(first_nums[-1]) if first_nums else 1
            end_page = int(last_nums[-1]) if last_nums else (start_page + num_pages - 1)

            # Extract headings
            headings = []
            title = slug.replace("_", " ")
            for pg in reader.pages:
                for line in (pg.extract_text() or "").splitlines():
                    line = line.strip()
                    h_match = re.match(r"^(Lecture \d+ · .+|\d{1,2}\.\d{1,2} \S.+)$", line)
                    if h_match:
                        h_text = h_match.group(1)[:90]
                        if h_text not in headings:
                            headings.append(h_text)
                    title_match = re.search(r"Lecture \d+ · (.+)", line)
                    if title_match:
                        title = title_match.group(1).strip()

            return LectureRecord(
                lecture_num=lec_num,
                title=title,
                start_page=start_page,
                end_page=end_page,
                page_count=num_pages,
                filename=pdf.name,
                status="completed",
                verified=True,
                headings=headings,
                lecture_span_end=span_end,
            )
        except Exception as e:
            print(f"[WARN] Error reading {pdf.name}: {e}")
            return None

    def get_verified_records(self) -> List[LectureRecord]:
        """Returns sorted list of completed, verified lecture records."""
        recs = []
        for d in self.data.get("lectures", {}).values():
            recs.append(LectureRecord(**d))
        recs.sort(key=lambda r: r.start_page)
        return recs

    def get_last_completed_page(self, up_to_lecture: Optional[int] = None) -> int:
        """Returns the highest end_page among completed lectures strictly before up_to_lecture."""
        recs = self.get_verified_records()
        if not recs:
            return 0
        if up_to_lecture is None:
            return max(r.end_page for r in recs)

        prev = [r for r in recs if (r.lecture_span_end or r.lecture_num) < up_to_lecture]
        if not prev:
            return 0
        return max(r.end_page for r in prev)

    def get_next_start_page(self, lecture_num: int) -> int:
        """Calculates exact starting page for lecture_num.

        Enforces that preceding lectures are verified and continuous.
        """
        if lecture_num == 1:
            return 1

        recs = self.get_verified_records()
        # Find the immediate predecessor
        # Check if lecture 1-2 covers up to 2, etc.
        highest_prev = None
        for r in recs:
            effective_num = r.lecture_span_end if r.lecture_span_end else r.lecture_num
            if effective_num < lecture_num:
                if highest_prev is None or effective_num > (highest_prev.lecture_span_end or highest_prev.lecture_num):
                    highest_prev = r

        if not highest_prev:
            raise ValueError(f"Cannot determine starting page for Lecture {lecture_num}: no prior lectures completed.")

        # If previous lecture does not immediately precede (gap check)
        prev_effective = highest_prev.lecture_span_end or highest_prev.lecture_num
        if prev_effective < lecture_num - 1:
            raise ValueError(
                f"Page gap detected! Highest completed lecture is {prev_effective} "
                f"(ends on page {highest_prev.end_page}), but requested lecture is {lecture_num}. "
                f"Lectures between {prev_effective + 1} and {lecture_num - 1} are missing."
            )

        return highest_prev.end_page + 1

    def record_lecture(
        self,
        lecture_num: int,
        title: str,
        start_page: int,
        end_page: int,
        page_count: int,
        filename: str,
        headings: List[str],
        span_end: Optional[int] = None,
        status: str = "completed",
        verified: bool = True,
    ) -> None:
        """Atomically stores or updates a lecture record."""
        # Validate continuity before recording
        if lecture_num > 1:
            expected_start = self.get_next_start_page(lecture_num)
            if start_page != expected_start:
                raise ValueError(
                    f"Integrity error: Lecture {lecture_num} starting page {start_page} "
                    f"does not match expected continuous page {expected_start}."
                )

        rec = LectureRecord(
            lecture_num=lecture_num,
            title=title,
            start_page=start_page,
            end_page=end_page,
            page_count=page_count,
            filename=filename,
            status=status,
            verified=verified,
            headings=headings,
            lecture_span_end=span_end,
        )
        self.data.setdefault("lectures", {})[str(lecture_num)] = asdict(rec)
        self._save()

    def validate_integrity(self) -> Tuple[bool, List[str]]:
        """Validates that all recorded lectures form a strictly continuous page sequence."""
        issues = []
        recs = self.get_verified_records()
        if not recs:
            return True, ["No lectures recorded yet."]

        prev_end = 0
        for r in recs:
            if prev_end > 0 and r.start_page != prev_end + 1:
                issues.append(
                    f"Discontinuity before Lecture {r.lecture_num}: "
                    f"previous ended at {prev_end}, current starts at {r.start_page}."
                )
            expected_end = r.start_page + r.page_count - 1
            if r.end_page != expected_end:
                issues.append(
                    f"Page count mismatch in Lecture {r.lecture_num}: "
                    f"start={r.start_page}, count={r.page_count}, recorded end={r.end_page} (expected {expected_end})."
                )
            prev_end = r.end_page

        total_pages = prev_end
        if total_pages > self.HARD_CEILING:
            # Soft warning — book exceeding estimate is not an integrity failure
            print(
                f"[WARN] Book length ({total_pages} pages) exceeds the {self.HARD_CEILING}-page "
                f"editorial estimate. This is a warning, not a pagination error."
            )
            # Do NOT append to issues — this is not a gap/overlap/integrity failure

        return len(issues) == 0, issues

    def get_all_headings(self, up_to_lecture: Optional[int] = None) -> List[str]:
        """Returns all headings up to the specified lecture for cross-referencing."""
        recs = self.get_verified_records()
        headings = []
        for r in recs:
            if up_to_lecture is None or r.lecture_num < up_to_lecture:
                headings.extend(r.headings)
        return headings

    def get_budget_status(self, current_lecture: int) -> dict:
        """Calculates pages used and provides editorial guidance (not strict budget)."""
        recs = self.get_verified_records()
        used = max((r.end_page for r in recs), default=0)
        remaining_lectures = max(1, self.TOTAL_LECTURES - current_lecture + 1)
        pages_left = max(0, self.BOOK_TARGET - used)
        # Editorial guidance only — not a hard constraint
        suggested_per_lec = max(1, round(pages_left / remaining_lectures))

        return {
            "pages_used": used,
            "book_target": self.BOOK_TARGET,
            "hard_ceiling": self.HARD_CEILING,
            "pages_remaining_to_target": pages_left,
            "lectures_remaining": remaining_lectures,
            "recommended_pages_this_lecture": suggested_per_lec,
        }
