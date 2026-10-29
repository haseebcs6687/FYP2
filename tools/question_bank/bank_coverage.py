"""
=============================================================================
EduGen - Question Bank Coverage & Quota Calculator
=============================================================================
Analyzes BM25 coverage across all 44 canonical concepts and all prepared PDFs.

Phase 2D-fix-3 Updates:
  - Strict batch cap at strong_count // 2 (max 6) enforced across all steps.
  - Strict PACK_ALIASES borrowing: borrowed chunk MUST have >= 1 CORE anchor of target concept.
  - Relaxed floor: every concept gets >= 4 batches IF material allows.
    Otherwise marked THIN (given >= 2 only if >= 1 heading-hit chunk).
  - Explicit reporting of THIN concepts and concepts below 4 batches.
  - Generates docs/bank_coverage.md and data/bank_work/quotas.json.

Usage:
    python tools/question_bank/bank_coverage.py
=============================================================================
"""

import argparse
import json
import math
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
    _is_chunk_strong,
    all_core,
    build_concept_query,
    check_chunk_anchors,
    check_heading_hit,
    get_anchors,
    get_effective_ranges,
    get_page_hints,
    has_exact_keyword_phrase,
    split_anchors,
)
from tools.question_bank.bank_prepare import BM25Index


def compute_pdf_coverage(pdfshort: str, work_dir: Path) -> dict:
    """
    Computes coverage metrics for all concepts on a given PDF (Phase 2D-fix-6):
      - Gathers chunks inside TOC or human page hint ranges (effective_ranges).
      - Evaluates BM25 candidate chunks for anchor-strong criteria.
      - Chunks inside TOC/hint ranges count as STRONG.
      - TOC ranges allow cap = min(6, ceil(range_chunks / 4)) batches.
      - Anchor-based chunks capped at strong // 2 batches (max 6).
      - Weak if total strong < 2.
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
    range_chunk_counts = {}
    has_toc_or_hint_map = {}
    caps = {}

    for tag in CONCEPTS:
        eff_ranges, src = get_effective_ranges(pdfshort, tag, work_dir)
        range_cids = set()
        if eff_ranges:
            for cid, chunk in chunks_map.items():
                if any(max(chunk["page_start"], r[0]) <= min(chunk["page_end"], r[1]) for r in eff_ranges):
                    range_cids.add(cid)
        range_chunks = len(range_cids)
        range_chunk_counts[tag] = range_chunks

        anchors = get_anchors(tag)
        phrase_core, word_core, support_anchors = split_anchors(tag, anchors, idx.df, idx.doc_count)
        core_anchors = all_core(phrase_core, word_core)
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

            h_hit_text = check_heading_hit(chunk["text"], phrase_core, tag)
            h_hit = bool(h_hit_text)

            candidates.append({
                "chunk_id": doc_id,
                "score": score,
                "hits": hits,
                "hit_list": hit_list,
                "heading_hit": h_hit,
                "heading_text": h_hit_text or "",
                "chapter_following_hit": False,
                "text": chunk["text"],
            })

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
                effective_pc = phrase_core if phrase_core else core_anchors
                if any(a in effective_pc for a in nxt_hit_list):
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

        best = max(c["score"] for c in candidates) if candidates else 0.0
        best_scores[tag] = best
        h_hits = sum(1 for c in candidates if c["heading_hit"])

        strong_cids = set(range_cids)
        for c in candidates:
            if c["chunk_id"] in strong_cids:
                continue
            if _is_chunk_strong(c, phrase_core, word_core, best):
                strong_cids.add(c["chunk_id"])

        sorted_cand = sorted(candidates, key=lambda x: x["score"], reverse=True)
        raw_sums[tag] = sum(c["score"] for c in sorted_cand[:30])
        total_strong = len(strong_cids)
        strong_counts[tag] = total_strong
        heading_hit_counts[tag] = h_hits + range_chunks

        has_toc_or_hint = (range_chunks > 0)
        has_toc_or_hint_map[tag] = has_toc_or_hint

        if has_toc_or_hint:
            cap = min(6, math.ceil(range_chunks / 4))
            is_weak = (range_chunks < 2 and total_strong < 2)
        else:
            is_weak = (total_strong < 2)
            cap = 0 if is_weak else min(6, total_strong // 2)

        caps[tag] = cap

    max_sum = max(raw_sums.values()) if raw_sums and max(raw_sums.values()) > 0 else 1.0

    for tag in CONCEPTS:
        norm_top30 = (raw_sums[tag] / max_sum) * 100.0
        strong = strong_counts[tag]
        cov = round(norm_top30 + strong, 1)
        h_cnt = heading_hit_counts[tag]

        concept_metrics[tag] = {
            "best_score": round(best_scores.get(tag, 0.0), 2),
            "raw_sum": round(raw_sums.get(tag, 0.0), 2),
            "norm_top30": round(norm_top30, 2),
            "strong": strong,
            "coverage": cov,
            "weak": (strong < 2),
            "heading_hits": h_cnt,
            "cap": caps.get(tag, 0),
            "has_toc_or_hint": has_toc_or_hint_map.get(tag, False),
            "range_chunks": range_chunk_counts.get(tag, 0),
        }

    return concept_metrics


def allocate_quotas(
    coverage_data: dict,
    target_per_pdf: int = 84,
    min_total: int = 4,
    max_per_concept: int = 6,
) -> dict:
    """
    Distributes batch quotas per PDF (Phase 2D-fix-6 rules):
      - Concepts with TOC/hint sections get cap = min(6, ceil(range_chunks/4)) and >= 2 batches if material allows.
      - Anchor-only concepts capped at strong // 2.
      - Weak concepts (< 2 strong) get 0 batches.
      - Goal: no concept at 0 batches, total target near 252.
    """
    pdfs = sorted(list(coverage_data.keys()))
    quotas = {pdf: {c: {"batches": 0, "borrowed": False, "thin": False} for c in CONCEPTS} for pdf in pdfs}

    target_total = target_per_pdf * len(pdfs)
    pdf_caps = {
        p: {
            c: coverage_data[p][c].get(
                "cap",
                (0 if coverage_data[p][c].get("weak") else min(max_per_concept, coverage_data[p][c]["strong"] // 2))
            )
            for c in CONCEPTS
        }
        for p in pdfs
    }

    pdf_targets = {p: min(target_per_pdf, sum(pdf_caps[p][c] for c in CONCEPTS)) for p in pdfs}
    rem_total = target_total - sum(pdf_targets.values())
    if rem_total > 0:
        for p in pdfs:
            room = sum(pdf_caps[p][c] for c in CONCEPTS) - pdf_targets[p]
            if room > 0:
                add = min(room, math.ceil(rem_total / 2))
                pdf_targets[p] += add
                rem_total -= add
                if rem_total <= 0:
                    break

    for pdf in pdfs:
        pdf_data = coverage_data[pdf]
        target_p = pdf_targets[pdf]
        caps = pdf_caps[pdf]
        eligible = [c for c in CONCEPTS if caps[c] >= 1]
        if not eligible:
            continue

        for c in eligible:
            if pdf_data[c].get("has_toc_or_hint") and caps[c] >= 2:
                quotas[pdf][c]["batches"] = 2
            else:
                quotas[pdf][c]["batches"] = 1

        current = sum(quotas[pdf][c]["batches"] for c in eligible)
        rem = target_p - current
        if rem > 0:
            total_cov = sum(pdf_data[c]["coverage"] for c in eligible)
            if total_cov > 0:
                floats = {c: (pdf_data[c]["coverage"] / total_cov) * rem for c in eligible}
                adds = {c: int(floats[c]) for c in eligible}
                leftover = rem - sum(adds.values())
                remainders = sorted(eligible, key=lambda c: floats[c] - adds[c], reverse=True)
                for i in range(leftover):
                    adds[remainders[i]] += 1
                for c in eligible:
                    quotas[pdf][c]["batches"] = min(caps[c], quotas[pdf][c]["batches"] + adds[c])

        current = sum(quotas[pdf][c]["batches"] for c in CONCEPTS)
        while current < target_p:
            cand = [c for c in sorted(eligible, key=lambda c: pdf_data[c]["coverage"], reverse=True) if quotas[pdf][c]["batches"] < caps[c]]
            if not cand:
                break
            quotas[pdf][cand[0]]["batches"] += 1
            current += 1

        while current > target_p:
            cand = [c for c in sorted(eligible, key=lambda c: pdf_data[c]["coverage"]) if quotas[pdf][c]["batches"] > 1]
            if not cand:
                break
            quotas[pdf][cand[0]]["batches"] -= 1
            current -= 1

    # Cross-PDF balancing: ensure min_total (4) where possible, and >= 2 for all concepts with capacity
    for min_floor in [2, min_total]:
        for tag in CONCEPTS:
            tot = sum(quotas[p][tag]["batches"] for p in pdfs)
            while tot < min_floor:
                eligible_pdfs = [
                    p for p in pdfs
                    if not coverage_data[p][tag].get("weak", False) and quotas[p][tag]["batches"] < pdf_caps[p][tag]
                ]
                if not eligible_pdfs:
                    break
                best_pdf = max(eligible_pdfs, key=lambda p: coverage_data[p][tag]["coverage"])
                donors = [
                    c for c in sorted(CONCEPTS, key=lambda c: coverage_data[best_pdf][c]["coverage"])
                    if quotas[best_pdf][c]["batches"] > 1 and sum(quotas[x][c]["batches"] for x in pdfs) > min_floor
                ]
                if not donors:
                    break
                donor = donors[0]
                quotas[best_pdf][donor]["batches"] -= 1
                quotas[best_pdf][tag]["batches"] += 1
                tot = sum(quotas[x][tag]["batches"] for x in pdfs)

    # Mark THIN concepts (< 4 batches total)
    for tag in CONCEPTS:
        tot = sum(quotas[pdf][tag]["batches"] for pdf in pdfs)
        if tot < min_total:
            for pdf in pdfs:
                quotas[pdf][tag]["thin"] = True

    return quotas


def generate_coverage_markdown(
    coverage_data: dict,
    quotas: dict,
    output_path: Path,
    thin_concepts: list[str],
    below_min_concepts: list[str],
    borrowed_concepts: list[str],
):
    """Writes docs/bank_coverage.md documenting coverage, flags, and quotas."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(list(coverage_data.keys()))

    lines = []
    lines.append("# Question Bank Source Coverage & Batch Quotas")
    lines.append("")
    lines.append("> Auto-generated report on textbook source coverage, strong chunks, and quota distribution (Phase 2D-fix-6: TOC-based section mapping).")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- **Total Canonical Concepts:** {len(CONCEPTS)}")
    lines.append(f"- **Source Textbooks:** {len(pdfs)} ({', '.join(pdfs)})")
    total_batches = sum(sum(quotas[pdf][c]["batches"] for c in CONCEPTS) for pdf in pdfs)
    total_questions = total_batches * 12
    lines.append(f"- **Total Target Batches:** {total_batches} ({total_questions:,} total questions, 12 MCQs / batch)")
    lines.append("")

    if borrowed_concepts:
        lines.append("### Concepts Utilizing Strict PACK_ALIASES Borrowing")
        lines.append("> ℹ️ The following concepts utilized strictly verified cross-concept borrowing (`PACK_ALIASES` chunks containing target CORE anchors):")
        for c in borrowed_concepts:
            b_details = []
            for p in pdfs:
                if quotas[p][c]["borrowed"]:
                    src = quotas[p][c].get("source_concept", "")
                    src_str = f" from `{src}`" if src else ""
                    b_details.append(f"{p}: {quotas[p][c]['batches']} batches (borrowed{src_str})")
            lines.append(f"- `{c}`: {', '.join(b_details)}")
        lines.append("")
    else:
        lines.append("### Concepts Utilizing Strict PACK_ALIASES Borrowing")
        lines.append("No concepts relied on cross-concept borrowing.")
        lines.append("")

    if thin_concepts:
        lines.append("### THIN Concepts (Source Material Limitations)")
        lines.append("> ⚠️ The following concepts have limited textbook material across the corpus and are marked **THIN**:")
        for c in thin_concepts:
            tot = sum(quotas[p][c]["batches"] for p in pdfs)
            hh = sum(coverage_data[p][c]["heading_hits"] for p in pdfs)
            lines.append(f"- `{c}`: Total = **{tot} batches** ({tot * 12} MCQs) | Heading Hits = {hh}")
        lines.append("")

    if below_min_concepts:
        lines.append("### Concepts Below 4 Batches Total")
        lines.append("> ⚠️ The following concepts could not reach 4 batches total due to strict source chunk caps (`strong_count // 2`):")
        for c in below_min_concepts:
            tot = sum(quotas[p][c]["batches"] for p in pdfs)
            lines.append(f"- `{c}`: Total = **{tot} batches**")
        lines.append("")
    else:
        lines.append("### Concepts Below 4 Batches Total")
        lines.append("All 44 concepts successfully meet or exceed the target of 4 batches total.")
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
        thin_badge = " *(THIN)*" if any(quotas[p][tag]["thin"] for p in pdfs) else ""
        row.append(f"**{tag_tot}**{thin_badge}")
        row.append(f"{tag_tot * 12}")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("---")
    lines.append("*Legend: Cov = Coverage Score; s = strong chunks; b = allocated batches (12 MCQs each); 🔄 / * = borrowed batch; THIN = limited source material.*")

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

    print("Allocating batch quotas (enforcing strong // 2 cap, relaxed floor)...")
    quotas = allocate_quotas(coverage_data, target_per_pdf=84, min_total=4, max_per_concept=6)

    # Check real borrowing from packs
    from tools.question_bank.bank_pack import build_pack
    for pdf in pdfs:
        for c in CONCEPTS:
            if quotas[pdf][c]["batches"] > 0:
                pack = build_pack(pdf, c, batch_idx=0, work_dir=work_dir)
                if pack.borrowed:
                    quotas[pdf][c]["borrowed"] = True
                    quotas[pdf][c]["source_concept"] = pack.source_concept

    # Check totals, thin concepts, and below min
    totals = {tag: sum(quotas[pdf][tag]["batches"] for pdf in pdfs) for tag in CONCEPTS}
    thin = [tag for tag in CONCEPTS if any(quotas[p][tag]["thin"] for p in pdfs)]
    below_min = [tag for tag, tot in totals.items() if tot < 4]
    borrowed = [tag for tag in CONCEPTS if any(quotas[p][tag]["borrowed"] for p in pdfs)]

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(quotas, f, indent=2)
    print(f"Saved quotas to {out_json}")

    generate_coverage_markdown(coverage_data, quotas, out_md, thin, below_min, borrowed)
    print(f"Saved coverage report to {out_md}")

    print("\n" + "=" * 65)
    print("  Coverage & Quota Summary (Phase 2D-fix-6)")
    print("=" * 65)
    for pdf in pdfs:
        allocated = sum(quotas[pdf][c]["batches"] for c in CONCEPTS)
        weak_count = sum(1 for d in coverage_data[pdf].values() if d["weak"])
        print(f"  {pdf:<28}: {allocated:>3} batches | {weak_count} weak concepts")
    total_b = sum(totals.values())
    print(f"  Total Batches: {total_b} ({total_b * 12} MCQs)")
    print(f"  Concepts relying on borrowing: {borrowed if borrowed else 'None'}")
    print(f"  THIN concepts (< 4 batches): {thin if thin else 'None'}")
    print(f"  Concepts below 4 batches total: {below_min if below_min else 'None (all >= 4)'}")
    print("=" * 65)


if __name__ == "__main__":
    main()

