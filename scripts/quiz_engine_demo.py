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


def run_demo():
    print("=" * 70)
    print("  EduGen Phase 4A - Misconception-First Quiz Engine Demo")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    # Create temporary student for demo
    signup_resp = client.post("/api/auth/signup", json={
        "name": "Phase 4A Demo Student",
        "email": f"demo_p4a_{os.getpid()}@example.com",
        "password": "demopassword123",
    })
    student_id = signup_resp.get_json().get("student_id") if signup_resp.status_code == 201 else None
    print(f"\n[Demo] Authenticated temporary student_id: {student_id}")

    clarifier = app.extensions["edugen"]["cc"]
    if not clarifier.llm_available:
        print("[ERROR] Groq LLM client is not available. Please verify GROQ_API_KEY in .env.")
        return

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
    # Demo 2: Practice Quiz ('method-overriding', Medium, 5 slots)
    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  2. PRACTICE QUIZ (Concept: 'method-overriding', Medium, 5 slots)")
    print("=" * 70)

    pract_slots = build_blueprint("practice", student_id=student_id, concepts=["method-overriding"], difficulty="Medium", n=5)
    print(f"Generated {len(pract_slots)} practice slots:")
    for i, s in enumerate(pract_slots, 1):
        print(f"  Slot {i:>2}: {s['concept']:<20} | {s['difficulty']:<6} | {s['qtype']:<11} | targets: {s['target_misconceptions']}")

    print("\nExecuting live generation via Concept Clarifier...")
    pract_res = clarifier.generate_quiz_from_blueprint(pract_slots, student_id=student_id)

    print("\n--- Practice Build Report ---")
    br2 = pract_res.get("build_report", {})
    for k, v in br2.items():
        print(f"  {k}: {v}")

    print(f"\nTotal questions accepted: {len(pract_res.get('questions', []))}")
    for i, q in enumerate(pract_res.get("questions", [])):
        print(format_question(i, q))

    print("\n" + "=" * 70)
    print("  Demo Complete")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
