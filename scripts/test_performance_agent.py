"""
=============================================================================
EduGen - Phase 5 Performance Analysis Agent Test Suite
=============================================================================
Hermetic, offline test suite for:
  1. BKT monotonicity (correct answers raise P(known), wrong lower it;
     correct Hard answer raises more than correct Easy answer).
  2. Misconception lifecycle transitions (active, suspected, resolved)
     with hand-built attempt sequences.
  3. Severity calculation and descending ordering.
  4. Facet map calculation (offered, chosen, error_rate, weak flag).
  5. Skill gap detection by question type (concept vs code_output / bug_find).
  6. Untagged error tracking per concept.
  7. Backward compatibility: legacy keys and shapes preserved, get_concept_performance.
  8. Idempotent persistence into student_misconceptions and concept_mastery.
  9. Empty student analysis (0 attempts).
  10. Legacy attempts compatibility (attempts lacking migration 5 columns).
=============================================================================
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.performance_analysis_agent import (
    PerformanceAnalysisAgent,
    get_concept_performance,
)
from core.db import get_db, init_db
from core.pa_model import (
    BKT_P_INIT,
    compute_concept_bkt,
    compute_facet_map,
    compute_misconception_stats,
    compute_skill_profile,
    compute_untagged_errors,
    get_confidence,
    update_bkt,
)


class TestBKTMonotonicity(unittest.TestCase):
    def test_correct_raises_pknown(self):
        """A correct answer strictly increases P(known) from prior."""
        p_next = update_bkt(BKT_P_INIT, True, "Medium")
        self.assertGreater(p_next, BKT_P_INIT)

    def test_wrong_lowers_pknown(self):
        """An incorrect answer strictly decreases P(known) from prior."""
        p_next = update_bkt(BKT_P_INIT, False, "Medium")
        self.assertLess(p_next, BKT_P_INIT)

    def test_hard_correct_raises_more_than_easy_correct(self):
        """A correct answer on a Hard question yields higher mastery than on an Easy question."""
        p_easy = update_bkt(BKT_P_INIT, True, "Easy")
        p_hard = update_bkt(BKT_P_INIT, True, "Hard")
        self.assertGreater(p_hard, p_easy)

    def test_hard_wrong_penalizes_less_than_easy_wrong(self):
        """Failing a Hard question leaves P(known) higher than failing an Easy question."""
        p_easy_fail = update_bkt(BKT_P_INIT, False, "Easy")
        p_hard_fail = update_bkt(BKT_P_INIT, False, "Hard")
        self.assertGreater(p_hard_fail, p_easy_fail)

    def test_confidence_tiers(self):
        """Confidence tiers correctly reflect attempt count thresholds."""
        self.assertEqual(get_confidence(0), "low")
        self.assertEqual(get_confidence(2), "low")
        self.assertEqual(get_confidence(3), "medium")
        self.assertEqual(get_confidence(5), "medium")
        self.assertEqual(get_confidence(6), "high")
        self.assertEqual(get_confidence(20), "high")

    def test_mastery_display_clamp(self):
        """7 consecutive correct answers reach p_known > 0.99 but displayed mastery is clamped to 98.0% (not 100%)."""
        from core.pa_model import clamp_mastery
        events = [{"is_correct": True, "difficulty": "Medium"} for _ in range(7)]
        p_known, _ = compute_concept_bkt(events)
        self.assertGreater(p_known, 0.99)
        self.assertEqual(clamp_mastery(100.0 * p_known), 98.0)

        # Lower bound clamp
        events_fail = [{"is_correct": False, "difficulty": "Easy"} for _ in range(7)]
        p_fail, _ = compute_concept_bkt(events_fail)
        self.assertLess(p_fail, 0.05)
        self.assertEqual(clamp_mastery(100.0 * p_fail), 2.0)


class TestMisconceptionLifecycle(unittest.TestCase):
    def setUp(self):
        self.mid = "method-overriding/static-methods-override"

    def test_suspected_transition(self):
        """Chosen once with avoided_streak < 2 -> suspected."""
        attempts = [
            {
                "timestamp": "2026-11-01 10:00:00",
                "concept": "method-overriding",
                "offered_misconceptions": [self.mid],
                "misconception_id": self.mid,
                "is_correct": False,
            }
        ]
        res = compute_misconception_stats(attempts)
        self.assertEqual(len(res["suspected"]), 1)
        self.assertEqual(len(res["active"]), 0)
        self.assertEqual(len(res["resolved"]), 0)
        item = res["suspected"][0]
        self.assertEqual(item["status"], "suspected")
        self.assertEqual(item["chosen"], 1)
        self.assertEqual(item["avoided_streak"], 0)

    def test_active_transition(self):
        """Chosen >= 2 times with avoided_streak < 2 -> active."""
        attempts = [
            {
                "timestamp": "2026-11-01 10:00:00",
                "concept": "method-overriding",
                "offered_misconceptions": [self.mid],
                "misconception_id": self.mid,
                "is_correct": False,
            },
            {
                "timestamp": "2026-11-01 10:05:00",
                "concept": "method-overriding",
                "offered_misconceptions": [self.mid],
                "misconception_id": self.mid,
                "is_correct": False,
            },
        ]
        res = compute_misconception_stats(attempts)
        self.assertEqual(len(res["active"]), 1)
        self.assertEqual(len(res["suspected"]), 0)
        self.assertEqual(len(res["resolved"]), 0)
        item = res["active"][0]
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["chosen"], 2)
        self.assertEqual(item["avoided_streak"], 0)

    def test_resolved_transition(self):
        """Chosen >= 1 time, followed by 2 consecutive avoidances -> resolved."""
        attempts = [
            {
                "timestamp": "2026-11-01 10:00:00",
                "concept": "method-overriding",
                "offered_misconceptions": [self.mid],
                "misconception_id": self.mid,
                "is_correct": False,
            },
            {
                "timestamp": "2026-11-01 10:05:00",
                "concept": "method-overriding",
                "offered_misconceptions": [self.mid],
                "misconception_id": None,
                "is_correct": True,
            },
            {
                "timestamp": "2026-11-01 10:10:00",
                "concept": "method-overriding",
                "offered_misconceptions": [self.mid],
                "misconception_id": None,
                "is_correct": True,
            },
        ]
        res = compute_misconception_stats(attempts)
        self.assertEqual(len(res["resolved"]), 1)
        self.assertEqual(len(res["active"]), 0)
        self.assertEqual(len(res["suspected"]), 0)
        item = res["resolved"][0]
        self.assertEqual(item["status"], "resolved")
        self.assertEqual(item["chosen"], 1)
        self.assertEqual(item["offered"], 3)
        self.assertEqual(item["avoided_streak"], 2)

    def test_severity_ordering(self):
        """Misconceptions in active list are ordered descending by severity."""
        m1 = "method-overriding/static-methods-override"
        m2 = "method-overriding/can-reduce-visibility"

        # m1 chosen 3 times, avoided 0 times (severity = 3 * 0.9^0 = 3.0)
        # m2 chosen 2 times, avoided 0 times (severity = 2 * 0.9^0 = 2.0)
        attempts = [
            {"concept": "method-overriding", "offered_misconceptions": [m1], "misconception_id": m1, "is_correct": False},
            {"concept": "method-overriding", "offered_misconceptions": [m1], "misconception_id": m1, "is_correct": False},
            {"concept": "method-overriding", "offered_misconceptions": [m1], "misconception_id": m1, "is_correct": False},
            {"concept": "method-overriding", "offered_misconceptions": [m2], "misconception_id": m2, "is_correct": False},
            {"concept": "method-overriding", "offered_misconceptions": [m2], "misconception_id": m2, "is_correct": False},
        ]
        res = compute_misconception_stats(attempts)
        active = res["active"]
        self.assertEqual(len(active), 2)
        self.assertEqual(active[0]["misconception_id"], m1)
        self.assertEqual(active[1]["misconception_id"], m2)
        self.assertGreater(active[0]["severity"], active[1]["severity"])


class TestFacetAndSkillProfiling(unittest.TestCase):
    def test_facet_map_weak_detection(self):
        """Facet map marks weak when chosen >= 2 and error_rate >= 0.5."""
        attempts = [
            {"concept": "method-overriding", "facet": "visibility", "is_correct": False},
            {"concept": "method-overriding", "facet": "visibility", "is_correct": False},
            {"concept": "method-overriding", "facet": "visibility", "is_correct": True},
            {"concept": "method-overriding", "facet": "final", "is_correct": True},
            {"concept": "method-overriding", "facet": "final", "is_correct": False},
        ]
        fmap = compute_facet_map(attempts)
        vis = fmap["method-overriding"]["visibility"]
        self.assertEqual(vis["offered"], 3)
        self.assertEqual(vis["chosen"], 2)
        self.assertEqual(vis["error_rate"], 0.67)
        self.assertTrue(vis["weak"])

        fin = fmap["method-overriding"]["final"]
        self.assertEqual(fin["offered"], 2)
        self.assertEqual(fin["chosen"], 1)
        self.assertFalse(fin["weak"])

    def test_skill_gap_detection(self):
        """Detects gap when a qtype is >= 25 points below another with >= 4 attempts each."""
        attempts = []
        # Concept: 6 attempts, 6 correct (100.0%)
        for _ in range(6):
            attempts.append({"concept": "class-definition", "qtype": "concept", "is_correct": True})
        # Code output: 6 attempts, 2 correct (33.3%)
        for _ in range(2):
            attempts.append({"concept": "class-definition", "qtype": "code_output", "is_correct": True})
        for _ in range(4):
            attempts.append({"concept": "class-definition", "qtype": "code_output", "is_correct": False})

        prof = compute_skill_profile(attempts)
        self.assertIn("concept", prof["overall"])
        self.assertIn("code_output", prof["overall"])
        self.assertEqual(prof["overall"]["concept"]["accuracy"], 100.0)
        self.assertEqual(prof["overall"]["code_output"]["accuracy"], 33.3)
        self.assertGreaterEqual(len(prof["skill_gaps"]), 1)
        self.assertTrue(any("code tracing" in g.lower() for g in prof["skill_gaps"]))

    def test_untagged_errors(self):
        """Untagged wrong answers increment untagged_errors per concept."""
        attempts = [
            {"concept": "class-definition", "is_correct": False, "misconception_id": None},
            {"concept": "class-definition", "is_correct": False, "misconception_id": None},
            {"concept": "class-definition", "is_correct": True, "misconception_id": None},
        ]
        untagged = compute_untagged_errors(attempts)
        self.assertEqual(untagged.get("class-definition"), 2)


class TestFullAgentWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_pa.db")
        os.environ["EDUGEN_DB_PATH"] = self.db_path
        init_db(self.db_path)
        self.agent = PerformanceAnalysisAgent()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.environ.pop("EDUGEN_DB_PATH", None)

    def _seed_student(self, sid=1):
        conn = get_db(self.db_path)
        conn.execute("INSERT OR IGNORE INTO users (id, name, email, password_hash) VALUES (?, 'Test', 't@e.com', 'h')", (sid,))
        conn.execute("INSERT OR IGNORE INTO students (id, user_id, name) VALUES (?, ?, 'Test')", (sid, sid))
        conn.commit()
        conn.close()

    def test_empty_student_report(self):
        """Empty student returns all legacy and new keys safely without exception."""
        self._seed_student(99)
        report = self.agent.analyze_student(99, db_path=self.db_path)
        self.assertEqual(report["total_quizzes_taken"], 0)
        self.assertEqual(report["total_questions_attempted"], 0)
        self.assertIn("weak_topics", report)
        self.assertIn("moderate_topics", report)
        self.assertIn("strong_topics", report)
        self.assertIn("recommendation_input", report)
        self.assertIn("misconceptions", report)
        self.assertIn("facet_map", report)
        self.assertIn("skill_profile", report)
        self.assertEqual(report["misconceptions"]["active"], [])

    def test_legacy_keys_and_shapes_present(self):
        """Report contains all expected FYP-1 and FYP-2 keys and shapes alongside Phase 5 keys."""
        self._seed_student(1)
        conn = get_db(self.db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source) "
            "VALUES (1, 1, 'class-definition', 'Classes', 'Medium', 2, 4, 1, ?, 'test')",
            (now,),
        )
        for i in range(4):
            is_c = 1 if i < 2 else 0
            conn.execute(
                """INSERT INTO question_attempts (
                    quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                    chosen_option_text, misconception_id, offered_misconceptions, qtype, facet, difficulty
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    1, i, json.dumps(["class-definition"]), is_c, 0 if is_c else 1, 0,
                    "Option A", "class-definition/class-stores-instance-data" if not is_c else None,
                    json.dumps(["class-definition/class-stores-instance-data"]),
                    "concept", "definition", "Medium",
                ),
            )
        conn.commit()
        conn.close()

        report = self.agent.analyze_student(1, db_path=self.db_path)

        # Legacy root keys
        legacy_root_keys = [
            "student_id", "generated_at", "overall_performance", "total_quizzes_taken",
            "total_questions_attempted", "total_questions_correct", "weak_topics",
            "moderate_topics", "strong_topics", "insufficient_data", "root_causes",
            "due_for_review", "module_breakdown", "concept_stats", "recommendation_input",
        ]
        for k in legacy_root_keys:
            self.assertIn(k, report)

        # New Phase 5 root keys
        self.assertIn("misconceptions", report)
        self.assertIn("facet_map", report)
        self.assertIn("skill_profile", report)

        # Legacy & new concept_stats keys
        stat = report["concept_stats"]["class-definition"]
        for k in ["concept_tag", "topic", "title", "module", "attempts", "correct", "accuracy", "mastery", "trend"]:
            self.assertIn(k, stat)
        for k in ["p_known", "ewma_accuracy", "confidence", "facets", "untagged_errors", "active_misconceptions"]:
            self.assertIn(k, stat)

        # Recommendation input keys
        rec_in = report["recommendation_input"]
        for k in ["primary_weak_topic", "weak_topic_count", "overall_performance", "root_causes", "due_for_review"]:
            self.assertIn(k, rec_in)
        for k in ["active_misconceptions", "weak_facets", "skill_gaps"]:
            self.assertIn(k, rec_in)

        # FYP-1 get_concept_performance compatibility
        perf = get_concept_performance(1, db_path=self.db_path)
        self.assertIn("class-definition", perf)
        self.assertIn("accuracy", perf["class-definition"])
        self.assertIn("mastery", perf["class-definition"])

    def test_idempotent_persistence(self):
        """Running analyze_student twice updates rather than duplicates rows in DB."""
        self._seed_student(2)
        conn = get_db(self.db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source) "
            "VALUES (10, 2, 'static-members', 'Classes', 'Medium', 0, 2, 1, ?, 'test')",
            (now,),
        )
        mid = "static-members/static-access-via-instance"
        for i in range(2):
            conn.execute(
                """INSERT INTO question_attempts (
                    quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                    misconception_id, offered_misconceptions, qtype, facet, difficulty
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (10, i, json.dumps(["static-members"]), 0, 1, 0, mid, json.dumps([mid]), "concept", "static", "Medium"),
            )
        conn.commit()
        conn.close()

        # Run 1
        r1 = self.agent.analyze_student(2, db_path=self.db_path)
        # Run 2
        r2 = self.agent.analyze_student(2, db_path=self.db_path)

        conn = get_db(self.db_path)
        sm_count = conn.execute("SELECT COUNT(*) FROM student_misconceptions WHERE student_id = 2").fetchone()[0]
        cm_count = conn.execute("SELECT COUNT(*) FROM concept_mastery WHERE student_id = 2").fetchone()[0]
        conn.close()

        self.assertEqual(sm_count, 1)
        self.assertEqual(cm_count, 1)

    def test_legacy_attempts_without_columns(self):
        """Old attempt rows with NULLs for migration 5 columns are analysed cleanly."""
        self._seed_student(3)
        conn = get_db(self.db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO quiz_results (id, student_id, concept, topic, difficulty, score, total_questions, attempt_number, timestamp, source) "
            "VALUES (20, 3, 'inheritance-basics', 'Inheritance', 'Easy', 1, 2, 1, ?, 'test')",
            (now,),
        )
        conn.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                time_taken_ms, question_text, chosen_option_text, misconception_id,
                offered_misconceptions, qtype, facet, difficulty
            ) VALUES (20, 0, ?, 1, 0, 0, 4000, 'Q1', 'Opt A', NULL, NULL, NULL, NULL, NULL)""",
            (json.dumps(["inheritance-basics"]),),
        )
        conn.execute(
            """INSERT INTO question_attempts (
                quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer,
                time_taken_ms, question_text, chosen_option_text, misconception_id,
                offered_misconceptions, qtype, facet, difficulty
            ) VALUES (20, 1, ?, 0, 1, 0, 8000, 'Q2', 'Opt B', NULL, NULL, NULL, NULL, NULL)""",
            (json.dumps(["inheritance-basics"]),),
        )
        conn.commit()
        conn.close()

        report = self.agent.analyze_student(3, db_path=self.db_path)
        self.assertIn("inheritance-basics", report["concept_stats"])
        stat = report["concept_stats"]["inheritance-basics"]
        self.assertEqual(stat["attempts"], 2)
        self.assertEqual(stat["correct"], 1)
        self.assertEqual(stat["untagged_errors"], 1)


if __name__ == "__main__":
    unittest.main()
