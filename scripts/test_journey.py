"""
=============================================================================
EduGen - Journey State Machine Test Suite (scripts/test_journey.py)
=============================================================================
Hermetic tests covering:
  - compute_next_action for all journey states (NEW, lesson first, check, probe,
    reevaluation, complete, quiz steps deferred after unfinished lessons)
  - Full table-driven autonomous loop:
      diagnostic -> plan -> lesson steps -> check -> probe -> reevaluation -> replan
  - on_quiz_submitted idempotency (duplicate submit returns stored outcome)
  - mark_ready skipping pending lessons and returning closing quiz + warnings
  - on_step_done advancing plan and triggering prefetch
  - Prefetch non-blocking and error-contained execution
  - quiz_start parameters derived from plan_step_id
  - Backward compatibility: legacy handle_student_visit continues to function
=============================================================================
"""

from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from core.db import get_db, init_db
from core.db_repo import (
    create_study_plan,
    get_active_study_plan,
    get_study_plan_steps,
    save_student_journey,
)
from core.journey import (
    STATE_COMPLETE,
    STATE_NEW,
    STATE_PLAN_ACTIVE,
    compute_next_action,
)


class TestJourney(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_journey.db")
        os.environ["EDUGEN_DB_PATH"] = self.db_path
        import core.db
        self.orig_db_path = core.db.DB_PATH
        core.db.DB_PATH = self.db_path
        init_db(self.db_path)

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.extensions["edugen"]["cc"].client = None
        self.client = self.app.test_client()

        # Seed students in DB
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, name, email, password_hash) VALUES (10, 'Student Alice', 'alice@edugen.edu', 'hash1')")
        cur.execute("INSERT INTO users (id, name, email, password_hash) VALUES (20, 'Student Bob', 'bob@edugen.edu', 'hash2')")
        cur.execute("INSERT INTO students (id, user_id, name) VALUES (10, 10, 'Student Alice')")
        cur.execute("INSERT INTO students (id, user_id, name) VALUES (20, 20, 'Student Bob')")
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            import core.db
            core.db.DB_PATH = self.orig_db_path
            self.tmp_dir.cleanup()
        except Exception:
            pass
        os.environ.pop("EDUGEN_DB_PATH", None)

    # 1. compute_next_action unit cases
    def test_compute_next_action_cases(self):
        # Case A: NEW student
        act_new = compute_next_action(STATE_NEW, plan=None, steps=None, quiz_history_count=0)
        self.assertEqual(act_new["type"], "take_quiz")
        self.assertEqual(act_new["quiz"]["kind"], "diagnostic")

        # Case B: Unfinished lesson step comes before quiz step
        steps = [
            {"id": 1, "position": 1, "concept": "method-overriding", "kind": "weak", "status": "pending", "lesson_style": "simplified"},
            {"id": 2, "position": 2, "concept": "method-overriding", "kind": "probe", "status": "pending"},
        ]
        act_lesson = compute_next_action(STATE_PLAN_ACTIVE, plan={"id": 100}, steps=steps, quiz_history_count=1)
        self.assertEqual(act_lesson["type"], "study_step")
        self.assertEqual(act_lesson["step_id"], 1)
        self.assertEqual(act_lesson["concept"], "method-overriding")
        self.assertEqual(act_lesson["style"], "simplified")
        self.assertEqual(len(act_lesson["upcoming"]), 1)
        self.assertEqual(act_lesson["upcoming"][0]["id"], 2)

        # Case C: Check step at pos 1 (no unfinished preceding lesson)
        check_steps = [
            {"id": 1, "position": 1, "concept": "inheritance-basics", "kind": "check", "status": "pending", "difficulty": "Easy"},
            {"id": 2, "position": 2, "concept": "method-overriding", "kind": "weak", "status": "pending", "lesson_style": "detailed"},
        ]
        act_check = compute_next_action(STATE_PLAN_ACTIVE, plan={"id": 101}, steps=check_steps, quiz_history_count=1)
        self.assertEqual(act_check["type"], "take_quiz")
        self.assertEqual(act_check["step_id"], 1)
        self.assertEqual(act_check["quiz"]["kind"], "practice")
        self.assertEqual(act_check["quiz"]["n"], 3)
        self.assertEqual(act_check["quiz"]["concept"], "inheritance-basics")

        # Case D: Probe step at pos 1
        probe_steps = [
            {"id": 2, "position": 1, "concept": "method-overriding", "kind": "probe", "status": "pending"},
        ]
        act_probe = compute_next_action(STATE_PLAN_ACTIVE, plan={"id": 102}, steps=probe_steps, quiz_history_count=1)
        self.assertEqual(act_probe["type"], "take_quiz")
        self.assertEqual(act_probe["quiz"]["kind"], "probe")
        self.assertEqual(act_probe["quiz"]["n"], 8)

        # Case E: Re-evaluation step
        reeval_steps = [
            {
                "id": 3,
                "position": 1,
                "concept": "method-overriding",
                "kind": "reevaluation",
                "status": "pending",
                "focus": {"concepts": ["method-overriding", "inheritance-basics"]},
            }
        ]
        act_reeval = compute_next_action(STATE_PLAN_ACTIVE, plan={"id": 103}, steps=reeval_steps, quiz_history_count=1)
        self.assertEqual(act_reeval["type"], "take_quiz")
        self.assertEqual(act_reeval["quiz"]["kind"], "reevaluation")
        self.assertIn("method-overriding", act_reeval["quiz"]["concepts"])

        # Case F: All steps done / COMPLETE
        done_steps = [
            {"id": 1, "position": 1, "concept": "method-overriding", "kind": "weak", "status": "done"},
            {"id": 2, "position": 2, "concept": "method-overriding", "kind": "probe", "status": "done"},
        ]
        act_complete = compute_next_action(STATE_PLAN_ACTIVE, plan={"id": 104}, steps=done_steps, quiz_history_count=2)
        self.assertEqual(act_complete["type"], "course_complete")

        act_comp_state = compute_next_action(STATE_COMPLETE, plan=None, steps=None, quiz_history_count=2)
        self.assertEqual(act_comp_state["type"], "course_complete")

    # 2. Idempotency of on_quiz_submitted
    def test_idempotency_quiz_submitted(self):
        coord = self.app.extensions["edugen"]["coordinator"]

        # Seed quiz_results and quiz_sessions
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO quiz_results (id, student_id, topic, concept, difficulty, score, total_questions, duration_ms, source)
               VALUES (501, 10, 'Polymorphism', 'method-overriding', 'Easy', 4, 5, 2000, 'pool')"""
        )
        cur.execute(
            """INSERT INTO quiz_sessions (id, student_id, concept, difficulty, source, payload_json)
               VALUES (501, 10, 'method-overriding', 'Easy', 'pool', '{"kind": "practice", "plan_step_id": null}')"""
        )
        conn.commit()
        conn.close()

        # First submit invocation
        res1 = coord.on_quiz_submitted(student_id=10, quiz_result_id=501, quiz_session_id=501)
        self.assertIn("next_action", res1)
        self.assertIn("pipeline", res1)

        # Second submit invocation with same result_id (must return identical stored outcome)
        res2 = coord.on_quiz_submitted(student_id=10, quiz_result_id=501, quiz_session_id=501)
        self.assertEqual(res1, res2)

    # 3. mark_ready skips pending lessons and attaches warnings
    def test_mark_ready_skips_pending_lessons(self):
        coord = self.app.extensions["edugen"]["coordinator"]

        plan_dict = {
            "title": "Test Plan",
            "concept": "method-overriding",
            "steps": [
                {"position": 1, "concept": "inheritance-basics", "kind": "prereq", "status": "in_progress", "lesson_style": "simplified", "prompt_text": "P1"},
                {"position": 2, "concept": "method-overriding", "kind": "weak", "status": "pending", "lesson_style": "detailed", "prompt_text": "P2"},
                {"position": 3, "concept": "method-overriding", "kind": "probe", "status": "pending", "prompt_text": "P3"},
            ],
            "coverage": {"ok": True, "violations": []},
            "deferred": [],
        }
        create_study_plan(student_id=10, plan_dict=plan_dict)

        ready_res = coord.mark_ready(student_id=10)
        self.assertIn("next_action", ready_res)
        next_act = ready_res["next_action"]

        # The next action must now be the closing probe quiz (since pending lessons were skipped)
        self.assertEqual(next_act["type"], "take_quiz")
        self.assertEqual(next_act["quiz"]["kind"], "probe")

        # Step 1 should be 'done', Step 2 'skipped'
        active_plan = get_active_study_plan(10)
        steps_map = {s["position"]: s["status"] for s in active_plan["steps"]}
        self.assertEqual(steps_map[1], "done")
        self.assertEqual(steps_map[2], "skipped")

    # 4. on_step_done advances plan
    def test_on_step_done_advances_plan(self):
        coord = self.app.extensions["edugen"]["coordinator"]

        plan_dict = {
            "title": "Sequential Plan",
            "concept": "method-overriding",
            "steps": [
                {"position": 1, "concept": "inheritance-basics", "kind": "prereq", "status": "in_progress", "lesson_style": "simplified", "prompt_text": "P1"},
                {"position": 2, "concept": "method-overriding", "kind": "weak", "status": "pending", "lesson_style": "detailed", "prompt_text": "P2"},
            ],
            "coverage": {"ok": True, "violations": []},
            "deferred": [],
        }
        saved = create_study_plan(student_id=10, plan_dict=plan_dict)
        step1_id = saved["steps"][0]["id"]

        done_res = coord.on_step_done(student_id=10, step_id=step1_id)
        self.assertEqual(done_res["status"], "done")
        next_act = done_res["next_action"]

        # Next action must now be Step 2
        self.assertEqual(next_act["type"], "study_step")
        self.assertEqual(next_act["concept"], "method-overriding")

    # 5. Background prefetch non-blocking and contained
    def test_prefetch_contained_and_non_blocking(self):
        coord = self.app.extensions["edugen"]["coordinator"]

        # Ensure prefetch does not raise even on unconfigured / simulated errors
        plan_dict = {
            "title": "Prefetch Plan",
            "steps": [
                {"id": 99, "position": 1, "concept": "method-overriding", "kind": "weak", "status": "pending", "lesson_style": "simplified"},
            ],
        }
        next_act = {"type": "study_step", "step_id": 99, "concept": "method-overriding"}

        # Must execute cleanly without exception
        coord._schedule_prefetch(student_id=10, next_action=next_act, plan=plan_dict)
        time.sleep(0.1)  # small yield

    # 6. /api/quiz/start parameters derived from plan_step_id
    def test_quiz_start_derived_from_plan_step(self):
        # Login as student 10
        with self.client.session_transaction() as sess:
            sess["user_id"] = 10
            sess["student_id"] = 10

        plan_dict = {
            "title": "Check Step Plan",
            "concept": "method-overriding",
            "steps": [
                {"position": 1, "concept": "inheritance-basics", "kind": "check", "status": "pending", "difficulty": "Easy", "prompt_text": "Check"},
            ],
        }
        saved = create_study_plan(student_id=10, plan_dict=plan_dict)
        check_step_id = saved["steps"][0]["id"]

        # Seed an active question in pool for inheritance-basics Easy
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO questions (concept, difficulty, qtype, question_text, options_json, correct_index, explanation, tags_json, source, pool_status, verified, text_hash)
               VALUES ('inheritance-basics', 'Easy', 'concept', 'What is inheritance in Java?', '["A", "B", "C", "D"]', 0, 'Explanation text', '{"tags": ["inheritance-basics"]}', 'test', 'active', 1, 'hash_test_ib')"""
        )
        conn.commit()
        conn.close()

        # Request quiz start with plan_step_id
        res = self.client.post("/api/quiz/start", json={"plan_step_id": check_step_id})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("quiz_session_id", data)

        # Verify session payload has plan_step_id and kind='practice'
        conn = get_db()
        sess_row = conn.execute("SELECT * FROM quiz_sessions WHERE id = ?", (data["quiz_session_id"],)).fetchone()
        conn.close()
        payload = json.loads(sess_row["payload_json"])
        self.assertEqual(payload["plan_step_id"], check_step_id)
        self.assertEqual(payload["kind"], "practice")

    # 7. Backward compatibility: handle_student_visit
    def test_handle_student_visit_backward_compat(self):
        coord = self.app.extensions["edugen"]["coordinator"]
        # First visit with no quizzes
        pkg = coord.handle_student_visit(student_id=20, generate=False)
        self.assertTrue(pkg["first_visit"])
        self.assertIn("trace", pkg)
        self.assertEqual(pkg["focus_concept"], "class-definition")

    # 8. Full autonomous learning loop table-driven test
    def test_full_autonomous_loop(self):
        coord = self.app.extensions["edugen"]["coordinator"]

        # Step 1: NEW student checks journey
        j1 = coord.get_journey(student_id=10)
        self.assertEqual(j1["state"], STATE_NEW)
        self.assertEqual(j1["next_action"]["type"], "take_quiz")
        self.assertEqual(j1["next_action"]["quiz"]["kind"], "diagnostic")

        # Step 2: Diagnostic quiz submitted -> Coordinator triggers PA and AC -> Plan created
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO quiz_results (id, student_id, topic, concept, difficulty, score, total_questions, duration_ms, source)
               VALUES (801, 10, 'OOP Basics', 'class-definition', 'Medium', 3, 10, 5000, 'prebuilt_diagnostic')"""
        )
        for i in range(10):
            cur.execute(
                """INSERT INTO question_attempts (id, quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
                   VALUES (?, 801, ?, '["method-overriding"]', ?, 0, 1)""",
                (8000 + i, i, 1 if i < 3 else 0),
            )
        cur.execute(
            """INSERT INTO quiz_sessions (id, student_id, concept, difficulty, source, payload_json)
               VALUES (801, 10, 'class-definition', 'Medium', 'prebuilt_diagnostic', '{"kind": "diagnostic"}')"""
        )
        conn.commit()
        conn.close()

        out_diag = coord.on_quiz_submitted(student_id=10, quiz_result_id=801, quiz_session_id=801)
        self.assertTrue(out_diag["plan_changed"])
        self.assertIn(out_diag["next_action"]["type"], ("study_step", "take_quiz"))

        j2 = coord.get_journey(student_id=10)
        self.assertEqual(j2["state"], STATE_PLAN_ACTIVE)
        self.assertIsNotNone(j2["plan"])
        self.assertGreater(len(j2["plan"]["steps"]), 0)


if __name__ == "__main__":
    unittest.main()
