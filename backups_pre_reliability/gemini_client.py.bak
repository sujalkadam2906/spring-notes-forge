"""Gemini API integration with model fallback, rate limit retry, and response validation.

Handles structured source hierarchy ingestion, File API lifecycle cleanup,
and rigorous output validation.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from pipeline.sources import LectureSources

load_dotenv()


def is_retriable_error(exc: Exception) -> Tuple[bool, str]:
    """Determines whether an exception is a temporary/retriable error.

    Returns:
        (is_retriable: bool, reason: str)
    """
    # 1. API errors with status code
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        # Temporary status codes: 429 (Rate Limit / Quota), 500, 502, 503, 504, 408
        if code in (429, 500, 502, 503, 504, 408):
            return True, f"HTTP {code} (temporary API error)"
        # Permanent client errors: 400, 401, 403, 404, etc.
        if code in (400, 401, 403, 404):
            return False, f"HTTP {code} (permanent client error)"
        if code is not None and 400 <= code < 500:
            return False, f"HTTP {code} (permanent client error)"
        if code is not None and code >= 500:
            return True, f"HTTP {code} (server error)"

    # 2. Connection and timeout errors
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True, f"Connection interruption ({type(exc).__name__})"

    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        if winerror in (10053, 10054, 10060, 10061) or errno in (10053, 10054, 10060, 10061):
            return True, f"Socket/Network error (WinError/errno {winerror or errno})"

    # 3. Text-based detection for network/transport drops and WinError 10053
    exc_str = str(exc).lower()
    transient_signatures = (
        "10053",
        "10054",
        "winerror 10053",
        "connection aborted",
        "connection reset",
        "connection closed",
        "remotedisconnected",
        "broken pipe",
        "timed out",
        "timeout",
        "network unreachable",
    )
    if any(sig in exc_str for sig in transient_signatures):
        return True, f"Connection interruption ({type(exc).__name__}: transient network issue)"

    return False, f"Non-retriable error ({type(exc).__name__})"


def calculate_backoff(attempt: int, base_sec: float = 15.0, max_sec: float = 120.0) -> float:
    """Calculates exponential backoff delay with random jitter.

    Formula: min(max_sec, base * 2^(attempt-1)) + jitter
    """
    exp_delay = base_sec * (2 ** (attempt - 1))
    capped_delay = min(max_sec, exp_delay)
    # Add uniform random jitter between 1.0s and 3.0s
    jitter = random.uniform(1.0, 3.0)
    return round(min(max_sec, capped_delay + jitter), 2)


@dataclass
class GeminiConfig:
    api_key: str
    primary_model: str
    fallback_model: str
    max_output_tokens: int = 60000
    temperature: float = 0.25
    max_retries: int = 5
    initial_backoff_sec: int = 15

    @classmethod
    def from_env(cls) -> GeminiConfig:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ValueError(
                "GEMINI_API_KEY is not configured in environment or .env file."
            )
        primary = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        fallback = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-4-hydrogen")
        max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "5"))
        initial_backoff = int(os.getenv("GEMINI_INITIAL_BACKOFF_SEC", "15"))
        return cls(
            api_key=key,
            primary_model=primary,
            fallback_model=fallback,
            max_retries=max_retries,
            initial_backoff_sec=initial_backoff,
        )


class GeminiClient:
    def __init__(self, config: Optional[GeminiConfig] = None):
        self.config = config or GeminiConfig.from_env()
        self.client = genai.Client(api_key=self.config.api_key)

    def verify_models(self) -> Dict[str, Dict[str, Any]]:
        """Verifies configured models against actual Gemini API and reports availability."""
        results: Dict[str, Dict[str, Any]] = {}
        for role, model_name in [("Primary", self.config.primary_model), ("Fallback", self.config.fallback_model)]:
            if not model_name:
                continue
            entry: Dict[str, Any] = {"role": role, "model": model_name, "available": False, "status": "unknown"}
            try:
                resp = self.client.models.generate_content(
                    model=model_name,
                    contents="Ping",
                )
                entry["available"] = True
                entry["status"] = "Accessible and operational"
            except errors.APIError as e:
                entry["code"] = e.code
                if e.code == 503:
                    entry["available"] = True
                    entry["status"] = "Accessible to account, but currently experiencing temporary HTTP 503 demand spikes"
                elif e.code == 404:
                    entry["available"] = False
                    entry["status"] = f"Unavailable (HTTP 404: {e.message or 'Model not found for this API version/endpoint'})"
                elif e.code == 429:
                    entry["available"] = False
                    entry["status"] = f"Quota exceeded (HTTP 429: {e.message or 'Resource exhausted'})"
                else:
                    entry["available"] = False
                    entry["status"] = f"HTTP {e.code}: {e.message or str(e)}"
            except Exception as e:
                entry["status"] = f"Error ({type(e).__name__}): {e}"
            results[model_name] = entry
        return results

    def prepare_content_parts(self, sources: LectureSources) -> Tuple[List[Any], List[str]]:
        """Uploads sources adhering to hierarchy and returns content parts and uploaded file names."""
        parts: List[Any] = []
        uploaded_remote_files: List[str] = []

        # 1. Primary Source
        if sources.primary_pdf:
            parts.append(
                f"=== PRIMARY SOURCE: Instructor's Handwritten / Excalidraw Notes ({sources.primary_pdf.name}) ===\n"
                "CRITICAL: Follow this document's teaching order, concept sequence, mental models, "
                "and diagrams as the primary foundation for the lecture."
            )
            up = self.client.files.upload(file=str(sources.primary_pdf))
            parts.append(up)
            uploaded_remote_files.append(up.name)

        # 2. Secondary Source
        if sources.secondary_pdf:
            parts.append(
                f"=== SECONDARY SOURCE: Instructor's Supplementary Notes ({sources.secondary_pdf.name}) ===\n"
                "Use this document to deepen explanations, verify exact technical definitions, "
                "and fill technical gaps without duplicating already clear primary concepts."
            )
            up = self.client.files.upload(file=str(sources.secondary_pdf))
            parts.append(up)
            uploaded_remote_files.append(up.name)

        # 3. Tertiary Source
        if sources.practice_pdf:
            parts.append(
                f"=== TERTIARY SOURCE: Practice Questions ({sources.practice_pdf.name}) ===\n"
                "Select 3 to 5 realistic, conceptual interview/self-check questions from this document. "
                "Do NOT invent questions."
            )
            up = self.client.files.upload(file=str(sources.practice_pdf))
            parts.append(up)
            uploaded_remote_files.append(up.name)

        return parts, uploaded_remote_files

    def cleanup_remote_files(self, file_names: List[str]) -> None:
        """Deletes uploaded files from Google Cloud to prevent quota/storage leaks."""
        for name in file_names:
            try:
                self.client.files.delete(name=name)
            except Exception as e:
                # Do not crash pipeline on cleanup failure
                print(f"[DEBUG] Could not delete remote file {name}: {e}")

    def generate_lecture_notes(
        self,
        lecture_num: int,
        sources: LectureSources,
        pages_so_far: int,
        target_pages: int,
        remaining_lectures: int,
        previous_headings: List[str],
        system_instruction: str,
        work_dir: Path,
    ) -> str:
        """Executes content generation with retries and fallback model support."""
        work_dir.mkdir(parents=True, exist_ok=True)
        parts, uploaded_files = self.prepare_content_parts(sources)

        # Prompt context
        headings_preview = "\n".join(f"- {h}" for h in previous_headings[-40:]) if previous_headings else "None (First lecture)"
        context_prompt = (
            f"Write Lecture {lecture_num} based on the provided source hierarchy.\n\n"
            f"BOOK PROGRESS & BUDGET:\n"
            f"- Total pages generated so far: {pages_so_far}\n"
            f"- Lectures remaining including this one: {remaining_lectures}\n"
            f"- TARGET LENGTH FOR THIS LECTURE: {target_pages} pages.\n"
            f"  (Keep text dense, concise, and compact so it cleanly renders within {target_pages} pages.)\n\n"
            f"PREVIOUSLY COVERED HEADINGS (Do NOT re-explain these; cross-reference if needed):\n"
            f"{headings_preview}\n\n"
            "Produce output strictly matching the formatting rules with <notes_html> and <issues>."
        )

        full_contents = parts + [context_prompt]
        cfg = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=self.config.max_output_tokens,
            temperature=self.config.temperature,
        )

        try:
            # Build list of distinct models to try
            models_to_try: List[str] = []
            if self.config.primary_model and self.config.primary_model.strip():
                models_to_try.append(self.config.primary_model.strip())
            if (
                self.config.fallback_model
                and self.config.fallback_model.strip()
                and self.config.fallback_model.strip() not in models_to_try
            ):
                models_to_try.append(self.config.fallback_model.strip())

            response_text: Optional[str] = None
            model_failures: Dict[str, str] = {}

            for model_name in models_to_try:
                is_primary = (model_name == self.config.primary_model)
                role = "Primary" if is_primary else "Fallback"
                print(f"[INFO] Requesting Lecture {lecture_num} generation using {role} model: {model_name}...")

                model_succeeded = False
                for attempt in range(1, self.config.max_retries + 1):
                    try:
                        resp = self.client.models.generate_content(
                            model=model_name,
                            contents=full_contents,
                            config=cfg,
                        )
                        # Check finish reason and response
                        self._validate_raw_response(resp)
                        response_text = resp.text or ""
                        model_succeeded = True
                        break
                    except Exception as e:
                        retriable, reason = is_retriable_error(e)
                        err_msg = getattr(e, "message", None) or str(e)
                        model_failures[model_name] = f"{reason} — {err_msg}"

                        if retriable and attempt < self.config.max_retries:
                            wait = calculate_backoff(attempt, self.config.initial_backoff_sec)
                            print(
                                f"[WARN] Temporary error on {role} model '{model_name}' ({reason}). "
                                f"Retrying in {wait}s (attempt {attempt}/{self.config.max_retries})..."
                            )
                            time.sleep(wait)
                        else:
                            if retriable:
                                print(
                                    f"[ERROR] {role} model '{model_name}' exhausted all "
                                    f"{self.config.max_retries} retries ({reason})."
                                )
                            else:
                                print(
                                    f"[ERROR] Permanent error on {role} model '{model_name}': {reason}. "
                                    f"Skipping retries for this model."
                                )
                            break

                if model_succeeded and response_text:
                    print(f"[SUCCESS] Generation succeeded using {role} model: {model_name}")
                    break

            if not response_text:
                summary_lines = [
                    f"  - Model '{m}': {fail_reason}"
                    for m, fail_reason in model_failures.items()
                ]
                summary_str = "\n".join(summary_lines)
                print(f"\n[ERROR] Generation failed for Lecture {lecture_num}. All attempted models failed:\n{summary_str}\n")
                raise RuntimeError(
                    f"Failed to generate Lecture {lecture_num} after trying models {models_to_try}.\n"
                    f"Failure details per model:\n{summary_str}"
                )

            # Save raw output
            raw_path = work_dir / f"lecture_{lecture_num:02d}_raw.txt"
            raw_path.write_text(response_text, encoding="utf-8")

            # Extract & Validate
            body = self.extract_and_validate_notes(response_text, lecture_num)
            return body

        finally:
            # Always clean up remote uploaded files
            if uploaded_files:
                self.cleanup_remote_files(uploaded_files)

    @staticmethod
    def _validate_raw_response(resp: Any) -> None:
        """Checks for empty response or token truncation."""
        if not resp:
            raise ValueError("Received empty response from Gemini API.")
        if hasattr(resp, "candidates") and resp.candidates:
            cand = resp.candidates[0]
            finish_reason = getattr(cand, "finish_reason", None)
            if finish_reason and str(finish_reason).upper() in ("MAX_TOKENS", "SAFETY", "RECITATION"):
                print(f"[WARN] Response finish_reason was: {finish_reason}")

    @staticmethod
    def extract_and_validate_notes(text: str, lecture_num: int) -> str:
        """Extracts HTML body from response and validates tags, diagrams, and structure."""
        m = re.search(r"<notes_html>(.*?)</notes_html>", text, re.S)
        if not m:
            raise ValueError(
                f"Model response did not contain <notes_html> tags. "
                f"Check work/lecture_{lecture_num:02d}_raw.txt for details."
            )

        issues = re.search(r"<issues>(.*?)</issues>", text, re.S)
        issues_text = issues.group(1).strip() if issues else "none reported"
        print(f"\n[REPORTED ISSUES FOR LECTURE {lecture_num}]:\n{issues_text}\n")

        body = m.group(1).strip()
        # Clean any accidental outer markdown code fence
        body = re.sub(r"^```\w*\s*|\s*```$", "", body).strip()

        # Structural HTML/SVG validations
        # 1. Title verification (accepts '·', ':', or '-' as separator)
        h1_m = re.search(r"<h1>(Lecture\s+\d+\s*[·:\-]\s*.*?)</h1>", body, re.IGNORECASE)
        if not h1_m:
            raise ValueError(
                f"Missing required <h1>Lecture {lecture_num} · Title</h1> at start of content."
            )

        # 2. SVG tag balance
        svg_open = len(re.findall(r"<svg\b", body, re.IGNORECASE))
        svg_close = len(re.findall(r"</svg>", body, re.IGNORECASE))
        if svg_open != svg_close:
            raise ValueError(
                f"Mismatched SVG tags in generated HTML: {svg_open} opening <svg> vs {svg_close} closing </svg>."
            )

        # 3. Table tag balance
        tbl_open = len(re.findall(r"<table\b", body, re.IGNORECASE))
        tbl_close = len(re.findall(r"</table>", body, re.IGNORECASE))
        if tbl_open != tbl_close:
            raise ValueError(
                f"Mismatched table tags: {tbl_open} opening <table> vs {tbl_close} closing </table>."
            )

        # 4. Div tag balance
        div_open = len(re.findall(r"<div\b", body, re.IGNORECASE))
        div_close = len(re.findall(r"</div>", body, re.IGNORECASE))
        if div_open != div_close:
            print(f"[WARN] Div tag imbalance: {div_open} opening <div> vs {div_close} closing </div>.")

        return body
