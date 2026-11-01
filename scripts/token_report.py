"""
=============================================================================
EduGen - Token Report CLI (Phase 4C)
=============================================================================
Reports per model per day:
  - Total calls
  - Successful calls
  - Total tokens (prompt + completion)
  - Accepted questions
  - Average tokens per accepted question
=============================================================================
"""

import os
import sqlite3
import sys
from pathlib import Path

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.db import get_db


def generate_token_report():
    conn = get_db()
    conn.row_factory = sqlite3.Row

    # Query LLM calls per model per day
    calls_rows = conn.execute("""
        SELECT 
            date(created_at) as day,
            COALESCE(model, 'unknown') as model,
            COUNT(*) as total_calls,
            SUM(ok) as ok_calls,
            SUM(COALESCE(total_tokens, prompt_tokens + completion_tokens, 0)) as total_tokens
        FROM llm_calls
        GROUP BY date(created_at), model
        ORDER BY day DESC, model ASC
    """).fetchall()

    # Query verified questions per model per day
    q_rows = conn.execute("""
        SELECT
            date(created_at) as day,
            COALESCE(model, 'unknown') as model,
            COUNT(*) as accepted_count
        FROM questions
        WHERE verified = 1
        GROUP BY date(created_at), model
    """).fetchall()
    conn.close()

    accepted_map = {}
    for r in q_rows:
        accepted_map[(r["day"], r["model"])] = int(r["accepted_count"] or 0)

    print("=" * 88)
    print("EDUGEN LLM TOKEN USAGE & EFFICIENCY REPORT")
    print("=" * 88)
    print(f"{'Date':<12} | {'Model':<26} | {'Calls':<6} | {'OK':<4} | {'Tokens':<9} | {'Accepted Q':<10} | {'Avg Tok/Q':<10}")
    print("-" * 88)

    if not calls_rows:
        print("No LLM calls recorded in the database.")
        print("=" * 88)
        return

    total_tokens_all = 0
    total_calls_all = 0
    total_acc_all = 0

    for r in calls_rows:
        day = r["day"] or "N/A"
        m = r["model"]
        calls = int(r["total_calls"] or 0)
        ok = int(r["ok_calls"] or 0)
        tokens = int(r["total_tokens"] or 0)

        # Look up accepted questions for this day + model
        acc = accepted_map.get((day, m), 0)
        avg_tok = f"{tokens / acc:.1f}" if acc > 0 else "N/A"

        total_tokens_all += tokens
        total_calls_all += calls
        total_acc_all += acc

        print(f"{day:<12} | {m:<26} | {calls:<6} | {ok:<4} | {tokens:<9} | {acc:<10} | {avg_tok:<10}")

    print("-" * 88)
    overall_avg = f"{total_tokens_all / total_acc_all:.1f}" if total_acc_all > 0 else "N/A"
    print(f"{'TOTAL':<12} | {'ALL MODELS':<26} | {total_calls_all:<6} | {'-':<4} | {total_tokens_all:<9} | {total_acc_all:<10} | {overall_avg:<10}")
    print("=" * 88)


if __name__ == "__main__":
    generate_token_report()

