"""
=============================================================================
EduGen - Quiz Bias & Test-Wise Gameability Audit (scripts/bias_audit.py)
=============================================================================
Measures the vulnerability of quiz questions to two surface-heuristic heuristics:
  Strategy 1: 'Pick longest option'
  Strategy 2: 'Drop options with absolute words (always/never/only/automatically/all/every/any),
               then pick longest'

Reports accuracy per difficulty for:
  - Active Verified Pool (pool_status = 'active')
  - Live/Generated Questions (origin in ('live', 'generated'))

Identifies the 20 most biased questions and calculates Easy pool capacity per concept.
=============================================================================
"""

import json
import math
import os
from pathlib import Path
import re
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS, concept_title
from core.db import get_db

ABS_PATTERN = re.compile(r"\b(always|never|only|automatically|all|every|any)\b", re.IGNORECASE)


def audit_question(q):
    """
    Evaluate a question against the test-wise heuristics:
      - always-longest
      - always-shortest
      - avoid-absolute-words (drop absolute words, then pick longest candidate)
      - always option 0 / 1 / 2 / 3
    Returns (strat1_correct, strat2_correct, bias_score, details_dict)
    """
    try:
        options = json.loads(q["options_json"] or "[]")
    except Exception:
        options = []

    if len(options) != 4:
        return False, False, 0.0, {}

    correct = int(q["correct_index"] or 0)
    cleaned = [str(o).strip() for o in options]
    lengths = [len(c) for c in cleaned]

    # Strategy 1: Pick longest
    strat1_choice = max(range(4), key=lambda i: lengths[i])
    strat1_correct = (strat1_choice == correct)

    # Strategy: Pick shortest
    shortest_choice = min(range(4), key=lambda i: lengths[i])
    strat_shortest_correct = (shortest_choice == correct)

    # Strategy 2: Drop absolute words, then pick longest
    abs_flags = [bool(ABS_PATTERN.search(c)) for c in cleaned]
    candidates = [i for i in range(4) if not abs_flags[i]]
    if not candidates:
        candidates = list(range(4))
    strat2_choice = max(candidates, key=lambda i: lengths[i])
    strat2_correct = (strat2_choice == correct)

    len_correct = lengths[correct]
    wrong_lens = [lengths[i] for i in range(4) if i != correct]
    max_wrong = max(wrong_lens) if wrong_lens else 1
    len_ratio = len_correct / max(max_wrong, 1)

    wrong_abs = sum(1 for i in range(4) if i != correct and abs_flags[i])
    correct_abs = abs_flags[correct]

    # Bias score combining length disparity and absolute word asymmetry
    bias_score = len_ratio + (0.5 * wrong_abs if not correct_abs else 0.0)

    details = {
        "id": q["id"],
        "concept": q["concept"],
        "difficulty": q["difficulty"],
        "len_ratio": round(len_ratio, 2),
        "wrong_abs": wrong_abs,
        "correct_abs": correct_abs,
        "bias_score": round(bias_score, 2),
        "len_correct": len_correct,
        "max_wrong": max_wrong,
        "correct_index": correct,
        "strat1_longest": strat1_correct,
        "strat_shortest": strat_shortest_correct,
        "strat2_avoid_abs": strat2_correct,
        "opt0": (correct == 0),
        "opt1": (correct == 1),
        "opt2": (correct == 2),
        "opt3": (correct == 3),
    }
    return strat1_correct, strat2_correct, bias_score, details


def run_blind_strategies_audit(title, rows, target_pct=35.0):
    n = len(rows)
    print("\n" + "=" * 76)
    print(f"  BLIND HEURISTIC STRATEGIES AUDIT: {title.upper()} (N = {n})")
    print("=" * 76)
    if n == 0:
        print("  No questions in cohort.")
        return {}

    counts = {
        "always-longest": 0,
        "always-shortest": 0,
        "avoid-absolute-words": 0,
        "always option 0": 0,
        "always option 1": 0,
        "always option 2": 0,
        "always option 3": 0,
    }

    for r in rows:
        _, _, _, d = audit_question(r)
        if not d:
            continue
        if d.get("strat1_longest"):
            counts["always-longest"] += 1
        if d.get("strat_shortest"):
            counts["always-shortest"] += 1
        if d.get("strat2_avoid_abs"):
            counts["avoid-absolute-words"] += 1
        if d.get("opt0"):
            counts["always option 0"] += 1
        if d.get("opt1"):
            counts["always option 1"] += 1
        if d.get("opt2"):
            counts["always option 2"] += 1
        if d.get("opt3"):
            counts["always option 3"] += 1

    print(f"{'STRATEGY':<26} | {'ACCURACY':<14} | {'PERCENT':<10} | {'TARGET (<=35%)':<16} | STATUS")
    print("-" * 76)
    results = {}
    for strat, cnt in counts.items():
        pct = (cnt / n) * 100.0
        passed = pct <= target_pct
        status = "PASS" if passed else "EXCEEDS (BIAS)"
        results[strat] = {"count": cnt, "total": n, "pct": round(pct, 1), "passed": passed}
        print(f"{strat:<26} | {cnt:>5}/{n:<7} | {pct:>6.1f}%    | {'<= 35.0%':<16} | {status}")
    print("-" * 76)
    print("Note: Random guessing baseline is 25.0%.")
    return results


def run_cohort_audit(title, rows):
    print("\n" + "=" * 76)
    print(f"  {title.upper()} (Total Questions: {len(rows)})")
    print("=" * 76)

    by_diff = {"Easy": [], "Medium": [], "Hard": []}
    for r in rows:
        diff = r["difficulty"] if r["difficulty"] in by_diff else "Medium"
        by_diff[diff].append(r)

    print(f"{'DIFFICULTY':<12} | {'COUNT':<7} | {'STRATEGY 1 (LONGEST)':<22} | {'STRATEGY 2 (NO ABS + LONGEST)'}")
    print("-" * 76)

    total_s1 = 0
    total_s2 = 0
    total_q = 0

    for diff in ("Easy", "Medium", "Hard"):
        q_list = by_diff[diff]
        n = len(q_list)
        if n == 0:
            print(f"{diff:<12} | {0:<7} | {'N/A':<22} | {'N/A'}")
            continue

        s1_wins = 0
        s2_wins = 0
        for q in q_list:
            s1_ok, s2_ok, _, _ = audit_question(q)
            if s1_ok:
                s1_wins += 1
            if s2_ok:
                s2_wins += 1

        total_s1 += s1_wins
        total_s2 += s2_wins
        total_q += n

        p1 = (s1_wins / n) * 100.0
        p2 = (s2_wins / n) * 100.0
        print(f"{diff:<12} | {n:<7} | {s1_wins}/{n} ({p1:.1f}%)" + " " * 8 + f"| {s2_wins}/{n} ({p2:.1f}%)")

    print("-" * 76)
    if total_q > 0:
        overall_p1 = (total_s1 / total_q) * 100.0
        overall_p2 = (total_s2 / total_q) * 100.0
        print(f"{'OVERALL':<12} | {total_q:<7} | {total_s1}/{total_q} ({overall_p1:.1f}%)" + " " * 8 + f"| {total_s2}/{total_q} ({overall_p2:.1f}%)")
        print(f"Note: Random baseline chance is 25.0%.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="EduGen Quiz Bias & Test-Wise Gameability Audit")
    parser.add_argument("--db-path", default=None, help="Path to database")
    parser.add_argument("--bank-only", action="store_true", help="Audit only bank questions")
    args = parser.parse_args()

    print("=" * 76)
    print("  EduGen Quiz Bias & Test-Wise Gameability Audit (Phase 9 / Phase 11b)")
    print("=" * 76)

    conn = get_db(args.db_path)
    cur = conn.cursor()

    # Cohort 1: Active Verified Pool (all active)
    pool_rows = cur.execute("SELECT * FROM questions WHERE pool_status = 'active' ORDER BY id ASC").fetchall()
    run_cohort_audit("Active Verified Pool (pool_status = 'active')", pool_rows)

    # Cohort: Active Bank Questions (Old vs New Top-Up)
    old_bank_rows = cur.execute(
        "SELECT * FROM questions WHERE pool_status = 'active' AND origin = 'bank' AND id <= 513 ORDER BY id ASC"
    ).fetchall()
    new_bank_rows = cur.execute(
        "SELECT * FROM questions WHERE pool_status = 'active' AND origin = 'bank' AND id > 513 ORDER BY id ASC"
    ).fetchall()

    run_blind_strategies_audit("Old Bank Questions (id <= 513)", old_bank_rows)
    run_blind_strategies_audit("New Top-Up Bank Questions (id > 513)", new_bank_rows)

    # Cohort 2: Live Generated Questions
    live_rows = cur.execute(
        "SELECT * FROM questions WHERE origin in ('live', 'generated') OR source = 'llm_rag' ORDER BY id ASC"
    ).fetchall()
    run_cohort_audit("Live Generated Questions (origin in ('live', 'generated'))", live_rows)

    # Top 20 Worst Question IDs
    all_rows = cur.execute("SELECT * FROM questions WHERE pool_status = 'active'").fetchall()
    scored = []
    for r in all_rows:
        _, _, score, d = audit_question(r)
        if d:
            scored.append(d)

    scored.sort(key=lambda x: x["bias_score"], reverse=True)
    top20 = scored[:20]

    print("\n" + "=" * 76)
    print("  TOP 20 MOST HEURISTIC-BIASED POOL QUESTIONS")
    print("=" * 76)
    print(f"{'QID':<6} | {'CONCEPT':<26} | {'DIFF':<7} | {'RATIO':<6} | {'WRONG ABS':<10} | {'SCORE'}")
    print("-" * 76)
    for q in top20:
        c_short = q["concept"][:24]
        print(f"{q['id']:<6} | {c_short:<26} | {q['difficulty']:<7} | {q['len_ratio']:<6} | {q['wrong_abs']:<10} | {q['bias_score']}")

    # Easy Pool Capacity per Concept
    print("\n" + "=" * 76)
    print("  EASY POOL CAPACITY & EXHAUSTION ANALYSIS (3 questions / quiz)")
    print("=" * 76)
    print(f"{'CONCEPT':<30} | {'EASY QS':<8} | {'QUIZZES TO EXHAUST'}")
    print("-" * 76)

    easy_counts = {}
    for r in cur.execute("SELECT concept, count(*) as cnt FROM questions WHERE pool_status = 'active' AND difficulty = 'Easy' GROUP BY concept"):
        easy_counts[r["concept"]] = r["cnt"]

    total_easy = sum(easy_counts.values())
    concepts_list = list(CONCEPTS) if CONCEPTS else sorted(easy_counts.keys())

    for c in concepts_list:
        cnt = easy_counts.get(c, 0)
        quizzes = math.ceil(cnt / 3.0) if cnt > 0 else 0
        print(f"{c:<30} | {cnt:<8} | {quizzes}")

    print("-" * 76)
    avg_quizzes = (total_easy / len(concepts_list) / 3.0) if concepts_list else 0
    print(f"Total Easy Pool Questions: {total_easy} across {len(concepts_list)} concepts (Avg ~{avg_quizzes:.1f} quizzes/concept)")
    print("=" * 76)

    conn.close()


if __name__ == "__main__":
    main()

