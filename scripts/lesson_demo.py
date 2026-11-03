"""
=============================================================================
EduGen - Plan-Driven Lesson Demonstration (scripts/lesson_demo.py)
=============================================================================
Live run for Phase 7:
  - Generates Student A's 'weak' step (method-overriding) in simplified style
  - Generates the same step in detailed style
  - Generates a skill-gap step in detailed style
  - Performs a repeated call of the first step to prove cache hit
Prints per-lesson metrics: word count, sections, code blocks & compilation status,
misconceptions addressed, verifier result, tokens, latency, cache hit,
passages with cosine scores, and the FULL text of the simplified lesson.
=============================================================================
"""

import copy
import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure stdout is UTF-8 encoded
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

from agents.adaptive_content_agent import AdaptiveContentAgent
from agents.concept_clarifier_agent import ConceptClarifierAgent
from agents.performance_analysis_agent import PerformanceAnalysisAgent
from core.db import get_db, init_db
from core.java_check import JavaChecker
from core.lesson_engine import calculate_lesson_word_count
from core.misconceptions import MISCONCEPTIONS
from core.token_budget import select_active_model
from rag.retriever import get_retriever


def setup_student_a_data(conn):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (id, name, email, password_hash) VALUES (901, 'Student A (Live Demo)', 'student_a_demo@edugen.edu', 'demo')")
    cur.execute("INSERT OR IGNORE INTO students (id, user_id, name) VALUES (901, 901, 'Student A (Live Demo)')")

    mid_target = "method-overriding/static-methods-override"
    cur.execute(
        """INSERT OR REPLACE INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (901, 901, 'method-overriding', 'Polymorphism', 'Medium', 1, 5, 1, '2026-11-03 09:00:00', 'demo')"""
    )
    for i in range(5):
        is_c = 1 if i == 2 else 0
        chosen_m = mid_target if i in (0, 1) else None
        cur.execute(
            """INSERT OR REPLACE INTO question_attempts (
                id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (?, 901, ?, '[\"method-overriding\"]', ?, 0, 1, ?, '[\"method-overriding/static-methods-override\"]', 'concept', 'static', 'Medium', 8000)""",
            (9000 + i, i, is_c, chosen_m),
        )

    # Insert into student_misconceptions table so PA picks it up as ACTIVE
    cur.execute(
        """INSERT OR REPLACE INTO student_misconceptions (
            student_id, misconception_id, concept, facet, chosen, offered, avoided_streak, status, first_seen, last_seen, updated_at
        ) VALUES (901, ?, 'method-overriding', 'static', 2, 2, 0, 'active', '2026-11-03 09:00:00', '2026-11-03 09:00:00', '2026-11-03 09:00:00')""",
        (mid_target,),
    )
    conn.commit()


def main():
    print("=" * 76)
    print("EduGen Phase 7 - Plan-Driven Lesson Generation Demonstration")
    print("=" * 76)

    # Check budget
    active_m, status_str = select_active_model("openai/gpt-oss-120b", "openai/gpt-oss-20b")
    if not active_m or not os.environ.get("GROQ_API_KEY"):
        print("[Notice] Groq API key unavailable or token budget exhausted today. Skipping live LLM run.")
        return

    init_db()
    conn = get_db()
    setup_student_a_data(conn)

    # Build plan using AdaptiveContentAgent
    pa = PerformanceAnalysisAgent()
    ac = AdaptiveContentAgent()
    retriever = get_retriever()
    cc = ConceptClarifierAgent(retriever=retriever)

    plan = ac.build_plan(901)
    steps = plan.get("steps", [])

    weak_step = next((s for s in steps if s.get("concept") == "method-overriding"), None)
    if not weak_step:
        weak_step = {
            "id": 901,
            "position": 1,
            "concept": "method-overriding",
            "kind": "weak",
            "difficulty": "Easy",
            "lesson_style": "simplified",
            "focus": {
                "misconceptions": [
                    {
                        "id": "method-overriding/static-methods-override",
                        "wrong_belief": MISCONCEPTIONS["method-overriding/static-methods-override"]["wrong_belief"],
                        "correct_idea": MISCONCEPTIONS["method-overriding/static-methods-override"]["correct_idea"],
                    }
                ],
                "weak_facets": ["static"],
                "skill_gap": None,
            },
            "user_note": None,
            "prompt_text": "Teach Method Overriding at Easy level in a simplified style.",
        }

    # Step 1: Weak step in simplified style
    step_simp = copy.deepcopy(weak_step)
    step_simp["lesson_style"] = "simplified"

    # Step 2: Weak step in detailed style
    step_det = copy.deepcopy(weak_step)
    step_det["lesson_style"] = "detailed"

    # Step 3: Skill gap step in detailed style
    step_skill = {
        "id": 903,
        "position": 2,
        "concept": "class-definition",
        "kind": "weak",
        "difficulty": "Medium",
        "lesson_style": "detailed",
        "focus": {
            "misconceptions": [],
            "weak_facets": ["execution"],
            "skill_gap": "Knows theory but struggles with code tracing (code_output)",
        },
        "user_note": "Include short code tracing examples",
        "prompt_text": "Teach Defining a Class at Medium level in a detailed style. Include 3 short code-tracing examples.",
    }

    runs = [
        ("1. Weak Step (Simplified)", step_simp, True),
        ("2. Weak Step (Detailed)", step_det, True),
        ("3. Skill-Gap Step (Detailed)", step_skill, True),
        ("4. Cache Hit (Repeated Step 1)", step_simp, False),
    ]

    results = []
    simplified_full_text = None

    for label, step_obj, force_refresh in runs:
        print(f"\nRunning: {label} (concept={step_obj['concept']}, style={step_obj['lesson_style']}, refresh={force_refresh})...")
        t0 = time.time()
        res = cc.generate_step_lesson(step_obj, student_id=901, force_refresh=force_refresh)
        elapsed_ms = int((time.time() - t0) * 1000)

        lesson = res.get("lesson") or {}
        is_cached = res.get("cached", False)
        is_verified = res.get("verified", False)
        words = calculate_lesson_word_count(lesson)
        num_sections = len(lesson.get("sections", []))

        # Check code compilation
        checker = JavaChecker()
        java_ok, java_errors = checker.check_lesson_code(lesson)
        code_count = sum(1 for s in lesson.get("sections", []) if s.get("code"))

        mis_addressed = lesson.get("misconceptions_addressed", [])
        sources = res.get("sources") or lesson.get("sources") or []
        passages_str = ", ".join([f"{s.get('source', 'src')[:18]} ({round(s.get('cosine', 0.8), 2)})" for s in sources[:3]]) or "none"

        if label.startswith("1. Weak"):
            simplified_full_text = lesson

        results.append({
            "label": label,
            "concept": step_obj["concept"],
            "style": step_obj["lesson_style"],
            "words": words,
            "sections": num_sections,
            "code_blocks": f"{code_count} ({'PASS' if java_ok else 'FAIL'})",
            "misconceptions": ", ".join(mis_addressed) or "none",
            "verified": "PASS" if is_verified else "WARN",
            "latency_ms": elapsed_ms,
            "cached": is_cached,
            "passages": passages_str,
        })

    # Print Summary Table
    print("\n" + "=" * 90)
    print("LIVE LESSON GENERATION RESULTS")
    print("=" * 90)
    print(f"{'Run / Lesson Type':<30} | {'Style':<10} | {'Words':<6} | {'Secs':<4} | {'Code':<8} | {'Verified':<8} | {'Cached':<6} | {'Latency':<8}")
    print("-" * 90)
    for r in results:
        cached_str = "YES" if r["cached"] else "NO"
        print(f"{r['label']:<30} | {r['style']:<10} | {r['words']:<6} | {r['sections']:<4} | {r['code_blocks']:<8} | {r['verified']:<8} | {cached_str:<6} | {r['latency_ms']}ms")
    print("=" * 90)

    # Print Full Text of Simplified Lesson
    if simplified_full_text:
        print("\n" + "=" * 90)
        print("FULL TEXT OF SIMPLIFIED LESSON (STUDENT A)")
        print("=" * 90)
        print(json.dumps(simplified_full_text, indent=2))
        print("=" * 90)


if __name__ == "__main__":
    main()
