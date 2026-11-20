"""CLI Driver for Publishing the Final Spring Boot Master Book.

Discovers completed, verified lecture PDFs, validates sequence integrity,
renders front matter, attaches supplements, adds clickable PDF bookmarks,
and atomically saves the final master book.

Usage:
  python publish_book.py
  python publish_book.py --check
  python publish_book.py --out dist/My_Spring_Boot_Book.pdf --overwrite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure standard UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.book_publisher import BookPublisher, PublishingConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SpringNotes Forge — Final Book Publishing System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python publish_book.py
  python publish_book.py --check
  python publish_book.py -o dist/Custom_Spring_Notes.pdf --overwrite
  python publish_book.py --author "Coder Army Team" --edition "2026 Edition"
        """,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Perform discovery and pre-flight integrity check without publishing",
    )
    parser.add_argument(
        "-o",
        "--out",
        default="dist/Spring_Boot_Complete_Notes.pdf",
        help="Destination path for final merged PDF (default: dist/Spring_Boot_Complete_Notes.pdf)",
    )
    parser.add_argument(
        "--overwrite",
        "-f",
        action="store_true",
        help="Safely overwrite existing destination PDF with a .bak backup",
    )
    parser.add_argument(
        "--author",
        default="Coder Army & SpringNotes Forge",
        help="Author name for cover and PDF metadata",
    )
    parser.add_argument(
        "--edition",
        default="2026 Master Reference Edition",
        help="Edition label displayed on the cover",
    )
    parser.add_argument(
        "--lectures-dir",
        default="output",
        help="Directory containing completed lecture PDFs (default: output)",
    )
    parser.add_argument(
        "--supplements-dir",
        default="supplements",
        help="Directory containing educational supplement PDFs (default: supplements)",
    )

    args = parser.parse_args()

    config = PublishingConfig(
        author=args.author,
        edition=args.edition,
        output_dir=Path(args.lectures_dir),
        supplements_dir=Path(args.supplements_dir),
        dest_pdf=Path(args.out),
    )

    publisher = BookPublisher(config)

    if args.check:
        print(f"\n{'='*25} PRE-FLIGHT PUBLISHING READINESS CHECK {'='*25}")
        readiness = publisher.check_readiness()
        status_label = "READY TO PUBLISH" if readiness["is_ready"] else "INTEGRITY ISSUES DETECTED"
        print(f"Readiness Status: {status_label}")
        print(f"Lectures Discovered: {readiness['lecture_count']}")
        print(f"Total Lecture Pages: {readiness['total_lecture_pages']}")
        print(f"Supplements Detected: {list(readiness['supplements'].keys())}")

        if readiness["issues"]:
            print("\n[ISSUES]:")
            for iss in readiness["issues"]:
                print(f"  - {iss}")
            sys.exit(1)
        else:
            print("\nAll 40 lecture PDFs form a strictly continuous, verified page sequence.")
            print("System is fully ready for publication.")
            sys.exit(0)

    try:
        final_pdf = publisher.publish(overwrite=args.overwrite)
        print(f"\n[DONE] Published book available at: {final_pdf.resolve()}")
    except Exception as e:
        print(f"\n[FATAL ERROR] Publishing failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
