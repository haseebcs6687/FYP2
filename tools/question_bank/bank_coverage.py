"""
=============================================================================
EduGen - Question Bank Coverage & Quota Calculator
=============================================================================
Analyzes BM25 coverage across all 44 canonical concepts and all prepared PDFs.
Generates docs/bank_coverage.md and data/bank_work/quotas.json.

Usage:
    python tools/question_bank/bank_coverage.py
=============================================================================
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.concepts import CONCEPTS, MODULE_CONCEPTS, MODULES
from tools.question_bank.bank_pack import (
    build_concept_query,
    check_chunk_anchors,
    get_anchors,
    has_exact_keyword_phrase,
)
from tools.question_bank.bank_prepare import BM25Index


def compute_pdf_coverage(pdfshort: str, work_dir: Path) -> dict:
    """
    Computes BM25 metrics for all concepts on a given PDF:
      - Filters chunks for candidate status (>= 1 anchor hit)
      - Identifies strong chunks (>= 2 distinct anchors OR 1 anchor >= 3 times, AND score >= 40% best score)
      - If fewer than 3 candidates: concept gets 0 raw sum and is marked weak (NO_MATERIAL)
      - Raw top-30 candidate sum
      - Strong chunks count
      - Weak flag (< 5 strong chunks)
    """
    index_file = work_dir / pdfshort / "bm25.pkl"
    chunks_file = work_dir / pdfshort / "chunks.jsonl"
    if not index_file.exists():
        raise FileNotFoundError(f"BM25 index not found: {index_file}. Run bank_prepare.py first.")
    if not chunks_file.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_file}. Run bank_prepare.py first.")

    idx = BM25Index.load(index_file)
    chunks_map = {}
    with open(chunks_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                item["text_lower"] = item["text"].lower()
                chunks_map[item["chunk_id"]] = item

    concept_metrics = {}
    raw_sums = {}
    strong_counts = {}
    best_scores = {}

    for tag in CONCEPTS:
        anchors = get_anchors(tag)
        query, keywords = build_concept_query(tag)
        raw_scores = dict(idx.score(query))

        candidates = []
        for doc_id, base_score in raw_scores.items():
            if base_score <= 0:
                continue
            chunk = chunks_map.get(doc_id)
            if not chunk:
                continue

            t_lower = chunk["text_lower"]
            hits, hit_list = check_chunk_anchors(t_lower, anchors)
            if not hit_list:
                continue

            score = base_score
            if has_exact_keyword_phrase(t_lower, keywords):
                score *= 1.20

            candidates.append({
                "chunk_id": doc_id,
                "score": score,
                "hits": hits,
                "hit_list": hit_list,
            })

        if len(candidates) < 3:
            raw_sums[tag] = 0.0
            strong_counts[tag] = 0
            best_scores[tag] = 0.0
            continue

        best = max(c["score"] for c in candidates)
        best_scores[tag] = best

        strong = [
            c for c in candidates
            if (len(c["hit_list"]) >= 2 or any(cnt >= 3 for cnt in c["hits"].values()))
            and (c["score"] >= 0.40 * best)
        ]
        sorted_cand = sorted(candidates, key=lambda x: x["score"], reverse=True)
        raw_sums[tag] = sum(c["score"] for c in sorted_cand[:30])
        strong_counts[tag] = len(strong)

    max_sum = max(raw_sums.values()) if raw_sums and max(raw_sums.values()) > 0 else 1.0

    for tag in CONCEPTS:
        norm_top30 = (raw_sums[tag] / max_sum) * 100.0
        strong = strong_counts[tag]
        cov = round(norm_top30 + strong, 1)
        concept_metrics[tag] = {
            "best_score": round(best_scores[tag], 2),
            "raw_sum": round(raw_sums[tag], 2),
            "norm_top30": round(norm_top30, 2),
            "strong": strong,
            "coverage": cov,
            "weak": strong < 5,
        }

    return concept_metrics


def allocate_quotas(
    coverage_data: dict,
    target_per_pdf: int = 84,
    min_total: int = 4,
    max_per_concept: int = 6,
) -> dict:
    """
    Distributes batches per PDF:
      - 84 batches per PDF (target ~1008 questions at 12 q/batch).
      - 0 batches for weak concepts.
      - Min 1, Max 6 for non-weak concepts.
      - Proportional to coverage score.
      - Post-balancing: ensures each concept has at least min_total (4) batches
        across all PDFs where feasible.
    """
    pdfs = sorted(list(coverage_data.keys()))
    quotas = {pdf: {} for pdf in pdfs}

    for pdf in pdfs:
        pdf_data = coverage_data[pdf]
        non_weak = [c for c, d in pdf_data.items() if not d["weak"]]
        weak = [c for c, d in pdf_data.items() if d["weak"]]

        for c in weak:
            quotas[pdf][c] = 0

        if not non_weak:
            continue

        # Each non-weak concept gets at least 1 batch
        for c in non_weak:
            quotas[pdf][c] = 1

        remaining = target_per_pdf - len(non_weak)
        total_cov = sum(pdf_data[c]["coverage"] for c in non_weak)

        # Largest remainder method for proportional allocation
        floats = {c: (pdf_data[c]["coverage"] / total_cov) * remaining for c in non_weak}
        additions = {c: int(floats[c]) for c in non_weak}
        leftover = remaining - sum(additions.values())

        remainders = sorted(non_weak, key=lambda c: floats[c] - additions[c], reverse=True)
        for i in range(leftover):
            additions[remainders[i]] += 1

        for c in non_weak:
            alloc = quotas[pdf][c] + additions[c]
            quotas[pdf][c] = min(max_per_concept, alloc)

        # Handle any discrepancies caused by the max_per_concept cap
        current_total = sum(quotas[pdf].values())
        while current_total < target_per_pdf:
            candidates = [
                c for c in sorted(non_weak, key=lambda c: pdf_data[c]["coverage"], reverse=True)
                if quotas[pdf][c] < max_per_concept
            ]
            if not candidates:
                break
            quotas[pdf][candidates[0]] += 1
            current_total += 1

        while current_total > target_per_pdf:
            candidates = [
                c for c in sorted(non_weak, key=lambda c: pdf_data[c]["coverage"])
                if quotas[pdf][c] > 1
            ]
            if not candidates:
                break
            quotas[pdf][candidates[0]] -= 1
            current_total -= 1

    # Cross-PDF guarantee: ensure every concept reaches at least min_total across all PDFs
    for tag in CONCEPTS:
        tot = sum(quotas[pdf].get(tag, 0) for pdf in pdfs)
        while tot < min_total:
            eligible_pdfs = [
                p for p in pdfs
                if not coverage_data[p][tag]["weak"] and quotas[p].get(tag, 0) < max_per_concept
            ]
            if not eligible_pdfs:
                break

            best_pdf = max(eligible_pdfs, key=lambda p: coverage_data[p][tag]["coverage"])
            donors = [
                c for c in sorted(CONCEPTS, key=lambda c: coverage_data[best_pdf][c]["coverage"])
                if quotas[best_pdf].get(c, 0) > 1 and sum(quotas[p].get(c, 0) for p in pdfs) > min_total
            ]
            if not donors:
                break

            donor = donors[0]
            quotas[best_pdf][donor] -= 1
            quotas[best_pdf][tag] += 1
            tot = sum(quotas[p].get(tag, 0) for p in pdfs)

    return quotas


def generate_coverage_markdown(
    coverage_data: dict,
    quotas: dict,
    output_path: Path,
    below_min_concepts: list[str],
):
    """Writes docs/bank_coverage.md documenting coverage, flags, and quotas."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(list(coverage_data.keys()))

    lines = []
    lines.append("# Question Bank Source Coverage & Batch Quotas")
    lines.append("")
    lines.append("> Auto-generated report on textbook source coverage, strong chunks, and quota distribution.")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- **Total Canonical Concepts:** {len(CONCEPTS)}")
    lines.append(f"- **Source Textbooks:** {len(pdfs)} ({', '.join(pdfs)})")
    lines.append(f"- **Batches per PDF:** 84 batches (12 questions / batch: 4 Easy, 4 Medium, 4 Hard)")
    total_batches = sum(sum(q.values()) for q in quotas.values())
    total_questions = total_batches * 12
    lines.append(f"- **Total Target Batches:** {total_batches} ({total_questions:,} total questions)")
    lines.append("")

    if below_min_concepts:
        lines.append("### Concepts Below 4 Batches Total")
        lines.append(f"> ⚠️ The following concepts could not reach the minimum threshold of 4 batches total across all books due to source coverage limitations:")
        for c in below_min_concepts:
            lines.append(f"- `{c}` (Total: {sum(quotas[p].get(c, 0) for p in pdfs)} batches)")
    else:
        lines.append("### Concepts Below 4 Batches Total")
        lines.append("All 44 concepts successfully meet or exceed the target minimum of 4 batches total across all textbooks.")
    lines.append("")

    lines.append("## Top & Weakest Covered Concepts Per Textbook")
    for pdf in pdfs:
        pdf_data = coverage_data[pdf]
        sorted_by_cov = sorted(CONCEPTS.keys(), key=lambda c: pdf_data[c]["coverage"], reverse=True)
        top8 = sorted_by_cov[:8]
        weak8 = sorted_by_cov[-8:]

        lines.append(f"### {pdf}")
        lines.append(f"- **8 Best Covered:**")
        for c in top8:
            d = pdf_data[c]
            lines.append(f"  - `{c}`: Coverage = {d['coverage']} ({d['strong']} strong chunks, norm top-30 = {d['norm_top30']}%)")
        lines.append(f"- **8 Weakest Covered:**")
        for c in weak8:
            d = pdf_data[c]
            flag = " [WEAK]" if d["weak"] else ""
            lines.append(f"  - `{c}`: Coverage = {d['coverage']} ({d['strong']} strong chunks, norm top-30 = {d['norm_top30']}%){flag}")
        lines.append("")

    lines.append("## Concept x Textbook Coverage & Quota Distribution Table")
    lines.append("")
    header = ["Concept Tag", "Module"]
    for pdf in pdfs:
        header.append(f"{pdf} (Cov / Strong / Batches)")
    header.append("Total Batches")
    header.append("Planned MCQs")

    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    for tag, meta in CONCEPTS.items():
        row = [f"`{tag}`", meta["module"]]
        tag_tot = sum(quotas[p].get(tag, 0) for p in pdfs)
        for pdf in pdfs:
            d = coverage_data[pdf][tag]
            b = quotas[pdf].get(tag, 0)
            cov_str = f"{d['coverage']}"
            if d["weak"]:
                cell = f"⚠️ **{cov_str}** ({d['strong']}s / **0b**)"
            else:
                cell = f"{cov_str} ({d['strong']}s / **{b}b**)"
            row.append(cell)
        row.append(f"**{tag_tot}**")
        row.append(f"{tag_tot * 12}")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("---")
    lines.append("*Legend: Cov = Coverage Score (normalised top-30 score + strong chunks); s = strong chunks; b = allocated batches (12 MCQs each).*")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Calculate bank coverage and generate batch quotas.")
    parser.add_argument("--work-dir", default="data/bank_work", help="Working directory containing indexed PDFs.")
    parser.add_argument("--out-md", default="docs/bank_coverage.md", help="Output Markdown report path.")
    parser.add_argument("--out-json", default="data/bank_work/quotas.json", help="Output quotas JSON path.")
    args = parser.parse_args()

    work_dir = BASE_DIR / args.work_dir
    out_md = BASE_DIR / args.out_md
    out_json = BASE_DIR / args.out_json

    pdf_dirs = [d for d in work_dir.iterdir() if d.is_dir() and (d / "bm25.pkl").exists()]
    if not pdf_dirs:
        print(f"No indexed PDFs found in {work_dir}. Run bank_prepare.py first.")
        return

    pdfs = sorted([d.name for d in pdf_dirs])
    print(f"Found {len(pdfs)} prepared PDFs: {', '.join(pdfs)}")

    coverage_data = {}
    for pdf in pdfs:
        print(f"Calculating coverage for {pdf}...")
        coverage_data[pdf] = compute_pdf_coverage(pdf, work_dir)

    print("Allocating batch quotas (target: 84 batches / PDF, min 4 total / concept)...")
    quotas = allocate_quotas(coverage_data, target_per_pdf=84, min_total=4, max_per_concept=6)

    # Check totals
    totals = {tag: sum(quotas[pdf].get(tag, 0) for pdf in pdfs) for tag in CONCEPTS}
    below_min = [tag for tag, tot in totals.items() if tot < 4]

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(quotas, f, indent=2)
    print(f"Saved quotas to {out_json}")

    generate_coverage_markdown(coverage_data, quotas, out_md, below_min)
    print(f"Saved coverage report to {out_md}")

    print("\n" + "=" * 65)
    print("  Coverage & Quota Summary")
    print("=" * 65)
    for pdf in pdfs:
        allocated = sum(quotas[pdf].values())
        weak_count = sum(1 for d in coverage_data[pdf].values() if d["weak"])
        print(f"  {pdf:<28}: {allocated:>3} batches | {weak_count} weak concepts")
    total_b = sum(totals.values())
    print(f"  Total Batches: {total_b} ({total_b * 12} MCQs)")
    print(f"  Concepts below 4 batches total: {below_min if below_min else 'None (all >= 4)'}")
    print("=" * 65)


if __name__ == "__main__":
    main()
