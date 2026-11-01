"""
=============================================================================
EduGen - Performance Analysis Agent Evaluation Demo (scripts/pa_demo.py)
=============================================================================
Demonstrates the deep diagnostics of the Phase 5 Performance Analysis Agent
across four synthetic student profiles with known behavioral characteristics:
  - Student A: Repeatedly falls for misconception 'method-overriding/static-methods-override'
  - Student B: Had misconception 'method-overriding/static-methods-override', then remediated it
  - Student C: Strong theory knowledge (concept: 100%), but fails code tracing (code_output: 25%)
  - Student D: Random guesser (~25% accuracy across questions, no persistent pattern)

Runs hermetically in a temporary database without external calls.
=============================================================================
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure stdout is UTF-8 encoded
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from agents.performance_analysis_agent import PerformanceAnalysisAgent
from core.db import get_db, init_db


def create_demo_data(db_path):
    conn = get_db(db_path)
    cur = conn.cursor()

    # 1. Create 4 students
    students = [
        (1, "Student A (Persistent Misconception)", "student_a@example.com"),
        (2, "Student B (Remediated Misconception)", "student_b@example.com"),
        (3, "Student C (Theory vs Tracing Gap)", "student_c@example.com"),
        (4, "Student D (Random Guesser)", "student_d@example.com"),
    ]
    for sid, name, email in students:
        cur.execute("INSERT OR IGNORE INTO users (id, name, email, password_hash) VALUES (?, ?, ?, 'demo')", (sid, name, email))
        cur.execute("INSERT OR IGNORE INTO students (id, user_id, name) VALUES (?, ?, ?)", (sid, sid, name))

    mid_target = "method-overriding/static-methods-override"
    mid_alt = "method-overriding/can-reduce-visibility"

    # ─────────────────────────────────────────────────────────────────────────
    # Student A: Repeats misconception 'method-overriding/static-methods-override'
    # 2 Quizzes, chosen 4 times, avoided 0 times -> ACTIVE
    # ─────────────────────────────────────────────────────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (101, 1, 'method-overriding', 'Polymorphism', 'Medium', 1, 5, 1, '2026-11-01 10:00:00', 'demo')"""
    )
    for i in range(5):
        if i in (0, 1):  # falls for target misconception
            is_c, chosen_m = 0, mid_target
        elif i == 2:     # correct
            is_c, chosen_m = 1, None
        else:            # untagged wrong
            is_c, chosen_m = 0, None
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
        if i in (3, 4):  # falls for target misconception in the most recent questions (avoided_streak = 0)!
            is_c, chosen_m = 0, mid_target
        elif i == 0:     # correct
            is_c, chosen_m = 1, None
        else:            # untagged wrong
            is_c, chosen_m = 0, None
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (102, ?, ?, ?, ?, 0, ?, ?, 'concept', 'static', 'Medium', 8500)""",
            (i, json.dumps(["method-overriding"]), is_c, 1 if not is_c else 0, chosen_m, json.dumps([mid_target, mid_alt])),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Student B: Had misconception, then remediated it (avoided streak = 3 -> RESOLVED)
    # ─────────────────────────────────────────────────────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (201, 2, 'method-overriding', 'Polymorphism', 'Medium', 2, 5, 1, '2026-10-30 10:00:00', 'demo')"""
    )
    for i in range(5):
        if i in (0, 1):  # previously fell for it twice
            is_c, chosen_m = 0, mid_target
        elif i in (2, 3):
            is_c, chosen_m = 1, None
        else:
            is_c, chosen_m = 0, None
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
        # Student now avoids the trap every time it is offered!
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (202, ?, ?, 1, 0, 0, NULL, ?, 'concept', 'static', 'Medium', 6000)""",
            (i, json.dumps(["method-overriding"]), json.dumps([mid_target, mid_alt])),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Student C: Strong theory knowledge, but fails code tracing (SKILL GAP)
    # ─────────────────────────────────────────────────────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (301, 3, 'class-definition', 'Classes', 'Medium', 7, 12, 1, '2026-11-01 12:00:00', 'demo')"""
    )
    # 6 concept questions -> 6/6 correct (100%)
    for i in range(6):
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (301, ?, ?, 1, 0, 0, NULL, '[]', 'concept', 'syntax', 'Medium', 5000)""",
            (i, json.dumps(["class-definition"])),
        )
    # 6 code_output questions -> 1/6 correct (16.7%)
    for i in range(6, 12):
        is_c = 1 if i == 6 else 0
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (301, ?, ?, ?, ?, 0, NULL, '[]', 'code_output', 'execution', 'Medium', 15000)""",
            (i, json.dumps(["class-definition"]), is_c, 0 if is_c else 1),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Student D: Random guesser (~25% accuracy across questions, no pattern)
    # ─────────────────────────────────────────────────────────────────────────
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source)
           VALUES (401, 4, 'inheritance-basics', 'Inheritance', 'Medium', 3, 12, 1, '2026-11-01 14:00:00', 'demo')"""
    )
    # 12 questions: 3 correct, 9 incorrect across different distractors with no repeat
    for i in range(12):
        is_c = 1 if i in (1, 5, 9) else 0
        diff_mid = f"inheritance-basics/fake-misconception-{i}" if not is_c else None
        cur.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                misconception_id, offered_misconceptions, qtype, facet, difficulty, time_taken_ms
            ) VALUES (401, ?, ?, ?, ?, 0, ?, ?, 'concept', 'basics', 'Medium', 3000)""",
            (i, json.dumps(["inheritance-basics"]), is_c, 0 if is_c else 1, diff_mid, json.dumps([diff_mid] if diff_mid else [])),
        )

    conn.commit()
    conn.close()


def print_student_report(agent, sid, title, db_path):
    print("\n" + "=" * 80)
    print(f"  {title.upper()}")
    print("=" * 80)

    report = agent.analyze_student(sid, db_path=db_path)

    print(f"Overall Accuracy          : {report['overall_performance']}%")
    print(f"Total Quizzes / Questions : {report['total_quizzes_taken']} quizzes, {report['total_questions_attempted']} questions")

    # Concept stats table
    print("\nConcept Performance (BKT vs EWMA):")
    header = f"{'Concept':<24} | {'Attempts':>8} | {'Accuracy':>8} | {'BKT Mastery':>11} | {'EWMA':>6} | {'Confidence':<10}"
    print(header)
    print("-" * len(header))
    for c_tag, stat in report["concept_stats"].items():
        print(f"{c_tag:<24} | {stat['attempts']:>8} | {stat['accuracy']:>7.1f}% | {stat['mastery']:>10.1f}% | {stat['ewma_accuracy']:>5.1f}% | {stat['confidence']:<10}")

    # Misconceptions summary
    misc = report["misconceptions"]
    print("\nMisconception Tracking:")
    print(f"  Active   ({len(misc['active'])}):")
    for m in misc["active"]:
        print(f"    - [{m['misconception_id']}] (severity: {m['severity']:.2f}, chosen: {m['chosen']}/{m['offered']}, avoided streak: {m['avoided_streak']})")
        print(f"      Evidence: {m['evidence']}")
        if m.get("wrong_belief"):
            print(f"      Wrong belief: \"{m['wrong_belief']}\"")

    print(f"  Resolved ({len(misc['resolved'])}):")
    for m in misc["resolved"]:
        print(f"    - [{m['misconception_id']}] (chosen: {m['chosen']}/{m['offered']}, avoided streak: {m['avoided_streak']})")
        print(f"      Evidence: {m['evidence']}")

    print(f"  Suspected ({len(misc['suspected'])}):")
    for m in misc["suspected"][:3]:
        print(f"    - [{m['misconception_id']}] (chosen: {m['chosen']}/{m['offered']}, avoided streak: {m['avoided_streak']})")

    # Facet Map
    print("\nFacet Error Rates:")
    for c_tag, f_dict in report["facet_map"].items():
        for f_name, f_data in f_dict.items():
            weak_tag = " [WEAK]" if f_data["weak"] else ""
            print(f"  {c_tag} :: {f_name:<16} : {f_data['chosen']}/{f_data['offered']} errors ({f_data['error_rate']*100:.0f}%){weak_tag}")

    # Skill Profile
    prof = report["skill_profile"]
    print("\nSkill Profile by Question Type:")
    for qt, data in prof["overall"].items():
        print(f"  {qt:<14} : {data['correct']}/{data['attempts']} correct ({data['accuracy']:.1f}%)")
    if prof["skill_gaps"]:
        print("\nSkill Gap Findings:")
        for gap in prof["skill_gaps"]:
            print(f"  -> {gap}")


def main():
    print("=" * 80)
    print("  EDUGEN PHASE 5: PERFORMANCE ANALYSIS AGENT EVALUATION DEMO")
    print("=" * 80)

    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "pa_demo.db")
    os.environ["EDUGEN_DB_PATH"] = db_path
    init_db(db_path)

    try:
        create_demo_data(db_path)
        agent = PerformanceAnalysisAgent()

        print_student_report(agent, 1, "Profile A: Student with Persistent Misconception", db_path)
        print_student_report(agent, 2, "Profile B: Student Who Overcame / Remediated Misconception", db_path)
        print_student_report(agent, 3, "Profile C: Student with Theory vs Tracing Skill Gap", db_path)
        print_student_report(agent, 4, "Profile D: Student Exhibiting Random Guessing", db_path)

        print("\n" + "=" * 80)
        print("  DEMO COMPLETE: All four diagnostic profiles successfully evaluated.")
        print("=" * 80)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.environ.pop("EDUGEN_DB_PATH", None)


if __name__ == "__main__":
    main()
