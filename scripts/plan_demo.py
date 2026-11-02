"""
=============================================================================
EduGen - Study Planner Demonstration & Examples Generator (scripts/plan_demo.py)
=============================================================================
Builds personalized study plans for five synthetic student profiles:
  - Student A: Persistent Misconception (active misconception in method-overriding)
  - Student B: Remediated Misconception (resolved misconception, normal remediation)
  - Student C: Theory vs Tracing Gap (struggles with code tracing)
  - Student D: Random Guesser (low overall accuracy, broad deficits)
  - Student E: Weak Prerequisite (struggling with dynamic-method-dispatch due to weak inheritance-basics)

Writes readable, formatted plans (steps, reasons, prompts, verification) to docs/PLAN_EXAMPLES.md.
Runs hermetically in a temporary database without external network calls.
=============================================================================
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure stdout is UTF-8 encoded
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from agents.adaptive_content_agent import AdaptiveContentAgent
from agents.performance_analysis_agent import PerformanceAnalysisAgent
from core.db import get_db, init_db


def create_demo_data(db_path):
    conn = get_db(db_path)
    cur = conn.cursor()

    # Create 5 students
    students = [
        (1, "Student A (Persistent Misconception)", "student_a@example.com"),
        (2, "Student B (Remediated Misconception)", "student_b@example.com"),
        (3, "Student C (Theory vs Tracing Gap)", "student_c@example.com"),
        (4, "Student D (Random Guesser)", "student_d@example.com"),
        (5, "Student E (Weak Prerequisite)", "student_e@example.com"),
        (6, "Student F (Mastered 6 Concepts)", "student_f@example.com"),
    ]
    for sid, name, email in students:
        cur.execute("INSERT OR IGNORE INTO users (id, name, email, password_hash) VALUES (?, ?, ?, 'demo')", (sid, name, email))
        cur.execute("INSERT OR IGNORE INTO students (id, user_id, name) VALUES (?, ?, ?)", (sid, sid, name))

    mid_target = "method-overriding/static-methods-override"
    mid_alt = "method-overriding/can-reduce-visibility"

    # ── Student A: Persistent Active Misconception ──────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (101, 1, 'method-overriding', 'Polymorphism', 'Medium', 1, 5, 1, '2026-11-01 10:00:00', 'demo')"""
    )
    for i in range(5):
        is_c, chosen_m = (0, mid_target) if i in (0, 1) else ((1, None) if i == 2 else (0, None))
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (101, ?, ?, ?, ?, 0, ?, ?, 'concept', 'static', 'Medium', 8000)""",
            (i, json.dumps(["method-overriding"]), is_c, 1 if not is_c else 0, chosen_m, json.dumps([mid_target, mid_alt])),
        )

    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (102, 1, 'method-overriding', 'Polymorphism', 'Medium', 1, 5, 2, '2026-11-01 11:00:00', 'demo')"""
    )
    for i in range(5):
        is_c, chosen_m = (0, mid_target) if i in (3, 4) else ((1, None) if i == 0 else (0, None))
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (102, ?, ?, ?, ?, 0, ?, ?, 'concept', 'static', 'Medium', 8500)""",
            (i, json.dumps(["method-overriding"]), is_c, 1 if not is_c else 0, chosen_m, json.dumps([mid_target, mid_alt])),
        )

    # ── Student B: Remediated Misconception ──────────────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (201, 2, 'method-overriding', 'Polymorphism', 'Medium', 2, 5, 1, '2026-10-30 10:00:00', 'demo')"""
    )
    for i in range(5):
        is_c, chosen_m = (0, mid_target) if i in (0, 1) else ((1, None) if i in (2, 3) else (0, None))
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (201, ?, ?, ?, ?, 0, ?, ?, 'concept', 'static', 'Medium', 9000)""",
            (i, json.dumps(["method-overriding"]), is_c, 1 if not is_c else 0, chosen_m, json.dumps([mid_target, mid_alt])),
        )

    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (202, 2, 'method-overriding', 'Polymorphism', 'Medium', 5, 5, 2, '2026-11-01 10:00:00', 'demo')"""
    )
    for i in range(5):
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (202, ?, ?, 1, 0, 0, NULL, ?, 'concept', 'static', 'Medium', 6000)""",
            (i, json.dumps(["method-overriding"]), json.dumps([mid_target, mid_alt])),
        )

    # ── Student C: Theory vs Tracing Gap ────────────────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (301, 3, 'class-definition', 'Classes', 'Medium', 7, 12, 1, '2026-11-01 12:00:00', 'demo')"""
    )
    for i in range(6):
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (301, ?, ?, 1, 0, 0, NULL, '[]', 'concept', 'syntax', 'Medium', 5000)""",
            (i, json.dumps(["class-definition"])),
        )
    for i in range(6, 12):
        is_c = 1 if i == 6 else 0
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (301, ?, ?, ?, ?, 0, NULL, '[]', 'code_output', 'execution', 'Medium', 15000)""",
            (i, json.dumps(["class-definition"]), is_c, 0 if is_c else 1),
        )

    # ── Student D: Random Guesser ───────────────────────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (401, 4, 'class-definition', 'Classes', 'Easy', 2, 8, 1, '2026-11-01 14:00:00', 'demo')"""
    )
    for i in range(8):
        is_c = 1 if i in (1, 5) else 0
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (401, ?, ?, ?, ?, 0, NULL, '[]', 'concept', 'syntax', 'Easy', 4000)""",
            (i, json.dumps(["class-definition"]), is_c, 0 if is_c else 1),
        )

    # ── Student E: Weak Prerequisite ────────────────────────────────────────
    # Has attempts in class-definition (mastered 80%)
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (501, 5, 'class-definition', 'Classes', 'Medium', 5, 5, 1, '2026-10-25 10:00:00', 'demo')"""
    )
    for i in range(5):
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (501, ?, ?, 1, 0, 0, NULL, '[]', 'concept', 'syntax', 'Medium', 5000)""",
            (i, json.dumps(["class-definition"])),
        )

    # Weak in inheritance-basics (prerequisite, 20% score)
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (502, 5, 'inheritance-basics', 'Inheritance', 'Medium', 1, 5, 2, '2026-10-28 10:00:00', 'demo')"""
    )
    for i in range(5):
        is_c = 1 if i == 0 else 0
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (502, ?, ?, ?, ?, 0, NULL, '[]', 'concept', 'hierarchy', 'Medium', 9000)""",
            (i, json.dumps(["inheritance-basics"]), is_c, 0 if is_c else 1),
        )

    # Struggles with dynamic-method-dispatch (symptom, 20% score)
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (503, 5, 'dynamic-method-dispatch', 'Polymorphism', 'Medium', 1, 5, 3, '2026-11-01 15:00:00', 'demo')"""
    )
    for i in range(5):
        is_c = 1 if i == 0 else 0
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (503, ?, ?, ?, ?, 0, NULL, '[]', 'concept', 'dispatch', 'Medium', 12000)""",
            (i, json.dumps(["dynamic-method-dispatch"]), is_c, 0 if is_c else 1),
        )

    # ── Student F: Mastered First 6 Concepts (Curriculum Frontier Advance) ───
    c6_list = [
        "class-definition", "object-instantiation", "static-members",
        "this-keyword", "reference-semantics", "object-composition"
    ]
    for q_idx, c_tag in enumerate(c6_list, start=1):
        res_id = 600 + q_idx
        cur.execute(
            """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
               VALUES (?, 6, ?, 'Foundations', 'Medium', 5, 5, 1, '2026-11-01 16:00:00', 'demo')""",
            (res_id, c_tag),
        )
        for i in range(5):
            cur.execute(
                """INSERT INTO question_attempts (
                    quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                    misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
                ) VALUES (?, ?, ?, 1, 0, 0, NULL, '[]', 'concept', 'syntax', 'Medium', 4500)""",
                (res_id, i, json.dumps([c_tag])),
            )

    conn.commit()
    conn.close()


def main():
    print("=" * 70)
    print("EduGen Phase 6 - Study Planner Demonstration")
    print("=" * 70)

    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "demo_edugen.db")
    os.environ["EDUGEN_DB_PATH"] = db_path

    import core.db
    core.db.DB_PATH = db_path
    init_db(db_path)
    create_demo_data(db_path)

    pa = PerformanceAnalysisAgent()
    ac = AdaptiveContentAgent()

    plans_output = []

    student_profiles = [
        (1, "Student A", "Persistent Active Misconception in Method Overriding"),
        (2, "Student B", "Remediated Misconception (Avoided Streak = 5)"),
        (3, "Student C", "Theory vs Code Tracing Skill Gap in Classes"),
        (4, "Student D", "Random Guesser (Low Accuracy Across the Board)"),
        (5, "Student E", "Weak Prerequisite Root Cause (Inheritance Basics behind Dynamic Dispatch)"),
        (6, "Student F", "Mastered First 6 Concepts (Curriculum Frontier Advance)"),
    ]

    for sid, name, desc in student_profiles:
        print(f"\nAnalyzing and Building Plan for: {name} ({desc})...")
        report = pa.analyze_student(sid, db_path=db_path)
        plan = ac.build_plan(sid, report=report)
        plans_output.append((name, desc, plan, report))

        print(f"  Plan ID: {plan.get('id')}")
        print(f"  Steps ({len(plan['steps'])}):")
        for s in plan["steps"]:
            style_str = f" [{s.get('lesson_style')}]" if s.get("lesson_style") else ""
            print(f"    {s['position']}. {s['title']} ({s['kind']}) - {s['difficulty']}{style_str} | Reason: {s['reason']}")
        print(f"  Coverage OK: {plan.get('coverage', {}).get('ok')}")

    # Generate docs/PLAN_EXAMPLES.md
    examples_file = BASE_DIR / "docs" / "PLAN_EXAMPLES.md"
    md = []
    md.append("# Study Plan Examples: Synthetic Student Profiles (Phase 6)")
    md.append("")
    md.append("This document illustrates the complete, ordered study plans generated by the **Adaptive Content Agent** across five benchmarked synthetic student profiles.")
    md.append("")

    for name, desc, plan, report in plans_output:
        md.append(f"## {name}: {desc}")
        md.append("")
        md.append(f"- **Overall Mastery**: `{report.get('overall_performance', 0.0)}%`")
        md.append(f"- **Plan Summary**: {plan.get('summary', '')}")
        cov = plan.get("coverage", {})
        md.append(f"- **Coverage Status**: `{'Verified & Complete (5/5 checks passed)' if cov.get('ok') else 'Coverage Warnings Present'}`")
        md.append("")
        md.append("### Curriculum Steps")
        md.append("")
        md.append("| Step | Concept / Title | Kind | Difficulty | Style | Est Min | Reason |")
        md.append("| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
        for s in plan["steps"]:
            style = s.get("lesson_style") or "-"
            md.append(f"| **{s['position']}** | **{s['title']}** (`{s['concept']}`) | `{s['kind']}` | `{s['difficulty']}` | `{style}` | {s['est_minutes']}m | {s['reason']} |")
        md.append("")

        md.append("### Generated Lesson Prompts & Focus Details")
        md.append("")
        learning_steps = [s for s in plan["steps"] if s.get("prompt_text")]
        for s in learning_steps:
            md.append(f"#### Step {s['position']}: {s['title']}")
            md.append(f"```text\n{s['prompt_text']}\n```")
            f = s.get("focus", {})
            if f.get("misconceptions"):
                md.append("- **Target Misconceptions**:")
                for m in f["misconceptions"]:
                    md.append(f"  - `{m['id']}`: *{m.get('wrong_belief')}* &rarr; **{m.get('correct_idea')}** (Severity: {m.get('severity', 0.0)})")
            if f.get("weak_facets"):
                md.append(f"- **Weak Facets**: `{', '.join(f['weak_facets'])}`")
            if f.get("skill_gap"):
                md.append(f"- **Skill Focus**: `{f['skill_gap']}`")
            md.append("")

        if plan.get("deferred"):
            md.append("### Deferred Items")
            for d in plan["deferred"]:
                md.append(f"- **{d['title']}** (`{d['concept']}`): Priority `{d.get('priority', 0.0):.1f}` &mdash; {d['reason']}")
            md.append("")

        md.append("---")
        md.append("")

    with open(examples_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"\n[OK] Wrote plan examples report to {examples_file}")

    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
