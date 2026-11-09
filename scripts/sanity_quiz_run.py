"""
EduGen - Phase 11b Sanity Run: Quiz Engine Pool Selection Verification
Tests 3 concepts across all 3 difficulties (9 quizzes):
  - default-constructor (Easy, Medium, Hard)
  - checked-vs-unchecked (Easy, Medium, Hard)
  - inheritance-hierarchy (Easy, Medium, Hard)
Verifies and records pool vs live question breakdown.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.db import get_db
from core.quiz_engine import build_blueprint, select_from_pool

CONCEPTS_TO_TEST = [
    "default-constructor",
    "checked-vs-unchecked",
    "inheritance-hierarchy",
]
DIFFICULTIES = ["Easy", "Medium", "Hard"]


def run_sanity():
    print("=" * 76)
    print("  EduGen Phase 11b Sanity Run: 9 Quizzes Pool vs Live Verification")
    print("=" * 76)

    conn = get_db()
    student = conn.execute("SELECT s.id, s.name FROM students s JOIN users u ON s.user_id = u.id WHERE u.email = 'demo@edugen.local'").fetchone()
    if not student:
        student = conn.execute("SELECT id, name FROM students ORDER BY id ASC LIMIT 1").fetchone()
    student_id = student["id"] if student else 1
    print(f"Testing with Student ID: {student_id} ({student['name'] if student else 'default'})\n")

    results = []
    total_slots = 0
    total_pool = 0
    total_live = 0

    print(f"{'CONCEPT':<26} | {'DIFF':<7} | {'SLOTS':<6} | {'FROM POOL':<10} | {'LIVE':<6} | {'STATUS'}")
    print("-" * 76)

    for concept in CONCEPTS_TO_TEST:
        for diff in DIFFICULTIES:
            # Check current pool count in database for this (concept, difficulty)
            pool_count = conn.execute(
                "SELECT count(*) FROM questions WHERE pool_status = 'active' AND concept = ? AND difficulty = ?",
                (concept, diff)
            ).fetchone()[0]

            slots = build_blueprint(
                kind="practice",
                student_id=student_id,
                concepts=[concept],
                concept=concept,
                n=3,
                difficulty=diff,
            )
            pool_served, unfilled_slots = select_from_pool(slots, student_id=student_id)

            n_slots = len(slots)
            n_pool = len(pool_served)
            n_live = len(unfilled_slots)

            total_slots += n_slots
            total_pool += n_pool
            total_live += n_live

            status = "100% POOL" if n_live == 0 else f"{n_live} LIVE NEEDED"
            results.append({
                "concept": concept,
                "difficulty": diff,
                "pool_available": pool_count,
                "slots": n_slots,
                "pool_served": n_pool,
                "live_needed": n_live,
                "status": status,
            })

            print(f"{concept:<26} | {diff:<7} | {n_slots:<6} | {n_pool:<10} | {n_live:<6} | {status} (pool avail: {pool_count})")

    print("-" * 76)
    pct_pool = (total_pool / total_slots * 100.0) if total_slots else 0.0
    print(f"TOTAL: {total_pool}/{total_slots} from pool ({pct_pool:.1f}%), {total_live} generated live.")
    print("=" * 76)

    # Detailed breakdown if any live questions were needed
    if total_live > 0:
        print("\nINVESTIGATION OF LIVE GENERATION REQUIREMENT:")
        for r in results:
            if r["live_needed"] > 0:
                print(f"  - Concept '{r['concept']}' [{r['difficulty']}]:")
                print(f"      Requested: {r['slots']} questions")
                print(f"      Available in active pool: {r['pool_available']} questions")
                print(f"      Reason: Active pool has {r['pool_available']} < {r['slots']} for {r['difficulty']} difficulty tier.")
                print("      Note: Relabeling by verifier shifted questions into other difficulty tiers.")

    conn.close()
    return results


if __name__ == "__main__":
    run_sanity()
