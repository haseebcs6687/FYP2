"""
=============================================================================
EduGen - Question Bank Generation Plan Builder (Phase 2E-a)
=============================================================================
Builds and maintains the 50-batch question generation plan in
data/bank_work/gen_plan.json.

Structure:
  50 batch entries:
    - Round 1 (P01..P44): one batch per concept (44 canonical concepts).
      * Pilot first: P01=method-overriding, P02=try-with-resources,
        P03=interface-basics, P04=abstraction-basics.
      * Remaining 40 concepts in module order from core.concepts.MODULES.
      * Highest quota PDF chosen (tie order: javanotes9, thinkjava2, JavaNotesForProfessionals).
      * Avoids chunk overlap > 50% with earlier entries.
      * javabeans has pack_concept='getters-setters' with custom focus line.
    - Round 2 (P45..P50): 6 extra batches for key foundation concepts:
      class-definition, constructor-basics, inheritance-basics, method-overriding,
      interface-basics, try-catch.
      * Uses a different PDF from Round 1 if available, else next batch_idx.

Usage:
    python tools/question_bank/gen_plan.py [--force]
=============================================================================
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.concepts import CONCEPTS, MODULE_CONCEPTS, MODULES
from tools.question_bank.bank_pack import build_pack

PLAN_FILE = BASE_DIR / "data" / "bank_work" / "gen_plan.json"
QUOTAS_FILE = BASE_DIR / "data" / "bank_work" / "quotas.json"

TIE_ORDER = ["javanotes9", "thinkjava2", "JavaNotesForProfessionals"]

PILOT_CONCEPTS = [
    "method-overriding",
    "try-with-resources",
    "interface-basics",
    "abstraction-basics",
]

ROUND2_CONCEPTS = [
    "class-definition",
    "constructor-basics",
    "inheritance-basics",
    "method-overriding",
    "interface-basics",
    "try-catch",
]


def load_quotas(path: Path = None) -> dict:
    q_file = path or QUOTAS_FILE
    if not q_file.exists():
        raise FileNotFoundError(f"Quotas file not found: {q_file}. Run bank_coverage.py first.")
    with open(q_file, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_best_pdf_and_batch(
    concept: str,
    pack_concept: str,
    quotas: dict,
    seen_entry_chunks: list[set[str]],
    prefer_different_pdf_from: str = None,
) -> tuple[str, int, set[str]]:
    """
    Selects best (pdf, batch_idx) for concept based on quotas, tie-order,
    and avoiding >50% chunk overlap with earlier entries.
    """
    candidates = []
    for pdf in TIE_ORDER:
        q = quotas.get(pdf, {}).get(pack_concept, {}).get("batches", 0)
        candidates.append((q, -TIE_ORDER.index(pdf), pdf))
    candidates.sort(reverse=True)

    # 1. First attempt: filter by prefer_different_pdf_from if specified
    for _, _, pdf in candidates:
        if prefer_different_pdf_from and pdf == prefer_different_pdf_from:
            continue
        max_batches = quotas.get(pdf, {}).get(pack_concept, {}).get("batches", 0)
        for b_idx in range(max(1, max_batches)):
            p = build_pack(pdf, pack_concept, batch_idx=b_idx)
            if p.status == "NO_MATERIAL" or len(p) == 0:
                continue
            c_ids = set(c["chunk_id"] for c in p)
            too_much_overlap = False
            for prev_ids in seen_entry_chunks:
                if len(c_ids) > 0 and len(c_ids & prev_ids) / len(c_ids) > 0.50:
                    too_much_overlap = True
                    break
            if not too_much_overlap:
                return pdf, b_idx, c_ids

    # 2. Second attempt: relax prefer_different_pdf_from
    if prefer_different_pdf_from:
        for _, _, pdf in candidates:
            max_batches = quotas.get(pdf, {}).get(pack_concept, {}).get("batches", 0)
            for b_idx in range(max(1, max_batches)):
                p = build_pack(pdf, pack_concept, batch_idx=b_idx)
                if p.status == "NO_MATERIAL" or len(p) == 0:
                    continue
                c_ids = set(c["chunk_id"] for c in p)
                too_much_overlap = False
                for prev_ids in seen_entry_chunks:
                    if len(c_ids) > 0 and len(c_ids & prev_ids) / len(c_ids) > 0.50:
                        too_much_overlap = True
                        break
                if not too_much_overlap:
                    return pdf, b_idx, c_ids

    # 3. Fallback: return highest-quota PDF that has any material
    for _, _, pdf in candidates:
        p = build_pack(pdf, pack_concept, batch_idx=0)
        if p.status != "NO_MATERIAL" and len(p) > 0:
            return pdf, 0, set(c["chunk_id"] for c in p)

    raise RuntimeError(f"Unable to find textbook material for concept '{concept}' (pack: '{pack_concept}')")


def build_generation_plan(quotas_path: Path = None) -> list[dict]:
    quotas = load_quotas(quotas_path)

    # Order Round 1 concepts: pilot first, then remaining in module order
    remaining_concepts = []
    for m in MODULES:
        for c in MODULE_CONCEPTS.get(m, []):
            if c not in PILOT_CONCEPTS:
                remaining_concepts.append(c)

    round1_concepts = PILOT_CONCEPTS + remaining_concepts
    entries = []
    seen_entry_chunks: list[set[str]] = []

    getters_setters_pdf = None
    for c in round1_concepts:
        pack_c = c
        focus = ""
        if c == "javabeans":
            pack_c = "getters-setters"
            focus = "JavaBeans convention: private fields, public no-arg constructor, getters/setters, Serializable, naming rules"
            pdf, b_idx, c_ids = pick_best_pdf_and_batch(
                c, pack_c, quotas, seen_entry_chunks, prefer_different_pdf_from=getters_setters_pdf
            )
        else:
            pdf, b_idx, c_ids = pick_best_pdf_and_batch(c, pack_c, quotas, seen_entry_chunks)
            if c == "getters-setters":
                getters_setters_pdf = pdf

        seen_entry_chunks.append(c_ids)
        plan_id = f"P{len(entries)+1:02d}"
        entries.append({
            "plan_id": plan_id,
            "pdf": pdf,
            "concept": c,
            "batch_idx": b_idx,
            "pack_concept": pack_c,
            "focus": focus,
            "status": "pending",
        })

    # Round 2: 6 extra batches
    round1_map = {e["concept"]: e["pdf"] for e in entries}
    for c in ROUND2_CONCEPTS:
        r1_pdf = round1_map[c]
        pdf, b_idx, c_ids = pick_best_pdf_and_batch(
            c, c, quotas, seen_entry_chunks, prefer_different_pdf_from=r1_pdf
        )
        seen_entry_chunks.append(c_ids)
        plan_id = f"P{len(entries)+1:02d}"
        entries.append({
            "plan_id": plan_id,
            "pdf": pdf,
            "concept": c,
            "batch_idx": b_idx,
            "pack_concept": c,
            "focus": "",
            "status": "pending",
        })

    return entries


def save_plan(entries: list[dict], out_path: Path = None, force: bool = False):
    p_file = out_path or PLAN_FILE
    p_file.parent.mkdir(parents=True, exist_ok=True)

    if p_file.exists() and not force:
        # Preserve status of existing done entries
        try:
            with open(p_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            status_map = {e["plan_id"]: e.get("status", "pending") for e in existing}
            for e in entries:
                if e["plan_id"] in status_map:
                    e["status"] = status_map[e["plan_id"]]
        except Exception:
            pass

    with open(p_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Build EduGen MCQ generation plan (50 batches).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing plan and reset statuses.")
    args = parser.parse_args()

    entries = build_generation_plan()
    save_plan(entries, force=args.force)

    print("=" * 70)
    print("EduGen - Question Bank Generation Plan (Phase 2E-a)")
    print("=" * 70)
    print(f"Total Plan Entries: {len(entries)}")
    print("Pilot Batches (P01..P04):")
    for e in entries[:4]:
        print(f"  [{e['plan_id']}] {e['concept']} | {e['pdf']} (batch {e['batch_idx']})")
    print("\nRound 2 Extra Batches (P45..P50):")
    for e in entries[-6:]:
        print(f"  [{e['plan_id']}] {e['concept']} | {e['pdf']} (batch {e['batch_idx']})")
    print(f"\nSaved generation plan to {PLAN_FILE}")


if __name__ == "__main__":
    main()
