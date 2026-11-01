"""
=============================================================================
EduGen - Phase 4C Unit & Integration Test Suite (test_pool.py)
=============================================================================
Hermetic, offline test suite for Phase 4C:
  1. Pool selection (unseen only, exact difficulty, target-coverage preference,
     within-quiz dedupe, unfilled slots returned).
  2. Token budget switching, 'both exhausted' paths, 429 TPD / long retry
     exhaustion without sleeping.
  3. reasoning_effort HTTP 400 fallback and remembered unsupported status.
  4. Explanation positional wording gate fixes.
  5. Verifier difficulty check (diff >= 2 rejected, diff <= 1 accepted).
  6. Migration 4 executed on a copy of data/edugen.db verifying schema additions
     and preserving old row counts.
=============================================================================
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.concept_clarifier_agent import ConceptClarifierAgent
from core.db import get_db, init_db
from core.db_repo import record_generated_questions, record_llm_call
from core.migrations import run_migrations
from core.quiz_engine import normalize_question, select_from_pool, serialize_embedding
from core.token_budget import (
    are_all_models_exhausted,
    check_429_exhaustion,
    get_today_token_usage,
    is_model_exhausted,
    is_reasoning_supported,
    mark_model_exhausted,
    mark_reasoning_unsupported,
    reset_budget_state,
    select_active_model,
)


class TestPoolSelection(unittest.TestCase):
    def setUp(self):
        reset_budget_state()
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_pool.db")
        import core.db
        core.db.DB_PATH = self.db_path
        os.environ["EDUGEN_DB_PATH"] = self.db_path
        init_db(self.db_path)
        conn = get_db(self.db_path)
        conn.execute("INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Test User', 'student@edugen.edu', 'hash')")
        conn.execute("INSERT INTO students (id, user_id, name) VALUES (1, 1, 'Test Student')")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        reset_budget_state()
        import core.db
        core.db.DB_PATH = str(BASE_DIR / "data" / "edugen.db")
        os.environ.pop("EDUGEN_DB_PATH", None)

    def _insert_pool_question(self, qid, concept, difficulty, text, qtype="concept", mids=None, emb=None, times_served=0):
        conn = get_db()
        thash = f"hash_{qid}_{text}"
        options_json = json.dumps(["A", "B", "C", "D"])
        tags_json = json.dumps({
            "tags": [concept],
            "option_misconception_ids": mids or [None, None, None, None],
            "qtype": qtype,
        })
        emb_blob = serialize_embedding(emb) if emb else None
        conn.execute("""
            INSERT INTO questions (
                id, concept, difficulty, qtype, question_text, options_json,
                correct_index, explanation, tags_json, source, model, verified,
                text_hash, embedding, origin, pool_status, times_served, times_correct
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 'Explanation text', ?, 'test', 'mock', 1, ?, ?, 'generated', 'active', ?, 0)
        """, (qid, concept, difficulty, qtype, text, options_json, tags_json, thash, emb_blob, times_served))
        conn.commit()
        conn.close()

    def test_unseen_only(self):
        """Student has seen question 101; pool selection chooses unseen question 102."""
        self._insert_pool_question(101, "class-definition", "Easy", "What is class 1?")
        self._insert_pool_question(102, "class-definition", "Easy", "What is class 2?")

        conn = get_db()
        conn.execute("INSERT INTO student_question_history (student_id, question_id, was_correct, chosen_index, time_taken_ms) VALUES (1, 101, 1, 0, 1000)")
        conn.commit()
        conn.close()

        slots = [{"concept": "class-definition", "difficulty": "Easy", "qtype": "concept"}]
        served, unfilled = select_from_pool(slots, student_id=1)

        self.assertEqual(len(served), 1)
        self.assertEqual(len(unfilled), 0)
        self.assertEqual(served[0]["question_id"], 102)

    def test_exact_difficulty(self):
        """Slot requests Medium; Easy questions in pool are not served."""
        self._insert_pool_question(201, "class-definition", "Easy", "Easy class Q")
        slots = [{"concept": "class-definition", "difficulty": "Medium", "qtype": "concept"}]
        served, unfilled = select_from_pool(slots, student_id=1)

        self.assertEqual(len(served), 0)
        self.assertEqual(len(unfilled), 1)

    def test_target_coverage_preference(self):
        """Candidate covering slot target misconceptions is preferred over one that covers 0."""
        slot_targets = ["class-definition/class-is-object", "class-definition/new-not-needed"]
        # Question 301 covers 0 targets
        self._insert_pool_question(301, "class-definition", "Easy", "Class Q1", mids=[None, None, None, None])
        # Question 302 covers 1 target
        self._insert_pool_question(302, "class-definition", "Easy", "Class Q2", mids=["class-definition/class-is-object", None, None, None])

        slots = [{"concept": "class-definition", "difficulty": "Easy", "target_misconceptions": slot_targets, "qtype": "concept"}]
        served, unfilled = select_from_pool(slots, student_id=1)

        self.assertEqual(len(served), 1)
        self.assertEqual(served[0]["question_id"], 302)

    def test_within_quiz_dedupe(self):
        """Near duplicate questions (cosine >= 0.88) are rejected within the same quiz."""
        vec = [0.1] * 128
        # Two questions with identical embeddings
        self._insert_pool_question(401, "class-definition", "Easy", "Class Q A", emb=vec)
        self._insert_pool_question(402, "class-definition", "Easy", "Class Q B", emb=vec)

        slots = [
            {"concept": "class-definition", "difficulty": "Easy", "qtype": "concept"},
            {"concept": "class-definition", "difficulty": "Easy", "qtype": "concept"},
        ]
        served, unfilled = select_from_pool(slots, student_id=1)

        # 401 served, 402 rejected as dup of 401, second slot left unfilled
        self.assertEqual(len(served), 1)
        self.assertEqual(len(unfilled), 1)

    def test_unfilled_slots_returned(self):
        """When pool runs out of matching questions, unfilled slots are returned."""
        self._insert_pool_question(501, "inheritance-basics", "Easy", "Inheritance Q1")

        slots = [
            {"concept": "inheritance-basics", "difficulty": "Easy", "qtype": "concept"},
            {"concept": "inheritance-basics", "difficulty": "Easy", "qtype": "concept"},
        ]
        served, unfilled = select_from_pool(slots, student_id=1)

        self.assertEqual(len(served), 1)
        self.assertEqual(len(unfilled), 1)
        self.assertEqual(unfilled[0]["concept"], "inheritance-basics")


class TestTokenBudget(unittest.TestCase):
    def setUp(self):
        reset_budget_state()
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_budget.db")
        import core.db
        core.db.DB_PATH = self.db_path
        os.environ["EDUGEN_DB_PATH"] = self.db_path
        init_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        reset_budget_state()
        import core.db
        core.db.DB_PATH = str(BASE_DIR / "data" / "edugen.db")
        os.environ.pop("EDUGEN_DB_PATH", None)

    def test_budget_switching_primary_to_fallback(self):
        """When primary model exceeds budget, select_active_model switches to fallback."""
        primary = "primary-model"
        fallback = "fallback-model"

        # Record calls exceeding 160,000 for primary
        record_llm_call(None, "clarifier", "generate", primary, 500, True, prompt_tokens=100000, completion_tokens=70000)

        model, status = select_active_model(primary, fallback)
        self.assertEqual(model, fallback)
        self.assertEqual(status, "fallback")

    def test_both_models_exhausted_path(self):
        """When both primary and fallback exceed budget, select_active_model returns None, exhausted."""
        primary = "primary-model"
        fallback = "fallback-model"

        record_llm_call(None, "clarifier", "generate", primary, 500, True, prompt_tokens=100000, completion_tokens=70000)
        record_llm_call(None, "clarifier", "generate", fallback, 500, True, prompt_tokens=100000, completion_tokens=70000)

        model, status = select_active_model(primary, fallback)
        self.assertIsNone(model)
        self.assertEqual(status, "exhausted")
        self.assertTrue(are_all_models_exhausted(primary, fallback))

    def test_tpd_429_marks_exhausted_without_sleep(self):
        """A 429 response mentioning tokens per day marks the model exhausted immediately."""
        model = "test-provider-model"
        err_msg = "Error code: 429 - Rate limit reached on tokens per day (TPD): Limit 200000, Used 199000."

        exhausted = check_429_exhaustion(model, err_msg)
        self.assertTrue(exhausted)
        self.assertTrue(is_model_exhausted(model))

    def test_retry_after_over_60_marks_exhausted(self):
        """A 429 response with Retry-After > 60 seconds marks the model exhausted."""
        model = "test-provider-model-2"
        exhausted = check_429_exhaustion(model, "Too many requests", retry_after=120.0)
        self.assertTrue(exhausted)
        self.assertTrue(is_model_exhausted(model))


class TestReasoningEffort(unittest.TestCase):
    def setUp(self):
        reset_budget_state()

    def tearDown(self):
        reset_budget_state()

    def test_reasoning_effort_400_fallback_is_remembered(self):
        """HTTP 400 with reasoning_effort retries without it and remembers model as unsupported."""
        agent = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        agent.log = None
        agent.client = MagicMock()

        # First call with reasoning_effort fails with 400
        mock_resp_success = MagicMock()
        mock_resp_success.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
        mock_resp_success.usage = MagicMock(prompt_tokens=10, completion_tokens=10, total_tokens=20)

        # Side effect: first call raises BadRequestError (400), second call succeeds
        agent.client.chat.completions.create.side_effect = [
            Exception("HTTP 400: Unknown parameter 'reasoning_effort'"),
            mock_resp_success,
        ]

        raw, exc = agent._create_completion(
            "mock-model",
            [{"role": "user", "content": "hi"}],
            0.6,
            1000,
            json_mode=False,
            reasoning_effort="low",
        )

        self.assertIsNone(exc)
        self.assertEqual(raw, '{"ok": true}')
        # Model should now be remembered as unsupported
        self.assertFalse(is_reasoning_supported("mock-model"))

        # Subsequent call will not pass reasoning_effort
        agent.client.chat.completions.create.side_effect = [mock_resp_success]
        agent._create_completion(
            "mock-model",
            [{"role": "user", "content": "hi"}],
            0.6,
            1000,
            json_mode=False,
            reasoning_effort="low",
        )
        last_kwargs = agent.client.chat.completions.create.call_args[1]
        self.assertNotIn("reasoning_effort", last_kwargs)


class TestGateFixes(unittest.TestCase):
    def test_explanation_names_option_positional_wording(self):
        """Positional phrases trip explanation_names_option gate."""
        bad_phrases = [
            "the first option is clearly wrong.",
            "the second option accurately describes encapsulation.",
            "the third option fails because of syntax.",
            "the fourth option is the only valid answer.",
            "the last option correctly compiles.",
            "Therefore option (a) is true.",
            "The former causes a compiler error while the latter succeeds.",
            "The one above is immutable.",
            "The one below overrides the method.",
        ]

        for phrase in bad_phrases:
            raw = {
                "question": "Which statement is true?",
                "qtype": "concept",
                "options": ["A", "B", "C", "D"],
                "correct": 0,
                "explanation": f"Explanation: {phrase}",
            }
            rec, reason = normalize_question(raw, "class-definition", "Easy")
            self.assertIsNone(rec, f"Expected rejection for: '{phrase}'")
            self.assertEqual(reason, "explanation_names_option", f"Failed on: '{phrase}'")

    def test_valid_explanation_passes(self):
        """Conceptual explanation without positional or letter labels passes."""
        raw = {
            "question": "Which statement is true?",
            "qtype": "concept",
            "options": ["A", "B", "C", "D"],
            "correct": 0,
            "explanation": "Instance variables are initialized before constructor bodies execute.",
            "option_misconceptions": [None, "class-definition/class-stores-instance-data", "class-definition/multiple-public-classes", None],
        }
        rec, reason = normalize_question(raw, "class-definition", "Easy")
        self.assertIsNotNone(rec)
        self.assertIsNone(reason)


class TestVerifierDifficultyCheck(unittest.TestCase):
    def test_difficulty_check_rejects_two_level_difference(self):
        """Verifier estimate differing by 2 levels (Easy vs Hard) is rejected."""
        agent = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        agent.log = None
        agent.client = MagicMock()
        agent.api_key = "mock-key"
        agent.verifier_model = "mock-verifier"
        agent.verifier_fallback_model = "mock-fallback"
        agent.model = "mock-gen"

        # Mock question labeled 'Easy'
        questions = [{
            "question": "What is an object?",
            "options": ["A", "B", "C", "D"],
            "correct": 1,
            "difficulty": "Easy",
            "concept": "class-definition",
            "option_misconception_ids": [None, None, None, None],
        }]

        # Verifier returns answer=1, not ambiguous, but difficulty_estimate='Hard' (diff = 2)
        v_response = {
            "verifications": [{
                "index": 0,
                "answer": 1,
                "ambiguous": False,
                "labels": [None, None, None, None],
                "difficulty_estimate": "Hard",
                "note": "Advanced concept",
            }]
        }
        agent._call_llm = MagicMock(return_value=v_response)

        accepted, rejected, tags_rem, warning, v_model = agent.verify_group(questions, "class-definition")
        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0][1], "verifier_difficulty_mismatch")

    def test_difficulty_check_accepts_one_level_difference(self):
        """Verifier estimate differing by 1 level (Easy vs Medium) is accepted."""
        agent = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        agent.log = None
        agent.client = MagicMock()
        agent.api_key = "mock-key"
        agent.verifier_model = "mock-verifier"
        agent.verifier_fallback_model = "mock-fallback"
        agent.model = "mock-gen"

        questions = [{
            "question": "What is an object?",
            "options": ["A", "B", "C", "D"],
            "correct": 1,
            "difficulty": "Easy",
            "concept": "class-definition",
            "option_misconception_ids": [None, None, None, None],
        }]

        v_response = {
            "verifications": [{
                "index": 0,
                "answer": 1,
                "ambiguous": False,
                "labels": [None, None, None, None],
                "difficulty_estimate": "Medium",
                "note": "Moderate trap",
            }]
        }
        agent._call_llm = MagicMock(return_value=v_response)

        accepted, rejected, tags_rem, warning, v_model = agent.verify_group(questions, "class-definition")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(accepted[0]["difficulty_verified"], 1)


class TestMigration4OnDbCopy(unittest.TestCase):
    def test_migration_4_on_db_copy(self):
        """Execute Migration 4 on a copy of data/edugen.db and verify additions with preserved row counts."""
        real_db = BASE_DIR / "data" / "edugen.db"
        if not real_db.exists():
            self.skipTest("data/edugen.db does not exist")

        temp_dir = tempfile.mkdtemp()
        copy_db = Path(temp_dir) / "edugen_copy.db"
        shutil.copy2(real_db, copy_db)

        # Count existing rows before migration
        conn_pre = sqlite3.connect(copy_db)
        pre_counts = {}
        for tbl in ["users", "students", "quiz_results", "questions", "llm_calls"]:
            try:
                pre_counts[tbl] = conn_pre.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            except Exception:
                pass
        conn_pre.close()

        # Run migration 4 on the copy
        def conn_factory(path):
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c

        applied = run_migrations(str(copy_db), conn_factory)

        # Verify new columns on questions table
        conn_post = sqlite3.connect(copy_db)
        q_cols = {row[1] for row in conn_post.execute("PRAGMA table_info(questions)").fetchall()}
        self.assertIn("origin", q_cols)
        self.assertIn("pool_status", q_cols)
        self.assertIn("difficulty_verified", q_cols)
        self.assertIn("verifier_labels_json", q_cols)
        self.assertIn("verified", q_cols)

        # Verify total_tokens on llm_calls
        llm_cols = {row[1] for row in conn_post.execute("PRAGMA table_info(llm_calls)").fetchall()}
        self.assertIn("total_tokens", llm_cols)

        # Verify index idx_questions_pool exists
        idx_rows = conn_post.execute("PRAGMA index_list(questions)").fetchall()
        idx_names = {r[1] for r in idx_rows}
        self.assertIn("idx_questions_pool", idx_names)

        # Verify old row counts unchanged
        for tbl, count in pre_counts.items():
            post_count = conn_post.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            self.assertEqual(count, post_count, f"Row count for '{tbl}' changed after migration!")

        conn_post.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
