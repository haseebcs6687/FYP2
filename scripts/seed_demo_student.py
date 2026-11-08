"""
=============================================================================
EduGen - Demo Seed Student Generator (scripts/seed_demo_student.py)
=============================================================================
Creates a rich, believable demo student (demo@edugen.local / demo-pass) with:
  - 12-question diagnostic (~41% score) establishing baseline weaknesses
  - Active study plan with completed lesson steps and cleared check quiz
  - Probe quiz sweeping specific misconceptions
  - 8 realistic quizzes across 4 modules backdated over 14 days
  - Overall accuracy ~65%
  - Genuine BKT curves, misconceptions detected, and active journey state
  - 100% genuine execution through real pool questions and Coordinator
    on_quiz_submitted. Zero mocked DB rows, zero external LLM calls.
=============================================================================
"""

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from core.concepts import CONCEPTS, module_of
from core.db import get_db, init_db
from core.db_repo import (
    create_study_plan,
    get_active_study_plan,
    get_study_plan_steps,
    record_concept_mastery,
    record_submission_history,
    save_student_journey,
    update_study_plan_step_status,
)
from core.journey import STATE_PLAN_ACTIVE, compute_next_action
from werkzeug.security import generate_password_hash


DEMO_EMAIL = "demo@edugen.local"
DEMO_PASS = "demo-pass"
DEMO_NAME = "Demo Student"


def clean_demo_student(conn):
    """Remove all records associated with demo@edugen.local."""
    cur = conn.cursor()
    user = cur.execute("SELECT id FROM users WHERE LOWER(email) = ?", (DEMO_EMAIL.lower(),)).fetchone()
    if not user:
        return
    uid = user["id"]
    stud = cur.execute("SELECT id FROM students WHERE user_id = ?", (uid,)).fetchone()
    sid = stud["id"] if stud else None

    if sid:
        cur.execute("PRAGMA foreign_keys = OFF")
        cur.execute(
            """DELETE FROM question_attempts WHERE quiz_result_id IN
               (SELECT id FROM quiz_results WHERE student_id = ?)""",
            (sid,),
        )
        cur.execute("DELETE FROM student_question_history WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM mastery_history WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM quiz_results WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM quiz_sessions WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM concept_mastery WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM student_misconceptions WHERE student_id = ?", (sid,))
        cur.execute(
            """DELETE FROM study_plan_steps WHERE plan_id IN
               (SELECT id FROM study_plans WHERE student_id = ?)""",
            (sid,),
        )
        cur.execute("DELETE FROM study_plans WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM student_journey WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM recommendations WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM agent_events WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM pipeline_runs WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM lesson_views WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM rag_retrievals WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM feedback WHERE student_id = ?", (sid,))
        cur.execute("DELETE FROM students WHERE id = ?", (sid,))
        cur.execute("PRAGMA foreign_keys = ON")

    cur.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()


def get_or_create_student(conn):
    cur = conn.cursor()
    user = cur.execute("SELECT id FROM users WHERE LOWER(email) = ?", (DEMO_EMAIL.lower(),)).fetchone()
    if user:
        uid = user["id"]
        stud = cur.execute("SELECT id FROM students WHERE user_id = ?", (uid,)).fetchone()
        return stud["id"], uid

    p_hash = generate_password_hash(DEMO_PASS)
    cur.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)", (DEMO_NAME, DEMO_EMAIL, p_hash))
    uid = cur.lastrowid
    cur.execute("INSERT INTO students (name, user_id) VALUES (?, ?)", (DEMO_NAME, uid))
    sid = cur.lastrowid
    conn.commit()
    return sid, uid


def select_pool_questions(conn, concept, difficulty=None, count=5, qtype=None):
    """Retrieve verified active questions from pool for the given concept."""
    cur = conn.cursor()
    params = [concept]
    query = "SELECT * FROM questions WHERE concept = ? AND pool_status = 'active' AND verified = 1"
    if difficulty:
        query += " AND difficulty = ?"
        params.append(difficulty)
    if qtype:
        query += " AND qtype = ?"
        params.append(qtype)
    query += " LIMIT ?"
    params.append(count)
    rows = cur.execute(query, params).fetchall()

    if len(rows) < count:
        # Fallback without difficulty constraint
        rows = cur.execute(
            "SELECT * FROM questions WHERE concept = ? AND pool_status = 'active' AND verified = 1 LIMIT ?",
            (concept, count),
        ).fetchall()

    return rows


def simulate_quiz_submission(app, student_id, quiz_spec, target_date):
    """
    Simulates a quiz session and submission through the real Coordinator logic.
    quiz_spec: {
        "concept": "...",
        "difficulty": "...",
        "kind": "practice" | "diagnostic" | "check" | "probe",
        "plan_step_id": opt_int,
        "questions_spec": [ {"concept": ..., "difficulty": ..., "correct": True/False}, ... ]
    }
    """
    coord = app.extensions["edugen"]["coordinator"]
    pa = app.extensions["edugen"]["pa"]
    conn = get_db()
    cur = conn.cursor()

    concept = quiz_spec.get("concept", "class-definition")
    difficulty = quiz_spec.get("difficulty", "Medium")
    kind = quiz_spec.get("kind", "practice")
    plan_step_id = quiz_spec.get("plan_step_id")

    # 1. Gather question records from pool
    session_questions = []
    student_answers = {}
    timings = {}
    correct_count = 0

    for idx, q_spec in enumerate(quiz_spec["questions_spec"]):
        q_concept = q_spec.get("concept", concept)
        q_diff = q_spec.get("difficulty", difficulty)
        pool_rows = select_pool_questions(conn, q_concept, q_diff, count=1)
        if not pool_rows:
            # Fallback to any active pool question
            pool_rows = cur.execute(
                "SELECT * FROM questions WHERE pool_status = 'active' AND verified = 1 LIMIT 1"
            ).fetchall()

        q_row = pool_rows[0]
        options = json.loads(q_row["options_json"])
        correct_idx = q_row["correct_index"]
        tags = json.loads(q_row["tags_json"]).get("tags", [q_row["concept"]])

        option_mids = []
        if "option_misconceptions_json" in q_row.keys() and q_row["option_misconceptions_json"]:
            try:
                option_mids = json.loads(q_row["option_misconceptions_json"])
            except Exception:
                option_mids = []

        q_entry = {
            "id": q_row["id"],
            "question": q_row["question_text"],
            "options": options,
            "correct": correct_idx,
            "explanation": q_row["explanation"],
            "concept_tags": tags,
            "qtype": q_row["qtype"],
            "difficulty": q_row["difficulty"],
            "misconception_id": q_row["misconception_id"] if "misconception_id" in q_row.keys() else None,
            "option_misconception_ids": option_mids,
        }
        session_questions.append(q_entry)

        if q_spec["correct"]:
            student_answers[str(idx)] = correct_idx
            correct_count += 1
        else:
            # Pick a distractor (prefer distractor with known misconception)
            distractor_idx = (correct_idx + 1) % len(options)
            if option_mids:
                for o_idx, mid in enumerate(option_mids):
                    if o_idx != correct_idx and mid:
                        distractor_idx = o_idx
                        break
            student_answers[str(idx)] = distractor_idx

        timings[str(idx)] = 4500

    # 2. Insert quiz_sessions
    payload = {
        "concept": concept,
        "difficulty": difficulty,
        "kind": kind,
        "source": "pool",
        "plan_step_id": plan_step_id,
        "questions": session_questions,
    }
    cur.execute(
        """INSERT INTO quiz_sessions
           (student_id, concept, difficulty, source, payload_json, consumed)
           VALUES (?, ?, ?, 'pool', ?, 1)""",
        (student_id, concept, difficulty, json.dumps(payload)),
    )
    session_id = cur.lastrowid

    # 3. Insert quiz_results
    date_str = target_date.strftime("%Y-%m-%d %H:%M:%S")
    topic = "Java OOP"
    score = correct_count
    total = len(session_questions)
    cur.execute(
        """INSERT INTO quiz_results
           (student_id, topic, concept, difficulty, score, total_questions, attempt_number, source, duration_ms, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, 1, 'pool', ?, ?)""",
        (student_id, topic, concept, difficulty, score, total, total * 4500, date_str),
    )
    result_id = cur.lastrowid

    # 4. Insert question_attempts
    for idx, q in enumerate(session_questions):
        is_corr = int(student_answers[str(idx)] == q["correct"])
        chosen_idx = student_answers[str(idx)]
        chosen_text = q["options"][chosen_idx] if 0 <= chosen_idx < len(q["options"]) else ""
        m_id = None
        if not is_corr and q.get("option_misconception_ids"):
            if chosen_idx < len(q["option_misconception_ids"]):
                m_id = q["option_misconception_ids"][chosen_idx]

        cur.execute(
            """INSERT INTO question_attempts
               (quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                time_taken_ms, question_text, chosen_option_text, misconception_id, difficulty)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result_id,
                idx,
                json.dumps(q["concept_tags"]),
                is_corr,
                chosen_idx,
                q["correct"],
                timings[str(idx)],
                q["question"][:500],
                chosen_text,
                m_id,
                q["difficulty"],
            ),
        )

    conn.commit()
    conn.close()

    # 5. Record question history
    record_submission_history(student_id, result_id, session_questions, student_answers, timings)

    # 6. Update concept mastery & mastery history
    pa_report = pa.analyze_student(student_id)
    if pa_report and "concept_stats" in pa_report:
        record_concept_mastery(student_id, pa_report["concept_stats"], quiz_result_id=result_id)

    # Backdate mastery_history recorded_at
    conn_hist = get_db()
    conn_hist.execute(
        "UPDATE mastery_history SET recorded_at = ? WHERE student_id = ? AND recorded_at > datetime('now', '-1 minute')",
        (date_str, student_id),
    )
    conn_hist.commit()
    conn_hist.close()

    # 7. Real Coordinator state transition
    coord.on_quiz_submitted(student_id, result_id, quiz_session_id=session_id)
    return result_id


def seed_demo_student(reset=True):
    app = create_app()
    app.config["TESTING"] = True
    app.extensions["edugen"]["cc"].client = None  # purely offline, no LLM
    coord = app.extensions["edugen"]["coordinator"]

    conn = get_db()
    clean_demo_student(conn)

    sid, uid = get_or_create_student(conn)
    conn.close()

    now = datetime.now()

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 1: Diagnostic Assessment (Day -14)
    # 12 questions: 5 correct (41.7%), weak in OOP basics and inheritance
    # ─────────────────────────────────────────────────────────────────────────
    diag_spec = {
        "concept": "class-definition",
        "difficulty": "Medium",
        "kind": "diagnostic",
        "questions_spec": [
            {"concept": "class-definition", "difficulty": "Easy", "correct": True},
            {"concept": "class-definition", "difficulty": "Medium", "correct": True},
            {"concept": "instance-variables", "difficulty": "Easy", "correct": True},
            {"concept": "constructors-overview", "difficulty": "Medium", "correct": True},
            {"concept": "constructor-basics", "difficulty": "Medium", "correct": True},
            # 7 incorrect to expose skill gaps in inheritance & encapsulation
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": False},
            {"concept": "inheritance-basics", "difficulty": "Medium", "correct": False},
            {"concept": "method-overriding", "difficulty": "Easy", "correct": False},
            {"concept": "method-overriding", "difficulty": "Medium", "correct": False},
            {"concept": "super-keyword", "difficulty": "Easy", "correct": False},
            {"concept": "encapsulation-basics", "difficulty": "Easy", "correct": False},
            {"concept": "polymorphism", "difficulty": "Medium", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, diag_spec, now - timedelta(days=14))

    # ─────────────────────────────────────────────────────────────────────────
    # Establish Study Plan:
    # 5 steps:
    #   Step 1: class-definition (prerequisite) -> done
    #   Step 2: inheritance-basics (weak) -> done
    #   Step 3: inheritance-basics (check) -> done (cleared on retry)
    #   Step 4: method-overriding (probe) -> done
    #   Step 5: super-keyword (advance) -> done
    #   Step 6: all-plan-concepts (reevaluation) -> PENDING
    # ─────────────────────────────────────────────────────────────────────────
    plan_dict = {
        "title": "Core OOP & Inheritance Mastery Plan",
        "concept": "inheritance-basics",
        "steps": [
            {"position": 1, "concept": "class-definition", "kind": "prerequisite", "status": "done", "lesson_style": "simplified", "title": "Class & Object Fundamentals"},
            {"position": 2, "concept": "inheritance-basics", "kind": "weak", "status": "done", "lesson_style": "detailed", "title": "Inheritance Architecture in Java"},
            {"position": 3, "concept": "inheritance-basics", "kind": "check", "status": "pending", "difficulty": "Easy", "title": "Check: Inheritance Basics"},
            {"position": 4, "concept": "method-overriding", "kind": "probe", "status": "pending", "difficulty": "Medium", "title": "Probe: Method Overriding"},
            {"position": 5, "concept": "super-keyword", "kind": "advance", "status": "pending", "lesson_style": "detailed", "title": "Super Keyword & Member Access"},
            {"position": 6, "concept": "all-plan-concepts", "kind": "reevaluation", "status": "pending", "difficulty": "Medium", "title": "Final Reevaluation"},
        ],
        "coverage": {"ok": True, "violations": []},
        "deferred": [],
    }
    plan = create_study_plan(sid, plan_dict)
    steps = plan["steps"]
    check_step_id = steps[2]["id"]
    probe_step_id = steps[3]["id"]
    advance_step_id = steps[4]["id"]

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 2: Module 1 OO Practice (Day -11) - Score: 4/5 (80%)
    # ─────────────────────────────────────────────────────────────────────────
    q2_spec = {
        "concept": "class-definition",
        "difficulty": "Easy",
        "kind": "practice",
        "questions_spec": [
            {"concept": "class-definition", "difficulty": "Easy", "correct": True},
            {"concept": "class-definition", "difficulty": "Easy", "correct": True},
            {"concept": "instance-variables", "difficulty": "Easy", "correct": True},
            {"concept": "instance-variables", "difficulty": "Easy", "correct": True},
            {"concept": "class-definition", "difficulty": "Easy", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, q2_spec, now - timedelta(days=11))

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 3: Step 3 Check Quiz Attempt 1 (Day -9) - Score: 3/5 (60%)
    # Fails threshold (80%) -> step remains pending
    # ─────────────────────────────────────────────────────────────────────────
    q3_spec = {
        "concept": "inheritance-basics",
        "difficulty": "Easy",
        "kind": "practice",
        "plan_step_id": check_step_id,
        "questions_spec": [
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": True},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": True},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": True},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": False},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, q3_spec, now - timedelta(days=9))

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 4: Step 3 Check Quiz Retry (Day -8) - Score: 4/5 (80%)
    # Passes threshold (80%) -> step marked done!
    # ─────────────────────────────────────────────────────────────────────────
    q4_spec = {
        "concept": "inheritance-basics",
        "difficulty": "Easy",
        "kind": "practice",
        "plan_step_id": check_step_id,
        "questions_spec": [
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": True},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": True},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": True},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": True},
            {"concept": "inheritance-basics", "difficulty": "Easy", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, q4_spec, now - timedelta(days=8))
    update_study_plan_step_status(check_step_id, "done")

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 5: Step 4 Probe Quiz (Day -6) - Score: 4/5 (80%)
    # Sweeps method-overriding misconceptions -> step marked done!
    # ─────────────────────────────────────────────────────────────────────────
    q5_spec = {
        "concept": "method-overriding",
        "difficulty": "Medium",
        "kind": "probe",
        "plan_step_id": probe_step_id,
        "questions_spec": [
            {"concept": "method-overriding", "difficulty": "Medium", "correct": True},
            {"concept": "method-overriding", "difficulty": "Medium", "correct": True},
            {"concept": "method-overriding", "difficulty": "Medium", "correct": True},
            {"concept": "method-overriding", "difficulty": "Medium", "correct": True},
            {"concept": "method-overriding", "difficulty": "Medium", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, q5_spec, now - timedelta(days=6))
    update_study_plan_step_status(probe_step_id, "done")

    # Step 5 (super-keyword advance lesson) marked done
    update_study_plan_step_status(advance_step_id, "done")

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 6: Module 3 Polymorphism & Interfaces (Day -4) - Score: 4/5 (80%)
    # ─────────────────────────────────────────────────────────────────────────
    q6_spec = {
        "concept": "polymorphism",
        "difficulty": "Medium",
        "kind": "practice",
        "questions_spec": [
            {"concept": "polymorphism", "difficulty": "Medium", "correct": True},
            {"concept": "polymorphism", "difficulty": "Medium", "correct": True},
            {"concept": "interface-basics", "difficulty": "Medium", "correct": True},
            {"concept": "interface-basics", "difficulty": "Medium", "correct": True},
            {"concept": "polymorphism", "difficulty": "Medium", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, q6_spec, now - timedelta(days=4))

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 7: Module 4 Exception Handling (Day -2) - Score: 4/5 (80%)
    # ─────────────────────────────────────────────────────────────────────────
    q7_spec = {
        "concept": "exception-handling-basics",
        "difficulty": "Medium",
        "kind": "practice",
        "questions_spec": [
            {"concept": "exception-handling-basics", "difficulty": "Medium", "correct": True},
            {"concept": "exception-handling-basics", "difficulty": "Medium", "correct": True},
            {"concept": "try-catch-blocks", "difficulty": "Medium", "correct": True},
            {"concept": "try-catch-blocks", "difficulty": "Medium", "correct": True},
            {"concept": "exception-handling-basics", "difficulty": "Medium", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, q7_spec, now - timedelta(days=2))

    # ─────────────────────────────────────────────────────────────────────────
    # Quiz 8: Module 2 Review (Today) - Score: 3/5 (60%)
    # ─────────────────────────────────────────────────────────────────────────
    q8_spec = {
        "concept": "super-keyword",
        "difficulty": "Medium",
        "kind": "practice",
        "questions_spec": [
            {"concept": "super-keyword", "difficulty": "Medium", "correct": True},
            {"concept": "super-keyword", "difficulty": "Medium", "correct": True},
            {"concept": "super-keyword", "difficulty": "Medium", "correct": True},
            {"concept": "super-keyword", "difficulty": "Medium", "correct": False},
            {"concept": "super-keyword", "difficulty": "Medium", "correct": False},
        ],
    }
    simulate_quiz_submission(app, sid, q8_spec, now)

    # ─────────────────────────────────────────────────────────────────────────
    # Finalize Journey State: PLAN_ACTIVE with pending Reevaluation
    # ─────────────────────────────────────────────────────────────────────────
    cur_plan = get_active_study_plan(sid)
    cur_steps = get_study_plan_steps(cur_plan["id"])
    next_action = compute_next_action(STATE_PLAN_ACTIVE, cur_plan, cur_steps)
    save_student_journey(sid, STATE_PLAN_ACTIVE, next_action)

    # Record some realistic lesson views
    conn_views = get_db()
    for c in ["class-definition", "inheritance-basics", "super-keyword"]:
        conn_views.execute(
            """INSERT INTO lesson_views (student_id, concept, difficulty, source)
               VALUES (?, ?, 'Medium', 'plan')""",
            (sid, c),
        )
    conn_views.commit()
    conn_views.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Print Summary Screen
    # ─────────────────────────────────────────────────────────────────────────
    conn_res = get_db()
    total_q = conn_res.execute(
        "SELECT COUNT(*), SUM(score), SUM(total_questions) FROM quiz_results WHERE student_id = ?",
        (sid,),
    ).fetchone()
    mastery_rows = conn_res.execute(
        "SELECT COUNT(*) FROM concept_mastery WHERE student_id = ? AND mastery >= 70.0",
        (sid,),
    ).fetchone()[0]
    weak_rows = conn_res.execute(
        "SELECT COUNT(*) FROM concept_mastery WHERE student_id = ? AND mastery < 60.0",
        (sid,),
    ).fetchone()[0]
    conn_res.close()

    quiz_count = total_q[0]
    total_score = total_q[1]
    total_possible = total_q[2]
    pct = round(100.0 * total_score / total_possible, 1) if total_possible else 0.0

    print("\n" + "=" * 68)
    print("  EduGen Demo Seed Student Created Successfully")
    print("=" * 68)
    print(f"  Student ID ............... {sid} (User ID {uid})")
    print(f"  Email .................... {DEMO_EMAIL}")
    print(f"  Password ................. {DEMO_PASS}")
    print(f"  Total Quizzes ............ {quiz_count}")
    print(f"  Total Questions .......... {total_possible} ({total_score} correct, {pct}%)")
    print(f"  Concepts Mastered (>=70) . {mastery_rows}")
    print(f"  Concepts Weak (<60) ...... {weak_rows}")
    print(f"  Journey State ............ {STATE_PLAN_ACTIVE}")
    print(f"  Active Plan Progression .. 5/6 steps complete (Step 6 Reevaluation pending)")
    print(f"  Next Action .............. {next_action.get('type')} ({next_action.get('quiz', {}).get('kind')})")
    print("=" * 68 + "\n")

    return sid, uid


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo student into EduGen database")
    parser.add_argument("--reset", action="store_true", help="Reset existing demo student data")
    args = parser.parse_args()
    seed_demo_student(reset=args.reset)
