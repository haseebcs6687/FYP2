"""
=============================================================================
EduGen - Question Bank Generation Brief Generator (Phase 2E-a)
=============================================================================
Prints a self-contained generation brief for the next N pending plan entries
from data/bank_work/gen_plan.json.

Brief contents per batch:
  - Plan ID and target JSONL path
  - Concept title & summary
  - Complete list of catalog misconceptions for the concept
  - Focus guidance (if any)
  - Full source pack text with page numbers
  - Generation RULES verbatim

Usage:
    python tools/question_bank/gen_next.py [--n 1]
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

from core.concepts import CONCEPTS
from core.misconceptions import misconceptions_for
from tools.question_bank.bank_pack import build_pack

PLAN_FILE = BASE_DIR / "data" / "bank_work" / "gen_plan.json"

RULES_TEXT = """RULES that every generated question must follow:
- 12 MCQs per batch: 4 Easy (recall/recognition), 4 Medium (apply/predict short code), 4 Hard (multi-step reasoning, edge cases, hiding vs overriding style traps).
- Ground the question in the pack's concept; standard Java 17 semantics. If the pack is thin, use correct standard Java knowledge of the concept; never invent facts.
- Write your OWN wording and OWN code; never copy sentences or code from the book. Never refer to "the text/book/chapter/figure".
- Code: one self-contained snippet in ```java fences, compiles as a single file (class Main with main), deterministic (no input, threads, time, random, hash ordering). For code_output the explanation must state the exact output and trace it. bug_find: the explanation names the exact compile/runtime error.
- 4 distinct options, exactly one correct. Every wrong option carries a misconception_id from THIS concept's catalog list shown in the brief, chosen so that the wrong belief would really produce that option; distinct ids across the three wrong options when possible; at most one null.
- Explanation: why the correct option is right and why the main distractor is wrong. Balance correct_index over 0-3.
- SELF-AUDIT before saving: for every question trace the code / re-derive the answer; fix any doubtful question instead of keeping it."""


def get_target_filename(pdf: str, concept: str, batch_idx: int) -> str:
    return f"{pdf}__{concept}__b{batch_idx:02d}.jsonl"


def format_brief(entry: dict) -> str:
    plan_id = entry["plan_id"]
    pdf = entry["pdf"]
    concept = entry["concept"]
    batch_idx = entry["batch_idx"]
    pack_concept = entry.get("pack_concept", concept)
    focus = entry.get("focus", "")

    target_name = get_target_filename(pdf, concept, batch_idx)
    target_rel_path = f"rag/corpus/questions/raw/{target_name}"

    c_meta = CONCEPTS.get(concept, {})
    title = c_meta.get("title", concept)
    summary = c_meta.get("summary", "")

    misconceptions = misconceptions_for(concept)
    pack = build_pack(pdf, pack_concept, batch_idx=batch_idx, max_words=2200)

    lines = []
    lines.append("=" * 78)
    lines.append(f"QUESTION GENERATION BRIEF: {plan_id} ({concept} | {pdf} | batch {batch_idx:02d})")
    lines.append("=" * 78)
    lines.append(f"Target Output File : {target_rel_path}")
    lines.append(f"Concept Tag        : {concept}")
    lines.append(f"Concept Title      : {title}")
    lines.append(f"Concept Summary    : {summary}")
    if focus:
        lines.append(f"Specific Focus     : {focus}")
    lines.append("")

    lines.append("--- Misconception Catalog Entries (Use these IDs for wrong options) ---")
    if not misconceptions:
        lines.append("  (No catalog misconceptions found for this concept)")
    else:
        for idx, m in enumerate(misconceptions, 1):
            lines.append(f"{idx}. ID: {m['id']}")
            lines.append(f"   Title        : {m['title']}")
            lines.append(f"   Wrong Belief : {m['wrong_belief']}")
            lines.append(f"   Correct Idea : {m['correct_idea']}")
    lines.append("")

    lines.append("--- Source Pack Chunks (Grounding Material) ---")
    lines.append(f"Pack Status: {pack.status} | Chunks: {len(pack)} | Total Words: {sum(c['words'] for c in pack)}")
    for i, c in enumerate(pack, 1):
        lines.append(f"\n[Chunk {i}] pp.{c['page_start']}-{c['page_end']} (Score: {c['score']}):")
        lines.append(c["text"].strip())
    lines.append("")

    lines.append("--- Verbatim Generation Rules ---")
    lines.append(RULES_TEXT)
    lines.append("=" * 78)

    return "\n".join(lines)


def get_next_pending_entries(n: int = 1, plan_path: Path = None) -> list[dict]:
    p_file = plan_path or PLAN_FILE
    if not p_file.exists():
        raise FileNotFoundError(f"Plan file not found: {p_file}. Run gen_plan.py first.")
    with open(p_file, "r", encoding="utf-8") as f:
        plan = json.load(f)

    pending = [e for e in plan if e.get("status") == "pending"]
    return pending[:n]


def main():
    parser = argparse.ArgumentParser(description="Display generation brief for next pending plan batches.")
    parser.add_argument("--n", type=int, default=1, help="Number of pending briefs to display (default: 1).")
    args = parser.parse_args()

    pending = get_next_pending_entries(args.n)
    if not pending:
        print("No pending generation plan entries found. All batches complete!")
        return

    for entry in pending:
        brief = format_brief(entry)
        print(brief)
        print("\n\n")


if __name__ == "__main__":
    main()
