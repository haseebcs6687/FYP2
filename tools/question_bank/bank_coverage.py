"""
=============================================================================
EduGen - Question Bank Coverage & Quota Calculator
=============================================================================
Analyzes BM25 coverage across all 44 canonical concepts and all prepared PDFs.
Incorporates Phase 2D-fix-2 updates:
  - CORE vs SUPPORT anchor splitting (PDF document frequency < 3% threshold)
  - No 1-anchor x3 strong rule
  - HEADING HIT detection with same-chapter propagation
  - Weak rule: strong_count < 3 (or < 2 if heading hit)
  - Batch caps: min(6, strong_count // 2)
  - PACK_ALIASES borrowing for concepts with total_strong < 8 to reach 4 batches
  - Quotas file with {"batches": int, "borrowed": bool}
  - Generates docs/bank_coverage.md and data/bank_work/quotas.json

Usage:
    python tools/question_bank/bank_coverage.py
=============================================================================
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.concepts import CONCEPTS, MODULE_CONCEPTS, MODULES
from tools.question_bank.bank_pack import (
    ANCHOR_EXTRA,
    GENERIC_SUPPORT_WORDS,
    PACK_ALIASES,
    build_concept_query,
    check_chunk_anchors,
    check_heading_hit,
    get_anchors,
    has_exact_keyword_phrase,
    split_anchors,
)
from tools.question_bank.bank_prepare import BM25Index


def compute_pdf_coverage(pdfshort: str, work_dir: Path) -> dict:
    """
    Computes BM25 metrics for all concepts on a given PDF:
      - Filters chunks for candidate status (>= 1 anchor hit)
      - Identifies strong chunks:
          * (>= 1 CORE anchor hit) AND (>= 2 distinct anchors OR CORE anchor appears >= 2 times)
            AND (score >= 40% best score)
          * OR chunk has a HEADING HIT (or is one of next 3 chunks of chapter with >= 1 CORE anchor).
      - Weak rule: strong_count < 3 (or < 2 if heading hit).
      - Returns concept metrics dictionary.
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

    chunk_ids_in_order = sorted(chunks_map.keys())
    id_to_order = {cid: i for i, cid in enumerate(chunk_ids_in_order)}

    concept_metrics = {}
    raw_sums = {}
    strong_counts = {}
    best_scores = {}
    heading_hit_counts = {}

    for tag in CONCEPTS:
        anchors = get_anchors(tag)
        core_anchors, support_anchors = split_anchors(tag, anchors, idx.df, idx.doc_count)
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

            h_hit = check_heading_hit(chunk["text"], core_anchors, tag)

            candidates.append({
                "chunk_id": doc_id,
                "score": score,
                "hits": hits,
                "hit_list": hit_list,
                "heading_hit": h_hit,
                "chapter_following_hit": False,
                "text": chunk["text"],
            })

        if len(candidates) < 3:
            raw_sums[tag] = 0.0
            strong_counts[tag] = 0
            best_scores[tag] = 0.0
            heading_hit_counts[tag] = 0
            continue

        cand_map = {c["chunk_id"]: c for c in candidates}

        # Propagate heading hit to next 3 chunks of same chapter if >= 1 CORE anchor
        for c in list(candidates):
            if not c["heading_hit"]:
                continue
            c_order = id_to_order.get(c["chunk_id"])
            if c_order is None:
                continue
            for step in (1, 2, 3):
                nxt_idx = c_order + step
                if nxt_idx >= len(chunk_ids_in_order):
                    break
                nxt_cid = chunk_ids_in_order[nxt_idx]
                nxt_c = chunks_map.get(nxt_cid)
                if not nxt_c:
                    continue
                if re.match(r"^(?:chapter\s+\d+|#+\s+chapter)", nxt_c["text"][:100].lower()):
                    break  # new chapter started

                nxt_hits, nxt_hit_list = check_chunk_anchors(nxt_c["text_lower"], anchors)
                if any(a in core_anchors for a in nxt_hit_list):
                    if nxt_cid in cand_map:
                        cand_map[nxt_cid]["chapter_following_hit"] = True
                    else:
                        cand_entry = {
                            "chunk_id": nxt_cid,
                            "score": raw_scores.get(nxt_cid, 1.0),
                            "hits": nxt_hits,
                            "hit_list": nxt_hit_list,
                            "heading_hit": False,
                            "chapter_following_hit": True,
                            "text": nxt_c["text"],
                        }
                        candidates.append(cand_entry)
                        cand_map[nxt_cid] = cand_entry

        best = max(c["score"] for c in candidates)
        best_scores[tag] = best
        h_hits = sum(1 for c in candidates if c["heading_hit"])
        heading_hit_counts[tag] = h_hits

        strong = []
        for c in candidates:
            is_strong = False
            if c["heading_hit"] or c["chapter_following_hit"]:
                is_strong = True
            else:
                c_core_hits = [a for a in c["hit_list"] if a in core_anchors]
                if len(c_core_hits) >= 1:
                    dist_ok = (len(c["hit_list"]) >= 2) or any(c["hits"][a] >= 2 for a in c_core_hits)
                    sc_ok = (c["score"] >= 0.40 * best)
                    if dist_ok and sc_ok:
                        is_strong = True

            if is_strong:
                strong.append(c)

        sorted_cand = sorted(candidates, key=lambda x: x["score"], reverse=True)
        raw_sums[tag] = sum(c["score"] for c in sorted_cand[:30])
        strong_counts[tag] = len(strong)

    max_sum = max(raw_sums.values()) if raw_sums and max(raw_sums.values()) > 0 else 1.0

    for tag in CONCEPTS:
        norm_top30 = (raw_sums[tag] / max_sum) * 100.0
        strong = strong_counts[tag]
        cov = round(norm_top30 + strong, 1)
        h_cnt = heading_hit_counts[tag]

        # Rule 5: weak only if strong < 3. If heading hit, min strong for non-weak is 2.
        is_weak = (strong < 2) if h_cnt > 0 else (strong < 3)

        concept_metrics[tag] = {
            "best_score": round(best_scores[tag], 2),
            "raw_sum": round(raw_sums[tag], 2),
            "norm_top30": round(norm_top30, 2),
            "strong": strong,
            "coverage": cov,
            "weak": is_weak,
            "heading_hits": h_cnt,
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
      - 0 batches for weak concepts on that PDF.
      - Batches for a (pdf, concept) are capped at min(max_per_concept, strong // 2).
      - Proportional to coverage score among eligible non-weak concepts.
      - Concepts with total_strong < 8 across all PDFs may borrow chunks from PACK_ALIASES
        to reach min_total (4) batches.
      - Quota format per concept: {"batches": int, "borrowed": bool}
    """
    pdfs = sorted(list(coverage_data.keys()))
    # Initialize quotas structure
    quotas = {pdf: {c: {"batches": 0, "borrowed": False} for c in CONCEPTS} for pdf in pdfs}

    for pdf in pdfs:
        pdf_data = coverage_data[pdf]
        # Non-weak concepts with strong // 2 >= 1
        eligible = [c for c in CONCEPTS if not pdf_data[c]["weak"] and (pdf_data[c]["strong"] // 2) >= 1]
        if not eligible:
            continue

        # Initial allocation: 1 batch each for eligible concepts
        for c in eligible:
            quotas[pdf][c]["batches"] = 1

        remaining = target_per_pdf - len(eligible)
        if remaining > 0:
            total_cov = sum(pdf_data[c]["coverage"] for c in eligible)
            floats = {c: (pdf_data[c]["coverage"] / total_cov) * remaining for c in eligible}
            additions = {c: int(floats[c]) for c in eligible}
            leftover = remaining - sum(additions.values())

            remainders = sorted(eligible, key=lambda c: floats[c] - additions[c], reverse=True)
            for i in range(leftover):
                additions[remainders[i]] += 1

            for c in eligible:
                cap = min(max_per_concept, pdf_data[c]["strong"] // 2)
                alloc = quotas[pdf][c]["batches"] + additions[c]
                quotas[pdf][c]["batches"] = min(cap, max(1, alloc))

        # Adjust up to target_per_pdf within caps
        current_total = sum(quotas[pdf][c]["batches"] for c in CONCEPTS)
        while current_total < target_per_pdf:
            candidates = [
                c for c in sorted(eligible, key=lambda c: pdf_data[c]["coverage"], reverse=True)
                if quotas[pdf][c]["batches"] < min(max_per_concept, pdf_data[c]["strong"] // 2)
            ]
            if not candidates:
                # If all reached cap, allow highest coverage non-weak concepts up to max_per_concept
                candidates = [
                    c for c in sorted(eligible, key=lambda c: pdf_data[c]["coverage"], reverse=True)
                    if quotas[pdf][c]["batches"] < max_per_concept
                ]
            if not candidates:
                break
            quotas[pdf][candidates[0]]["batches"] += 1
            current_total += 1

        # Adjust down to target_per_pdf if over
        while current_total > target_per_pdf:
            candidates = [
                c for c in sorted(eligible, key=lambda c: pdf_data[c]["coverage"])
                if quotas[pdf][c]["batches"] > 1
            ]
            if not candidates:
                break
            quotas[pdf][candidates[0]]["batches"] -= 1
            current_total -= 1

    # Cross-PDF guarantee: ensure every concept reaches at least min_total across all PDFs
    # Step 1: Native reallocation among non-weak PDFs
    for tag in CONCEPTS:
        tot = sum(quotas[pdf][tag]["batches"] for pdf in pdfs)
        while tot < min_total:
            eligible_pdfs = [
                p for p in pdfs
                if not coverage_data[p][tag]["weak"] and
                quotas[p][tag]["batches"] < min(max_per_concept, max(2, coverage_data[p][tag]["strong"] // 2))
            ]
            if not eligible_pdfs:
                break

            best_pdf = max(eligible_pdfs, key=lambda p: coverage_data[p][tag]["coverage"])
            donors = [
                c for c in sorted(CONCEPTS, key=lambda c: coverage_data[best_pdf][c]["coverage"])
                if quotas[best_pdf][c]["batches"] > 1 and sum(quotas[p][c]["batches"] for p in pdfs) > min_total
            ]
            if not donors:
                break

            donor = donors[0]
            quotas[best_pdf][donor]["batches"] -= 1
            quotas[best_pdf][tag]["batches"] += 1
            tot = sum(quotas[p][tag]["batches"] for p in pdfs)

    # Step 2: Borrowing mechanism via PACK_ALIASES for concepts that cannot reach min_total natively
    for tag in CONCEPTS:
        tot = sum(quotas[pdf][tag]["batches"] for pdf in pdfs)
        total_strong = sum(coverage_data[pdf][tag]["strong"] for pdf in pdfs)

        if tot < min_total and tag in PACK_ALIASES:
            deficit = min_total - tot
            aliases = PACK_ALIASES[tag]

            # Find PDFs with strong alias material
            for alias in aliases:
                if deficit <= 0:
                    break
                for p in pdfs:
                    if deficit <= 0:
                        break
                    if coverage_data[p][alias]["strong"] >= 4 and quotas[p][tag]["batches"] == 0:
                        # Find a donor in PDF p with surplus
                        donors = [
                            c for c in sorted(CONCEPTS, key=lambda c: coverage_data[p][c]["coverage"], reverse=True)
                            if quotas[p][c]["batches"] > 1 and sum(quotas[x][c]["batches"] for x in pdfs) > min_total
                        ]
                        for donor in donors:
                            surplus = min(quotas[p][donor]["batches"] - 1, sum(quotas[x][donor]["batches"] for x in pdfs) - min_total)
                            if surplus <= 0:
                                continue
                            borrow_amount = min(deficit, surplus)
                            quotas[p][donor]["batches"] -= borrow_amount
                            quotas[p][tag]["batches"] += borrow_amount
                            quotas[p][tag]["borrowed"] = True
                            deficit -= borrow_amount
                            if deficit <= 0:
                                break

    return quotas


def generate_coverage_markdown(
    coverage_data: dict,
    quotas: dict,
    output_path: Path,
    below_min_concepts: list[str],
    borrowed_concepts: list[str],
):
    """Writes docs/bank_coverage.md documenting coverage, flags, and quotas."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(list(coverage_data.keys()))

    lines = []
    lines.append("# Question Bank Source Coverage & Batch Quotas")
    lines.append("")
    lines.append("> Auto-generated report on textbook source coverage, strong chunks, and quota distribution (Phase 2D-fix-2).")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- **Total Canonical Concepts:** {len(CONCEPTS)}")
    lines.append(f"- **Source Textbooks:** {len(pdfs)} ({', '.join(pdfs)})")
    lines.append(f"- **Batches per PDF:** 84 batches (12 questions / batch: 4 Easy, 4 Medium, 4 Hard)")
    total_batches = sum(sum(quotas[pdf][c]["batches"] for c in CONCEPTS) for pdf in pdfs)
    total_questions = total_batches * 12
    lines.append(f"- **Total Target Batches:** {total_batches} ({total_questions:,} total questions)")
    lines.append("")

    if borrowed_concepts:
        lines.append("### Concepts Utilizing PACK_ALIASES Borrowing")
        lines.append("> ℹ️ The following concepts reached their quota through cross-concept alias borrowing (`PACK_ALIASES`):")
        for c in borrowed_concepts:
            b_details = []
            for p in pdfs:
                if quotas[p][c]["borrowed"]:
                    b_details.append(f"{p}: {quotas[p][c]['batches']} batches (borrowed)")
            lines.append(f"- `{c}`: {', '.join(b_details)}")
        lines.append("")

    if below_min_concepts:
        lines.append("### Concepts Below 4 Batches Total")
        lines.append("> ⚠️ The following concepts could not reach the minimum threshold of 4 batches total across all books:")
        for c in below_min_concepts:
            tot = sum(quotas[p][c]["batches"] for p in pdfs)
            lines.append(f"- `{c}` (Total: {tot} batches)")
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
        tag_tot = sum(quotas[p][tag]["batches"] for p in pdfs)
        for pdf in pdfs:
            d = coverage_data[pdf][tag]
            b_entry = quotas[pdf][tag]
            b = b_entry["batches"]
            borrow_flag = "*" if b_entry["borrowed"] else ""
            cov_str = f"{d['coverage']}"
            if d["weak"] and b == 0:
                cell = f"⚠️ **{cov_str}** ({d['strong']}s / **0b**)"
            elif b_entry["borrowed"]:
                cell = f"🔄 {cov_str} ({d['strong']}s / **{b}b{borrow_flag}**)"
            else:
                cell = f"{cov_str} ({d['strong']}s / **{b}b**)"
            row.append(cell)
        row.append(f"**{tag_tot}**")
        row.append(f"{tag_tot * 12}")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("---")
    lines.append("*Legend: Cov = Coverage Score; s = strong chunks; b = allocated batches (12 MCQs each); 🔄 / * = borrowed batch via PACK_ALIASES.*")

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

    # Check totals and borrowed concepts
    totals = {tag: sum(quotas[pdf][tag]["batches"] for pdf in pdfs) for tag in CONCEPTS}
    below_min = [tag for tag, tot in totals.items() if tot < 4]
    borrowed = [tag for tag in CONCEPTS if any(quotas[p][tag]["borrowed"] for p in pdfs)]

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(quotas, f, indent=2)
    print(f"Saved quotas to {out_json}")

    generate_coverage_markdown(coverage_data, quotas, out_md, below_min, borrowed)
    print(f"Saved coverage report to {out_md}")

    print("\n" + "=" * 65)
    print("  Coverage & Quota Summary")
    print("=" * 65)
    for pdf in pdfs:
        allocated = sum(quotas[pdf][c]["batches"] for c in CONCEPTS)
        weak_count = sum(1 for d in coverage_data[pdf].values() if d["weak"])
        print(f"  {pdf:<28}: {allocated:>3} batches | {weak_count} weak concepts")
    total_b = sum(totals.values())
    print(f"  Total Batches: {total_b} ({total_b * 12} MCQs)")
    print(f"  Concepts relying on borrowing: {borrowed if borrowed else 'None'}")
    print(f"  Concepts below 4 batches total: {below_min if below_min else 'None (all >= 4)'}")
    print("=" * 65)


if __name__ == "__main__":
    main()
