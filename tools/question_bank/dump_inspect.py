"""
=============================================================================
EduGen - Question Bank Raw Inspect Report Generator
=============================================================================
Runs the exact --inspect code path for batch 0 across 12 key concepts and
all 3 textbooks, outputting unedited raw text (first 300 characters) to
data/bank_work/inspect_report.txt.

Usage:
    python tools/question_bank/dump_inspect.py
=============================================================================
"""

import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from tools.question_bank.bank_pack import build_pack

CONCEPTS_12 = [
    "method-overriding",
    "constructor-chaining",
    "dynamic-method-dispatch",
    "try-with-resources",
    "copy-constructor",
    "finally-block",
    "this-keyword",
    "static-members",
    "abstract-classes",
    "data-hiding",
    "immutability",
    "interface-basics",
]

PDFS = ["javanotes9", "JavaNotesForProfessionals", "thinkjava2"]


def generate_raw_inspect_report(output_file: Path):
    output_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []

    for concept in CONCEPTS_12:
        for pdf in PDFS:
            pack = build_pack(pdf, concept, batch_idx=0)

            if pack.status == "NO_MATERIAL" or len(pack) == 0:
                lines.append(f"\n[{pdf} | {concept}] NO_MATERIAL (candidates: {pack.candidate_count})")
                continue

            total_words = sum(c["words"] for c in pack)
            page_ranges = ", ".join(f"pp.{c['page_start']}-{c['page_end']}" for c in pack)

            lines.append("=" * 70)
            lines.append(f"  Source Pack: {concept} | PDF: {pdf} | Batch: 0")
            lines.append(f"  Status: {pack.status} | Strong Chunks: {pack.strong_count} | Candidates: {pack.candidate_count}")
            if pack.borrowed:
                lines.append(f"  [BORROWED] Material borrowed from related concept: {pack.source_concept}")
            lines.append(f"  Pack Chunks: {len(pack)} | Total words: {total_words} / 2200")
            lines.append(f"  Page ranges: {page_ranges}")
            lines.append("=" * 70)

            for i, c in enumerate(pack, 1):
                badges = []
                if c.get("is_strong"):
                    badges.append("[STRONG]")
                else:
                    badges.append("[CANDIDATE]")
                if c.get("is_hint"):
                    badges.append("[HINT]")
                if c.get("heading_hit"):
                    badges.append("[HEADING-HIT]")
                elif c.get("chapter_following_hit"):
                    badges.append("[CHAPTER-HIT]")
                if c.get("is_borrowed"):
                    badges.append(f"[BORROWED from {c.get('source_concept')}]")

                badge_str = " ".join(badges)
                anchors_hit = c.get("anchors_hit", [])
                core_hits = c.get("core_anchors_hit", [])
                supp_hits = c.get("support_anchors_hit", [])
                num_anchors = len(anchors_hit)

                # Raw unedited first 300 characters without ellipses or paraphrasing
                raw_300 = c["text"][:300]

                lines.append(f"\nChunk {i}: pp.{c['page_start']}-{c['page_end']} {badge_str}")
                lines.append(f"  Source Concept: {c.get('source_concept')}")
                lines.append(f"  Distinct Anchors ({num_anchors}):")
                lines.append(f"    CORE ({len(core_hits)}): {core_hits}")
                lines.append(f"    SUPPORT ({len(supp_hits)}): {supp_hits}")
                lines.append(f"  Score: {c['score']} | Words: {c['words']}")
                lines.append(f"  Text: {raw_300}")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Saved raw inspect report to {output_file}")


def main():
    out_file = BASE_DIR / "data" / "bank_work" / "inspect_report.txt"
    generate_raw_inspect_report(out_file)


if __name__ == "__main__":
    main()
