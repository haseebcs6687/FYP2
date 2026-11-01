"""
=============================================================================
EduGen - Quiz Engine Real LLM Demo (Phase 4A)
=============================================================================
Demonstrates live quiz generation with the real Groq API key:
  1. Temporary student
  2. One diagnostic quiz (12 slots: 6 Easy + 6 Medium across foundational concepts)
  3. One practice quiz (concept: 'method-overriding', Medium, 5 slots)
  4. Formatted output showing build_report, slot details, and options with
     misconceptions resolved to their catalog titles.
=============================================================================
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure stdout is UTF-8 encoded
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app import create_app
from core.concepts import CONCEPTS, concept_title
from core.db import get_db
from core.misconceptions import MISCONCEPTIONS
from core.quiz_engine import build_blueprint


def format_question(idx, q):
    lines = []
    lines.append(f"\n--- Question {idx + 1} [{q.get('concept')} | {q.get('difficulty')} | {q.get('qtype')}] ---")
    lines.append(f"Question: {q.get('question')}")
    lines.append("Options:")
    opts = q.get("options") or []
    mids = q.get("option_misconception_ids") or [None] * len(opts)
    correct_idx = q.get("correct")

    for oi, opt in enumerate(opts):
        tag = "[CORRECT]" if oi == correct_idx else "         "
        mid = mids[oi] if oi < len(mids) else None
        if mid and mid in MISCONCEPTIONS:
            m_title = MISCONCEPTIONS[mid].get("title", mid)
            m_desc = f" -> Misconception: {m_title} ({mid})"
        elif mid:
            m_desc = f" -> Misconception ID: {mid}"
        else:
            m_desc = " -> (No misconception tag)" if oi != correct_idx else " -> (None - Correct)"

        lines.append(f"  ({oi}) {tag} {opt}{m_desc}")

    lines.append(f"Explanation: {q.get('explanation')}")
    if q.get("facet"):
        lines.append(f"Facet: {q.get('facet')}")
    return "\n".join(lines)


def run_demo(args):
    print("=" * 70)
    print("  EduGen Phase 4A/4E - Misconception-First Quiz Engine Demo")
    if args.no_pool:
        print("  [Mode: Pool Bypassed -- Live LLM Generation]")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    # Create temporary student for demo
    signup_resp = client.post("/api/auth/signup", json={
        "name": "Phase 4E Demo Student",
        "email": f"demo_p4e_{os.getpid()}@example.com",
        "password": "demopassword123",
    })
    student_id = signup_resp.get_json().get("student_id") if signup_resp.status_code == 201 else None
    print(f"\n[Demo] Authenticated temporary student_id: {student_id}")

    clarifier = app.extensions["edugen"]["cc"]
    if not clarifier.llm_available:
        print("[ERROR] Groq LLM client is not available. Please verify GROQ_API_KEY in .env.")
        return

    # Track start call id in llm_calls
    conn = get_db()
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) FROM llm_calls")
    start_call_id = cur.fetchone()[0]
    conn.close()

    if not args.practice_only:
        # ─────────────────────────────────────────────────────────────
        # Demo 1: Diagnostic Quiz (12 slots)
        # ─────────────────────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  1. DIAGNOSTIC QUIZ (12 Foundational Slots: 6 Easy + 6 Medium)")
        print("=" * 70)

        diag_slots = build_blueprint("diagnostic", student_id=student_id)
        print(f"Generated {len(diag_slots)} diagnostic slots across modules:")
        for i, s in enumerate(diag_slots, 1):
            print(f"  Slot {i:>2}: {s['concept']:<28} | {s['difficulty']:<6} | {s['qtype']:<11} | targets: {len(s['target_misconceptions'])}")

        print("\nExecuting live generation via Concept Clarifier...")
        diag_res = clarifier.generate_quiz_from_blueprint(diag_slots, student_id=student_id)

        print("\n--- Diagnostic Build Report ---")
        br = diag_res.get("build_report", {})
        for k, v in br.items():
            print(f"  {k}: {v}")

        print(f"\nTotal questions accepted: {len(diag_res.get('questions', []))}")
        for i, q in enumerate(diag_res.get("questions", [])):
            print(format_question(i, q))

    # ─────────────────────────────────────────────────────────────
    # Demo 2: Practice Quiz (default: 'method-overriding', Medium, 5 slots)
    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"  PRACTICE QUIZ (Concept: '{args.concept}', {args.difficulty}, {args.count} slots)")
    print("=" * 70)

    pract_slots = build_blueprint("practice", student_id=student_id, concepts=[args.concept], difficulty=args.difficulty, n=args.count)
    print(f"Generated {len(pract_slots)} practice slots:")
    for i, s in enumerate(pract_slots, 1):
        print(f"  Slot {i:>2}: {s['concept']:<20} | {s['difficulty']:<6} | {s['qtype']:<11} | targets: {s['target_misconceptions']}")

    print("\nExecuting live generation via Concept Clarifier...")
    pract_res = clarifier.generate_quiz_from_blueprint(pract_slots, student_id=student_id)

    print("\n--- Practice Build Report ---")
    br2 = pract_res.get("build_report", {})
    for k, v in br2.items():
        print(f"  {k}: {v}")

    accepted_qs = pract_res.get("questions", [])
    print(f"\nTotal questions accepted: {len(accepted_qs)}")
    for i, q in enumerate(accepted_qs):
        print(format_question(i, q))

    # ─────────────────────────────────────────────────────────────
    # Live Token Measurement Report (from llm_calls)
    # ─────────────────────────────────────────────────────────────
    conn = get_db()
    rows = conn.execute(
        """SELECT model,
                  COUNT(*) as calls,
                  SUM(prompt_tokens) as p_tokens,
                  SUM(completion_tokens) as c_tokens,
                  SUM(total_tokens) as t_tokens
           FROM llm_calls
           WHERE id > ?
           GROUP BY model""",
        (start_call_id,),
    ).fetchall()
    conn.close()

    total_all_tokens = sum(r["t_tokens"] or 0 for r in rows)
    num_accepted = len(accepted_qs)
    tok_per_q = round(total_all_tokens / num_accepted, 1) if num_accepted > 0 else 0.0

    print("\n" + "=" * 70)
    print("  LIVE TOKEN USAGE MEASUREMENT")
    print("=" * 70)
    print(f"{'Model':<28} | {'Calls':>6} | {'Prompt':>8} | {'Comp':>8} | {'Total':>8}")
    print("-" * 70)
    for r in rows:
        print(f"{r['model']:<28} | {r['calls']:>6} | {r['p_tokens'] or 0:>8} | {r['c_tokens'] or 0:>8} | {r['t_tokens'] or 0:>8}")
    print("-" * 70)
    print(f"{'TOTAL':<28} | {sum(r['calls'] for r in rows):>6} | {sum(r['p_tokens'] or 0 for r in rows):>8} | {sum(r['c_tokens'] or 0 for r in rows):>8} | {total_all_tokens:>8}")
    print(f"\nAccepted Questions        : {num_accepted}")
    print(f"Tokens Per Accepted Question: {tok_per_q}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="EduGen Misconception-First Quiz Engine Demo")
    parser.add_argument("--no-pool", action="store_true", default=False, help="Bypass question pool and generate live")
    parser.add_argument("--practice-only", action="store_true", default=False, help="Run only practice quiz")
    parser.add_argument("--concept", type=str, default="method-overriding", help="Target concept")
    parser.add_argument("--difficulty", type=str, default="Medium", help="Target difficulty")
    parser.add_argument("--count", type=int, default=5, help="Number of questions")
    args = parser.parse_args()
    run_demo(args)


if __name__ == "__main__":
    main()
