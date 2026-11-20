"""CLI Driver for Educational Supplement Generation.

Generates high-yield Revision Sheets, Interview Theory Questions, and Interview
Practical Workbooks for SpringNotes Forge.

Usage:
  python build_supplements.py
  python build_supplements.py --reuse
  python build_supplements.py --type revision
  python build_supplements.py --type theory
  python build_supplements.py --type practical
  python build_supplements.py --out supplements
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure standard UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.supplement_generator import SupplementGenerator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SpringNotes Forge — Educational Supplement Generation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_supplements.py
  python build_supplements.py --reuse
  python build_supplements.py --type revision
  python build_supplements.py --type theory
  python build_supplements.py --type practical
  python build_supplements.py --out my_supplements
        """,
    )
    parser.add_argument(
        "--type",
        choices=["all", "revision", "theory", "practical"],
        default="all",
        help="Specify which educational supplement to generate (default: all)",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse cached HTML in work/ directory without recomputing content",
    )
    parser.add_argument(
        "--out",
        default="supplements",
        help="Destination directory for output supplement PDFs (default: supplements)",
    )
    parser.add_argument(
        "--work",
        default="work",
        help="Working directory for intermediate HTML caches (default: work)",
    )

    args = parser.parse_args()
    generator = SupplementGenerator(
        work_dir=args.work,
        output_dir=args.out,
    )

    source_count = generator.get_source_lecture_count()
    print(f"\n{'='*25} SPRINGNOTES FORGE SUPPLEMENT BUILDER {'='*25}")
    print(f"Discovered {source_count} source lectures available for grounding.")
    print(f"Target Directory: {Path(args.out).resolve()}")
    print(f"Mode: {'Reusing cached HTML' if args.reuse else 'Generating & validating fresh HTML'}\n")

    try:
        if args.type == "all":
            results = generator.build_all(reuse=args.reuse)
            print(f"\n[SUMMARY] Successfully built all {len(results)} educational supplements:")
            for k, p in results.items():
                print(f"  - {k.capitalize()}: {p.name}")
        else:
            pdf_path = generator.generate_supplement(args.type, reuse=args.reuse)
            print(f"\n[SUMMARY] Successfully built '{args.type}' supplement: {pdf_path.name}")
    except Exception as e:
        print(f"\n[ERROR] Supplement generation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
