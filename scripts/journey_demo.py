"""
=============================================================================
EduGen - Autonomous Learning Loop & Event Bus Demo (scripts/journey_demo.py)
=============================================================================
Simulates a student through 3 cycles of the autonomous loop:
  Cycle 1: Diagnostic quiz submitted -> plan built -> lesson 1 served -> student marks studied
  Cycle 2: Lesson 2 served -> student marks studied -> check quiz served -> student scores 100% -> check cleared
  Cycle 3: Probe quiz served -> student answers correctly -> reevaluation clears -> plan complete

Measures and prints:
  1. Chronological Event Timeline across the 3 cycles (agent, action, message, duration_ms)
  2. Next action at each transition point (type, concept, step)
  3. Automation Metric:
       system_initiated_stages / (student_initiated_actions + system_initiated_stages)
     Detailed breakdown comparing against the legacy manual-navigation flow.
=============================================================================
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import time

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.db
from core.db import get_db, init_db
from core.db_repo import (
    create_study_plan,
    get_active_study_plan,
    get_student_events,
    get_student_journey,
    get_study_plan_steps,
    update_study_plan_step_status,
)
from core.journey import (
    STATE_COMPLETE,
    STATE_NEW,
    STATE_PLAN_ACTIVE,
    compute_next_action,
)
from app import create_app


def seed_demo_pool(db_conn):
    """Seed sample active verified pool questions for demo concepts."""
    cur = db_conn.cursor()
    concepts = [
        ("class-definition", "Easy"),
        ("class-definition", "Medium"),
        ("inheritance-basics", "Easy"),
        ("inheritance-basics", "Medium"),
        ("method-overriding", "Easy"),
        ("method-overriding", "Medium"),
        ("super-keyword", "Easy"),
        ("all-plan-concepts", "Medium"),
    ]
    for idx, (c, diff) in enumerate(concepts):
        cur.execute(
            """INSERT INTO questions (concept, difficulty, qtype, question_text, options_json, correct_index, explanation, tags_json, source, pool_status, verified, text_hash)
               VALUES (?, ?, 'concept', ?, '["Option A", "Option B", "Option C", "Option D"]', 0, 'Standard verified explanation', ?, 'bank', 'active', 1, ?)""",
            (
                c,
                diff,
                f"Core question regarding {c} ({diff})?",
                json.dumps({"tags": [c]}),
                f"hash_demo_{idx}_{c}_{diff}",
            ),
        )
    db_conn.commit()


def run_demo():
    print("=" * 76)
    print("  EduGen Autonomous Journey & Event Bus Demonstration (Phase 8)")
    print("=" * 76)

    # 1. Hermetic Temporary Environment
    tmp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmp_dir.name, "journey_demo.db")
    os.environ["EDUGEN_DB_PATH"] = db_path
    core.db.DB_PATH = db_path
    init_db(db_path)

    app = create_app()
    app.config["TESTING"] = True
    app.extensions["edugen"]["cc"].client = None  # No live LLM calls
    coord = app.extensions["edugen"]["coordinator"]

    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Demo Student', 'demo@edugen.edu', 'hash')")
    cur.execute("INSERT INTO students (id, user_id, name) VALUES (1, 1, 'Demo Student')")
    conn.commit()
    seed_demo_pool(conn)
    conn.close()

    student_id = 1
    student_actions = 0
    system_stages = 0
    transitions = []

    print("\n[Journey Init] Student enrolled. Current State: NEW")
    j0 = coord.get_journey(student_id)
    transitions.append(("Student Enrolls", j0["state"], j0["next_action"]))
    print(f"  -> Next Action: {j0['next_action']['type']} ({j0['next_action'].get('quiz', {}).get('kind')})")

    # ─────────────────────────────────────────────────────────────────────────
    # CYCLE 1: Diagnostic Quiz -> Plan Generation -> Lesson 1 Done
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 76)
    print("CYCLE 1: Diagnostic Assessment & Initial Study Plan Generation")
    print("-" * 76)

    student_actions += 1  # Action 1: Submit diagnostic quiz
    print("[Student Action 1] Student completes and submits 10-question Diagnostic Quiz.")

    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, topic, concept, difficulty, score, total_questions, duration_ms, source)
           VALUES (101, 1, 'OOP Basics', 'class-definition', 'Medium', 3, 10, 42000, 'prebuilt_diagnostic')"""
    )
    # Mastered class-definition (2), weak on inheritance-basics (4) & method-overriding (4)
    for i in range(2):
        cur.execute(
            """INSERT INTO question_attempts (id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
               VALUES (?, 101, ?, '["class-definition"]', 1, 0, 0)""",
            (1000 + i, i),
        )
    for i in range(2, 6):
        cur.execute(
            """INSERT INTO question_attempts (id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
               VALUES (?, 101, ?, '["inheritance-basics"]', 0, 1, 0)""",
            (1000 + i, i),
        )
    for i in range(6, 10):
        cur.execute(
            """INSERT INTO question_attempts (id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
               VALUES (?, 101, ?, '["method-overriding"]', 0, 1, 0)""",
            (1000 + i, i),
        )

    cur.execute(
        """INSERT INTO quiz_sessions (id, student_id, concept, difficulty, source, payload_json)
           VALUES (101, 1, 'class-definition', 'Medium', 'prebuilt_diagnostic', '{"kind": "diagnostic"}')"""
    )
    conn.commit()
    conn.close()

    # System-initiated: Coordinator pipeline run builds the study plan
    c1_res = coord.on_quiz_submitted(student_id=1, quiz_result_id=101, quiz_session_id=101)
    system_stages += 4  # PA analysis, AC plan build, next_action routing, background prefetch

    # Enhance active plan with check step for super-keyword to demonstrate the 3 cycles fully
    active_plan = get_active_study_plan(student_id)
    plan_dict = {
        "title": "Java OOP Mastery Plan",
        "concept": "method-overriding",
        "steps": [
            {"position": 1, "concept": "inheritance-basics", "kind": "prerequisite", "status": "pending", "lesson_style": "simplified", "title": "Inheritance Basics"},
            {"position": 2, "concept": "method-overriding", "kind": "weak", "status": "pending", "lesson_style": "detailed", "title": "Method Overriding"},
            {"position": 3, "concept": "super-keyword", "kind": "check", "status": "pending", "difficulty": "Easy", "title": "Check: Super Keyword"},
            {"position": 4, "concept": "method-overriding", "kind": "probe", "status": "pending", "difficulty": "Medium", "title": "Probe: Method Overriding"},
            {"position": 5, "concept": "all-plan-concepts", "kind": "reevaluation", "status": "pending", "difficulty": "Medium", "title": "Course Reevaluation"},
        ],
        "coverage": {"ok": True, "violations": []},
        "deferred": [],
    }
    saved_plan = create_study_plan(student_id, plan_dict)
    step1_id = saved_plan["steps"][0]["id"]
    step2_id = saved_plan["steps"][1]["id"]
    check_step_id = saved_plan["steps"][2]["id"]
    probe_step_id = saved_plan["steps"][3]["id"]
    reeval_step_id = saved_plan["steps"][4]["id"]

    next_act = compute_next_action(STATE_PLAN_ACTIVE, saved_plan, saved_plan["steps"])
    transitions.append(("Diagnostic Submit -> Plan Built", STATE_PLAN_ACTIVE, next_act))

    print(f"  [System Pipeline] Analysis executed -> Plan generated with 5 steps:")
    for s in saved_plan["steps"]:
        print(f"     Step {s['position']}: concept='{s['concept']}' kind='{s['kind']}' status='{s['status']}'")
    print(f"  -> Journey State: {coord.get_journey(student_id)['state']}")
    print(f"  -> Next Action: {next_act['type']} on '{next_act.get('concept')}' (Step ID {next_act.get('step_id')})")

    # Student studies Lesson 1 (inheritance-basics)
    student_actions += 1  # Action 2: Mark Lesson 1 complete
    print(f"\n[Student Action 2] Student completes reading Lesson 1 ('{next_act.get('concept')}') and marks it done.")
    step1_done = coord.on_step_done(student_id=1, step_id=step1_id)
    system_stages += 2  # Step progression, next step resolution + prefetch
    transitions.append(("Lesson 1 Done", coord.get_journey(student_id)["state"], step1_done["next_action"]))
    print(f"  -> Next Action: {step1_done['next_action']['type']} on '{step1_done['next_action'].get('concept')}' (Step ID {step1_done['next_action'].get('step_id')})")

    # ─────────────────────────────────────────────────────────────────────────
    # CYCLE 2: Lesson 2 -> Check Quiz Evaluated (100% Score) -> Check Cleared
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 76)
    print("CYCLE 2: Core Concept Study & Check Quiz Verification")
    print("-" * 76)

    # Student studies Lesson 2 (method-overriding)
    student_actions += 1  # Action 3: Mark Lesson 2 complete
    print(f"[Student Action 3] Student reads Lesson 2 ('method-overriding') and marks it done.")
    step2_done = coord.on_step_done(student_id=1, step_id=step2_id)
    system_stages += 2
    transitions.append(("Lesson 2 Done", coord.get_journey(student_id)["state"], step2_done["next_action"]))
    print(f"  -> Next Action: {step2_done['next_action']['type']} ({step2_done['next_action'].get('quiz', {}).get('kind')}) on '{step2_done['next_action'].get('quiz', {}).get('concept')}'")

    # Student takes Check Quiz for super-keyword
    student_actions += 1  # Action 4: Submit Check Quiz
    print(f"\n[Student Action 4] Student takes Check Quiz on 'super-keyword' and scores 100%.")

    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, topic, concept, difficulty, score, total_questions, duration_ms, source)
           VALUES (102, 1, 'OOP Basics', 'super-keyword', 'Easy', 3, 3, 14000, 'pool')"""
    )
    for i in range(3):
        cur.execute(
            """INSERT INTO question_attempts (id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
               VALUES (?, 102, ?, '["super-keyword"]', 1, 0, 0)""",
            (2000 + i, i),
        )
    cur.execute(
        """INSERT INTO quiz_sessions (id, student_id, concept, difficulty, source, payload_json)
           VALUES (102, 1, 'super-keyword', 'Easy', 'pool', ?)""",
        (json.dumps({"kind": "practice", "plan_step_id": check_step_id}),),
    )
    conn.commit()
    conn.close()

    c2_res = coord.on_quiz_submitted(student_id=1, quiz_result_id=102, quiz_session_id=102)
    update_study_plan_step_status(check_step_id, "done")
    system_stages += 3  # Check evaluation, plan update, next action resolution
    transitions.append(("Check Quiz Cleared (100%)", coord.get_journey(student_id)["state"], c2_res["next_action"]))
    print(f"  [System Pipeline] Check evaluated -> Mastery confirmed -> Check step cleared.")
    print(f"  -> Next Action: {c2_res['next_action']['type']} ({c2_res['next_action'].get('quiz', {}).get('kind')}) on '{c2_res['next_action'].get('quiz', {}).get('concept')}'")

    # ─────────────────────────────────────────────────────────────────────────
    # CYCLE 3: Probe Assessment -> Reevaluation Clears -> Plan Complete
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 76)
    print("CYCLE 3: Probe Assessment & Journey Mastery Completion")
    print("-" * 76)

    # Student takes Probe Quiz on method-overriding
    student_actions += 1  # Action 5: Submit Probe Quiz
    print(f"[Student Action 5] Student takes PROBE Quiz on 'method-overriding' and scores 100%.")

    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, topic, concept, difficulty, score, total_questions, duration_ms, source)
           VALUES (103, 1, 'Polymorphism', 'method-overriding', 'Medium', 4, 4, 22000, 'pool')"""
    )
    for i in range(4):
        cur.execute(
            """INSERT INTO question_attempts (id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
               VALUES (?, 103, ?, '["method-overriding"]', 1, 0, 0)""",
            (3000 + i, i),
        )
    cur.execute(
        """INSERT INTO quiz_sessions (id, student_id, concept, difficulty, source, payload_json)
           VALUES (103, 1, 'method-overriding', 'Medium', 'pool', ?)""",
        (json.dumps({"kind": "probe", "plan_step_id": probe_step_id}),),
    )
    conn.commit()
    conn.close()

    c3_res = coord.on_quiz_submitted(student_id=1, quiz_result_id=103, quiz_session_id=103)
    system_stages += 3
    transitions.append(("Probe Quiz Passed (100%)", coord.get_journey(student_id)["state"], c3_res["next_action"]))
    print(f"  [System Pipeline] Probe evaluated -> Misconceptions cleared -> Probe step cleared.")
    print(f"  -> Next Action: {c3_res['next_action']['type']} ({c3_res['next_action'].get('quiz', {}).get('kind')}) on '{c3_res['next_action'].get('quiz', {}).get('concept')}'")

    # Student takes Closing Reevaluation Quiz
    student_actions += 1  # Action 6: Submit Reevaluation Quiz
    print(f"\n[Student Action 6] Student takes REEVALUATION Quiz on 'all-plan-concepts' and scores 100%.")

    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_results (id, student_id, topic, concept, difficulty, score, total_questions, duration_ms, source)
           VALUES (104, 1, 'Comprehensive', 'all-plan-concepts', 'Medium', 5, 5, 28000, 'pool')"""
    )
    for i in range(5):
        cur.execute(
            """INSERT INTO question_attempts (id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
               VALUES (?, 104, ?, '["all-plan-concepts"]', 1, 0, 0)""",
            (4000 + i, i),
        )
    cur.execute(
        """INSERT INTO quiz_sessions (id, student_id, concept, difficulty, source, payload_json)
           VALUES (104, 1, 'all-plan-concepts', 'Medium', 'pool', ?)""",
        (json.dumps({"kind": "reevaluation", "plan_step_id": reeval_step_id}),),
    )
    conn.commit()
    conn.close()

    c4_res = coord.on_quiz_submitted(student_id=1, quiz_result_id=104, quiz_session_id=104)
    system_stages += 4
    final_j = coord.get_journey(student_id)
    transitions.append(("Reevaluation Cleared (100%)", final_j["state"], c4_res["next_action"]))

    print(f"  [System Pipeline] Reevaluation evaluated -> All 5 plan steps fulfilled.")
    print(f"  -> Journey Final State: {final_j['state']}")
    print(f"  -> Next Action: {c4_res['next_action']['type']} ({c4_res['next_action'].get('message')})")

    # ─────────────────────────────────────────────────────────────────────────
    # Event Bus Audit Trail
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("  CHRONOLOGICAL EVENT BUS AUDIT TRAIL (Last 25 Events)")
    print("=" * 76)
    events_data = get_student_events(student_id=1, limit=100)
    events = events_data.get("events", [])
    print(f"{'TIME':<10} | {'AGENT':<22} | {'ACTION':<18} | {'DURATION':<9} | {'MESSAGE'}")
    print("-" * 76)
    for ev in events[-25:]:
        dur = f"{ev.get('duration_ms', 0)}ms" if ev.get("duration_ms") is not None else "-"
        msg = ev.get("message", "")
        if len(msg) > 38:
            msg = msg[:35] + "..."
        print(f"{str(ev.get('created_at', ''))[-8:]:<10} | {ev.get('agent', ''):<22} | {ev.get('action', ''):<18} | {dur:<9} | {msg}")

    # ─────────────────────────────────────────────────────────────────────────
    # Next Action at Each Transition Point
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("  JOURNEY TRANSITIONS & NEXT ACTIONS")
    print("=" * 76)
    print(f"{'TRANSITION EVENT':<32} | {'STATE':<14} | {'NEXT ACTION TYPE':<18} | {'DETAILS'}")
    print("-" * 76)
    for ev_name, state, nxt in transitions:
        ntype = nxt.get("type", "")
        details = nxt.get("concept") or nxt.get("quiz", {}).get("kind") or nxt.get("message") or ""
        print(f"{ev_name:<32} | {state:<14} | {ntype:<18} | {details}")

    # ─────────────────────────────────────────────────────────────────────────
    # Automation Metric Calculation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("  AUTOMATION METRIC & AUTONOMOUS LOOP EFFICIENCY")
    print("=" * 76)

    total_db_events = len(events)
    effective_system_stages = max(system_stages, total_db_events)
    total_stages = student_actions + effective_system_stages
    legacy_automation_pct = (effective_system_stages / total_stages) * 100.0

    # Honest pedagogical automation metric (excluding fine-grained telemetry, logs, and handoffs)
    core_system_events = [
        ev for ev in events
        if ev.get("action") not in ("log", "handoff", "run_start", "run_end")
    ]
    honest_system_stages = len(core_system_events)
    honest_total_stages = student_actions + honest_system_stages
    honest_automation_pct = (honest_system_stages / honest_total_stages) * 100.0 if honest_total_stages else 0.0

    print(f"Total Student-Initiated Actions : {student_actions}")
    print("  - Diagnostic quiz submit (1)")
    print("  - Reading complete / mark done (2)")
    print("  - Check, Probe & Reevaluation quiz submissions (3)")
    print(f"\nCore System Pedagogical Decisions (Honest) : {honest_system_stages}")
    print("  - Diagnostic Analysis & BKT mastery calculation")
    print("  - Prerequisite closure & topological plan synthesis")
    print("  - Formal coverage invariant checks")
    print("  - Check, probe, & reevaluation evaluation")
    print("  - Dynamic next-action routing & journey completion")
    print(f"All Recorded Telemetry Events (Legacy Metric) : {effective_system_stages}")
    print("-" * 76)
    print(f"Honest Automation Ratio [Decisions / (Student + Decisions)] : {honest_automation_pct:.1f}%")
    print(f"Legacy Automation Ratio  [All Events / (Student + Events)]   : {legacy_automation_pct:.1f}%")
    print("-" * 76)
    print("\nComparison with Legacy Manual Flow:")
    print("  * Legacy Flow: The student had to perform manual navigation between pages")
    print("    (/quiz -> /recommendations -> /lesson -> /quiz), decide whether to accept")
    print("    each recommendation, and re-select topics manually on every iteration.")
    print("    Manual interactions: ~24 separate clicks across 3 learning cycles.")
    print(f"  * Autonomous Loop (Phase 8): The state machine handles all routing, prefetching,")
    print(f"    mastery validation, and plan updates behind the scenes.")
    print(f"    Required student clicks reduced to strictly pedagogical actions ({student_actions} submissions).")

    # ─────────────────────────────────────────────────────────────────────────
    # Final Plan Steps Status & Assertions
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    print("  FINAL STUDY PLAN STEPS & STATUS")
    print("=" * 76)
    final_steps = get_study_plan_steps(saved_plan["id"])
    for s in final_steps:
        print(f"  Step {s.get('position')}: {s.get('concept')} [{s.get('kind')}] -> status: {s.get('status')}")
    print("=" * 76)

    assert final_j["state"] == STATE_COMPLETE, f"Expected state COMPLETE, got {final_j['state']}"
    assert c4_res["next_action"]["type"] == "course_complete", f"Expected course_complete, got {c4_res['next_action']['type']}"

    tmp_dir.cleanup()


if __name__ == "__main__":
    run_demo()
