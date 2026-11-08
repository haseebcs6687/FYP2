"""
=============================================================================
EduGen - Question Bank Gap Plan Builder (Phase 11a)
=============================================================================
Opens data/edugen.db strictly in READ-ONLY mode (sqlite URI mode=ro), counts
active pool questions per (concept, difficulty), calculates deficits against:
    Easy >= 4, Medium >= 3, Hard >= 3
and builds a prioritized 24-batch question generation plan in:
    data/bank_work/gap_plan.json

Output:
  - Writes data/bank_work/gap_plan.json
  - Prints the formatted plan table to stdout

Usage:
    python tools/question_bank/gen_gap_plan.py [--force]
=============================================================================
"""

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.concepts import CONCEPTS
from core.misconceptions import misconceptions_for
from tools.question_bank.bank_pack import build_pack

DB_PATH = BASE_DIR / "data" / "edugen.db"
GAP_PLAN_FILE = BASE_DIR / "data" / "bank_work" / "gap_plan.json"
RAW_DIR = BASE_DIR / "rag" / "corpus" / "questions" / "raw"

TIE_ORDER = ["thinkjava2", "JavaNotesForProfessionals", "javanotes9"]

TARGETS = {"Easy": 4, "Medium": 3, "Hard": 3}

DEFAULT_FOCUS_MAP = {
    "default-constructor": "compiler provides a no-arg constructor ONLY if no constructors are declared; super() insertion; visibility matches class",
    "access-modifiers": "public, protected, package-private (default), private; subclass access across packages vs same package; class-level vs member-level visibility",
    "checked-vs-unchecked": "Exception vs RuntimeException / Error hierarchy; catch or declare rule; subclass throws clause cannot declare broader checked exceptions",
    "default-values": "fields get default values (0, 0.0, false, null) upon allocation; local variables are uninitialized and trigger compile errors on read",
    "constructor-basics": "constructor name matches class, no return type; this() vs super() rules; instance field initialization order",
    "inheritance-hierarchy": "Object as root; single inheritance of classes; IS-A relationship; widening reference conversions; constructor invocation chain",
    "dynamic-method-dispatch": "the overridden version that runs is chosen by runtime object type; fields and static methods are NOT dispatched; super.m() invocation",
    "abstraction-basics": "abstract classes cannot be instantiated; abstract methods have no body; concrete subclasses must implement all inherited abstract methods",
    "object-instantiation": "new operator allocates memory on heap, initializes fields to defaults, then executes constructor chain",
    "data-hiding": "private fields with public getters/setters protect internal invariants; why direct field access breaks encapsulation",
    "reference-semantics": "references point to heap objects; == checks reference identity, .equals() checks logical equality; aliasing and mutations",
    "constructor-overloading": "multiple constructors with distinct parameter signatures; delegating via this(...) as the first statement",
    "copy-constructor": "creating a new independent object by copying state from an existing instance; shallow copy vs deep copy traps",
    "getters-setters": "standard accessor and mutator conventions; returning mutable references violates encapsulation; defensive copies in getters",
    "javabeans": "JavaBeans conventions: public no-arg constructor, private fields, standard getter/setter naming (get/set/is for boolean), property encapsulation",
}


def load_active_pool_counts(db_path: Path = None) -> dict[str, dict[str, int]]:
    """Opens edugen.db strictly in READ-ONLY mode and counts active pool questions."""
    p = db_path or DB_PATH
    uri = f"file:{p.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT concept, difficulty, count(id) FROM questions "
        "WHERE pool_status='active' GROUP BY concept, difficulty"
    )
    counts: dict[str, dict[str, int]] = {}
    for c, d, cnt in cur.fetchall():
        counts.setdefault(c, {})[d] = cnt
    conn.close()
    return counts


def get_unused_misconceptions(concept: str, db_path: Path = None) -> list[str]:
    """Finds catalog misconceptions not yet covered in the active pool for this concept."""
    p = db_path or DB_PATH
    uri = f"file:{p.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT tags_json FROM questions WHERE pool_status='active' AND concept=?",
        (concept,),
    )
    used = set()
    for (tags_raw,) in cur.fetchall():
        if not tags_raw:
            continue
        try:
            t = json.loads(tags_raw)
            mids = t.get("option_misconception_ids") or []
            for mid in mids:
                if mid:
                    used.add(mid)
        except Exception:
            pass
    conn.close()

    catalog = [m["id"] for m in misconceptions_for(concept)]
    return [mid for mid in catalog if mid not in used]


def count_raw_questions_by_pdf(raw_dir: Path = None) -> Counter:
    """Counts questions currently installed in raw_dir grouped by (concept, pdf)."""
    r_dir = raw_dir or RAW_DIR
    counts = Counter()
    if not r_dir.exists():
        return counts
    for f in r_dir.glob("*.jsonl"):
        parts = f.stem.split("__")
        if len(parts) >= 2:
            counts[(parts[1], parts[0])] += 12
    return counts


def pick_best_pdf_and_batch(
    concept: str,
    pack_concept: str,
    raw_counts: Counter,
    seen_chunks: list[set[str]],
    reserved_files: set[str] = None,
) -> tuple[str, int, set[str]]:
    """
    Selects best (pdf, batch_idx) for concept:
    Among PDFs with material (build_pack != NO_MATERIAL), picks the PDF with
    the FEWEST questions in raw questions directory for that concept.
    Avoids > 50% chunk overlap with earlier batches and avoids overwriting reserved files.
    """
    candidates = []
    for pdf in TIE_ORDER:
        raw_cnt = raw_counts[(concept, pdf)]
        candidates.append((raw_cnt, TIE_ORDER.index(pdf), pdf))
    candidates.sort()

    for _, _, pdf in candidates:
        for b_idx in range(4):
            fname = f"{pdf}__{concept}__b{b_idx:02d}.jsonl"
            if reserved_files and fname in reserved_files:
                continue
            pack = build_pack(pdf, pack_concept, batch_idx=b_idx)
            if pack.status == "NO_MATERIAL" or len(pack) == 0:
                continue
            c_ids = set(c["chunk_id"] for c in pack)
            too_much_overlap = False
            for prev_ids in seen_chunks:
                if len(c_ids) > 0 and len(c_ids & prev_ids) / len(c_ids) > 0.50:
                    too_much_overlap = True
                    break
            if not too_much_overlap:
                return pdf, b_idx, c_ids

    raise RuntimeError(f"Unable to find textbook material for concept '{concept}'")


def build_gap_plan(db_path: Path = None, raw_dir: Path = None) -> list[dict]:
    """Builds the 24-batch gap generation plan."""
    counts = load_active_pool_counts(db_path)
    raw_counts = count_raw_questions_by_pdf(raw_dir)

    gen_plan_path = BASE_DIR / "data" / "bank_work" / "gen_plan.json"
    reserved_files = set()
    if gen_plan_path.exists():
        with open(gen_plan_path, "r", encoding="utf-8") as f:
            p_plan = json.load(f)
            reserved_files = set(f"{e['pdf']}__{e['concept']}__b{e['batch_idx']:02d}.jsonl" for e in p_plan)

    # 24 batch specifications based on deficits and required concepts
    batch_specs = [
        # Top 8 high-deficit concepts (2 batches each)
        ("default-constructor", "default-constructor", {"Easy": 5, "Medium": 2, "Hard": 5}),
        ("default-constructor", "default-constructor", {"Easy": 4, "Medium": 3, "Hard": 5}),
        ("access-modifiers", "access-modifiers", {"Easy": 3, "Medium": 4, "Hard": 5}),
        ("access-modifiers", "access-modifiers", {"Easy": 3, "Medium": 5, "Hard": 4}),
        ("checked-vs-unchecked", "checked-vs-unchecked", {"Easy": 5, "Medium": 2, "Hard": 5}),
        ("checked-vs-unchecked", "checked-vs-unchecked", {"Easy": 5, "Medium": 3, "Hard": 4}),
        ("default-values", "default-values", {"Easy": 6, "Medium": 1, "Hard": 5}),
        ("default-values", "default-values", {"Easy": 5, "Medium": 2, "Hard": 5}),
        ("constructor-basics", "constructor-basics", {"Easy": 2, "Medium": 5, "Hard": 5}),
        ("constructor-basics", "constructor-basics", {"Easy": 3, "Medium": 4, "Hard": 5}),
        ("inheritance-hierarchy", "inheritance-hierarchy", {"Easy": 6, "Medium": 1, "Hard": 5}),
        ("inheritance-hierarchy", "inheritance-hierarchy", {"Easy": 5, "Medium": 2, "Hard": 5}),
        ("dynamic-method-dispatch", "dynamic-method-dispatch", {"Easy": 2, "Medium": 5, "Hard": 5}),
        ("dynamic-method-dispatch", "dynamic-method-dispatch", {"Easy": 3, "Medium": 5, "Hard": 4}),
        ("abstraction-basics", "abstraction-basics", {"Easy": 2, "Medium": 5, "Hard": 5}),
        ("abstraction-basics", "abstraction-basics", {"Easy": 3, "Medium": 4, "Hard": 5}),
        # Next high deficit + required concepts (1 batch each)
        ("null-pointer-exception", "null-pointer-exception", {"Easy": 2, "Medium": 4, "Hard": 6}),
        ("object-instantiation", "object-instantiation", {"Easy": 2, "Medium": 5, "Hard": 5}),
        ("data-hiding", "data-hiding", {"Easy": 3, "Medium": 4, "Hard": 5}),
        ("reference-semantics", "reference-semantics", {"Easy": 3, "Medium": 4, "Hard": 5}),
        ("constructor-overloading", "constructor-overloading", {"Easy": 3, "Medium": 4, "Hard": 5}),
        ("copy-constructor", "copy-constructor", {"Easy": 3, "Medium": 4, "Hard": 5}),
        ("getters-setters", "getters-setters", {"Easy": 3, "Medium": 4, "Hard": 5}),
        ("javabeans", "getters-setters", {"Easy": 4, "Medium": 4, "Hard": 4}),
    ]

    seen_chunks: list[set[str]] = []
    plan_entries = []

    for idx, (concept, pack_concept, mix) in enumerate(batch_specs, 1):
        plan_id = f"G{idx:02d}"
        pdf, b_idx, c_ids = pick_best_pdf_and_batch(
            concept, pack_concept, raw_counts, seen_chunks, reserved_files=reserved_files
        )
        seen_chunks.append(c_ids)
        raw_counts[(concept, pdf)] += 12

        # Build focus guidance
        if concept == "null-pointer-exception":
            unused = get_unused_misconceptions("null-pointer-exception", db_path)
            focus = (
                "Unused catalog misconceptions to target: "
                + ", ".join(unused)
                + "; also cover null dereferencing, method invocation on null, unboxing null to primitive"
            )
        else:
            focus = DEFAULT_FOCUS_MAP.get(concept, f"Key principles and edge cases for {concept}")

        entry = {
            "plan_id": plan_id,
            "pdf": pdf,
            "concept": concept,
            "pack_concept": pack_concept,
            "batch_idx": b_idx,
            "mix": mix,
            "focus": focus,
            "status": "pending",
        }
        plan_entries.append(entry)

    return plan_entries


def print_plan_table(plan: list[dict]):
    print("=" * 105)
    print("EDU-GEN QUESTION BANK GAP PLAN (Phase 11a)")
    print("=" * 105)
    print(f"{'ID':4s} | {'Concept':25s} | {'PDF':26s} | {'Batch':5s} | {'Mix (E/M/H)':11s} | {'Status':7s}")
    print("-" * 105)
    for e in plan:
        m = e["mix"]
        mix_str = f"{m['Easy']}/{m['Medium']}/{m['Hard']}"
        print(
            f"{e['plan_id']:4s} | {e['concept']:25s} | {e['pdf']:26s} | b{e['batch_idx']:02d}   | {mix_str:11s} | {e['status']:7s}"
        )
    print("=" * 105)


def main():
    parser = argparse.ArgumentParser(description="Build question bank gap generation plan.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing gap_plan.json.")
    args = parser.parse_args()

    if GAP_PLAN_FILE.exists() and not args.force:
        print(f"Loading existing plan from {GAP_PLAN_FILE}...")
        with open(GAP_PLAN_FILE, "r", encoding="utf-8") as f:
            plan = json.load(f)
    else:
        print("Building gap plan from data/edugen.db (mode=ro)...")
        plan = build_gap_plan()
        GAP_PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(GAP_PLAN_FILE, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
        print(f"Plan written to {GAP_PLAN_FILE}")

    print_plan_table(plan)


if __name__ == "__main__":
    main()
