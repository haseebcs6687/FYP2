"""
=============================================================================
EduGen - Quarantine Biased Live Pool Questions (scripts/quarantine_biased.py)
=============================================================================
Runs the Phase 9 live validation gates against active questions in the pool
that originated from live generation (origin in ('live', 'generated') or source='llm_rag'):
  1. Length disparity gate: len(correct) > 1.03 * max(wrong_lengths) and strictly longest
  2. Absolute word asymmetry: >=2 wrong options contain absolute words while correct does not

Usage:
  python scripts/quarantine_biased.py          # Dry-run mode (default)
  python scripts/quarantine_biased.py --apply  # Apply quarantining to database
=============================================================================
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.db import get_db

ABS_PATTERN = re.compile(r"\b(always|never|only|automatically|all|every|any)\b", re.IGNORECASE)


def check_live_gates(options, correct_index):
    """
    Evaluate options against live bias gates.
    Returns (passed, list_of_failing_gates, details)
    """
    cleaned = [str(o).strip() for o in options]
    if len(cleaned) != 4 or correct_index < 0 or correct_index > 3:
        return False, ["malformed_options"], {}

    len_correct = len(cleaned[correct_index])
    wrong_lens = [len(cleaned[i]) for i in range(4) if i != correct_index]
    max_wrong = max(wrong_lens) if wrong_lens else 0

    failing_gates = []

    # Gate 1: Length Disparity (1.03x threshold)
    if max_wrong > 0 and len_correct > max_wrong and len_correct > 1.03 * max_wrong:
        failing_gates.append("correct_option_too_long")

    # Gate 2: Absolute Word Bias (>= 2 wrong options have absolute word, correct does not)
    wrong_abs_count = sum(1 for i in range(4) if i != correct_index and ABS_PATTERN.search(cleaned[i]))
    correct_has_abs = bool(ABS_PATTERN.search(cleaned[correct_index]))
    if wrong_abs_count >= 2 and not correct_has_abs:
        failing_gates.append("absolute_word_bias")

    passed = len(failing_gates) == 0
    ratio = round(len_correct / max(max_wrong, 1), 2)
    return passed, failing_gates, {
        "len_ratio": ratio,
        "wrong_abs": wrong_abs_count,
        "correct_has_abs": correct_has_abs,
    }


def main():
    parser = argparse.ArgumentParser(description="Quarantine biased live pool questions.")
    parser.add_argument("--apply", action="store_true", help="Apply updates to database (default is dry-run)")
    parser.add_argument("--db-path", default=None, help="Custom database path")
    args = parser.parse_args()

    conn = get_db(args.db_path)
    cur = conn.cursor()

    # Query active questions with live origin / llm_rag source
    rows = cur.execute(
        """SELECT id, concept, difficulty, qtype, question_text, options_json, correct_index, origin, source, pool_status
           FROM questions
           WHERE pool_status = 'active'
             AND (origin IN ('live', 'generated') OR source = 'llm_rag')
           ORDER BY id ASC"""
    ).fetchall()

    checked = len(rows)
    failing_records = []
    gate_counts = {
        "correct_option_too_long": 0,
        "absolute_word_bias": 0,
        "both_gates": 0,
        "malformed_options": 0,
    }

    for r in rows:
        try:
            opts = json.loads(r["options_json"] or "[]")
        except Exception:
            opts = []
        corr = int(r["correct_index"] or 0)
        passed, fails, details = check_live_gates(opts, corr)
        if not passed:
            failing_records.append((r["id"], fails, details, r["concept"], r["difficulty"]))
            for f in fails:
                gate_counts[f] = gate_counts.get(f, 0) + 1
            if len(fails) > 1 and "correct_option_too_long" in fails and "absolute_word_bias" in fails:
                gate_counts["both_gates"] += 1

    failing = len(failing_records)

    print("=" * 72)
    print("  EduGen - Quarantine Biased Live Questions")
    print("=" * 72)
    mode_str = "APPLY (writing to database)" if args.apply else "DRY-RUN (read-only, no changes made)"
    print(f"Mode: {mode_str}\n")
    print(f"Questions Checked : {checked}")
    print(f"Questions Passing : {checked - failing}")
    print(f"Questions Failing : {failing}\n")
    print("Failing Breakdown by Gate:")
    print(f"  - correct_option_too_long (>1.03x ratio) : {gate_counts['correct_option_too_long']}")
    print(f"  - absolute_word_bias (>=2 wrong abs)     : {gate_counts['absolute_word_bias']}")
    print(f"  - Failing both gates                     : {gate_counts['both_gates']}")
    if gate_counts.get("malformed_options", 0) > 0:
        print(f"  - Malformed options                      : {gate_counts['malformed_options']}")

    if failing_records:
        print("\nFailing Questions Detail:")
        print(f"{'QID':<6} | {'CONCEPT':<26} | {'DIFF':<7} | {'RATIO':<6} | {'WRONG ABS':<10} | {'GATES'}")
        print("-" * 72)
        for qid, fails, det, c, diff in failing_records:
            print(f"{qid:<6} | {c:<26} | {diff:<7} | {det.get('len_ratio', 0.0):<6.2f} | {det.get('wrong_abs', 0):<10} | {', '.join(fails)}")

    if args.apply:
        if failing_records:
            fail_ids = [item[0] for item in failing_records]
            cur.executemany(
                "UPDATE questions SET pool_status = 'quarantined' WHERE id = ?",
                [(qid,) for qid in fail_ids],
            )
            conn.commit()
            print(f"\n[APPLIED] Successfully quarantined {len(fail_ids)} questions in database.")
        else:
            print("\n[APPLIED] No questions met quarantine criteria.")
    else:
        print("\n[DRY-RUN] To commit changes to the database, re-run with --apply flag.")

    conn.close()


if __name__ == "__main__":
    main()

