"""
=============================================================================
EduGen - Quiz Engine & Misconception-First Tests (Phase 4A)
=============================================================================
Comprehensive unit and integration tests with NO network dependencies:
  1. Part 0: EmbeddingCache reuse & query embedder degraded fallback (timeout, signature mismatch)
  2. Part 1.1: normalize_question validation, rejection reasons, invalid misconception handling, shuffling
  3. Part 1.2: Blueprint generation for practice, diagnostic, and reevaluation (counts, qtype mix, mastery)
  4. Part 1.3: prioritize_misconceptions (chosen before -> never offered -> the rest)
  5. Part 1.4: group_slots grouping
  6. Part 2.3: Clarifier < 60% acceptance threshold returns unavailable error
  7. Part 3: api_quiz_start and api_quiz_submit wiring with misconceptions_detected
=============================================================================
"""

import collections
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.db as db
from core.concepts import CONCEPTS
from core.misconceptions import MISCONCEPTIONS, misconceptions_for
from core.quiz_engine import (
    build_blueprint,
    default_difficulty_for_concept,
    group_slots,
    normalize_question,
    prioritize_misconceptions,
)
from rag.embedding_cache import EmbeddingCache
from rag.retriever import Retriever
from rag.vector_store import VectorStore


# ─────────────────────────────────────────────────────────────
# 1. Part 0 Tests: Embedding Cache & Degraded Fallback
# ─────────────────────────────────────────────────────────────
class TestPart0Hardening(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_embedding_cache_reuse(self):
        cache_db = Path(self.temp_dir) / "cache.db"
        cache = EmbeddingCache(db_path=cache_db)
        sig = "fake:embedder:3"

        chunks = ["public class Foo {}", "public class Bar {}", "void test() {}"]
        hashes = [EmbeddingCache.hash_text(c) for c in chunks]

        # Initially empty
        found = cache.get_many(sig, hashes)
        self.assertEqual(len(found), 0)

        # Store two vectors
        cache.put_many(sig, [
            (hashes[0], [0.1, 0.2, 0.3]),
            (hashes[1], [0.4, 0.5, 0.6]),
        ])

        # Verify reuse
        found2 = cache.get_many(sig, hashes)
        self.assertEqual(len(found2), 2)
        self.assertIn(hashes[0], found2)
        self.assertIn(hashes[1], found2)
        self.assertNotIn(hashes[2], found2)

    def test_retriever_degraded_fallback_on_failing_embedder(self):
        index_dir = Path(self.temp_dir) / "test_index"
        store = VectorStore(index_dir)
        fake_chunks = [
            {"id": "c1", "text": "classes group state and behavior", "concept": "class-definition", "collection": "book", "source": "s1"},
            {"id": "c2", "text": "polymorphism allows dynamic method dispatch", "concept": "dynamic-method-dispatch", "collection": "book", "source": "s1"},
        ]
        store.save(fake_chunks, [[1.0, 0.0], [0.0, 1.0]], "fake:embedder:2")

        # Create a fake failing embedder
        class FailingEmbedder:
            def signature(self):
                return "fake:embedder:2"

            def embed_one(self, text):
                raise RuntimeError("Embedder service unreachable")

        retriever = Retriever(index_dir=index_dir, lazy=True)
        retriever.store = store
        retriever._loaded = True
        retriever._embedder = FailingEmbedder()

        res = retriever.retrieve({"concept": "class-definition", "query": "classes state and behavior"})
        self.assertTrue(res["ready"])
        self.assertEqual(res["trace"].get("degraded"), "lexical_only")
        self.assertGreater(len(res["passages"]), 0)

    def test_retriever_degraded_fallback_on_signature_mismatch(self):
        index_dir = Path(self.temp_dir) / "test_index_mismatch"
        store = VectorStore(index_dir)
        fake_chunks = [
            {"id": "c1", "text": "classes and methods in java", "concept": "class-definition", "collection": "book", "source": "s1"},
        ]
        store.save(fake_chunks, [[1.0, 0.0]], "index:signature:v1")

        class MismatchedEmbedder:
            def signature(self):
                return "active:signature:v2"

            def embed_one(self, text):
                raise AssertionError("Should never be called when signatures mismatch!")

        retriever = Retriever(index_dir=index_dir, lazy=True)
        retriever.store = store
        retriever._loaded = True
        retriever._embedder = MismatchedEmbedder()

        res = retriever.retrieve({"concept": "class-definition", "query": "classes and methods"})
        self.assertTrue(res["ready"])
        self.assertEqual(res["trace"].get("degraded"), "lexical_only")


# ─────────────────────────────────────────────────────────────
# 2. Part 1.1 Tests: Normalization & Validation
# ─────────────────────────────────────────────────────────────
class TestNormalization(unittest.TestCase):
    def test_valid_question_normalization(self):
        raw = {
            "question": "What is the primary role of a class definition in Java?",
            "qtype": "concept",
            "options": [
                {"text": "A blueprint for creating objects", "misconception_id": None},
                {"text": "A storage unit that directly holds all instance values", "misconception_id": "class-definition/class-stores-instance-data"},
                {"text": "A compiled binary file executable directly without a JVM", "misconception_id": None},
                {"text": "A package that contains only static methods", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "A class definition serves as a blueprint from which individual object instances are created.",
            "facet": "blueprint instantiation",
        }
        rec, reason = normalize_question(raw, "class-definition", "Easy")
        self.assertIsNone(reason)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec["options"]), 4)
        self.assertEqual(len(rec["option_misconception_ids"]), 4)
        self.assertIn("A blueprint for creating objects", rec["options"])
        # Correct option misconception id must be None
        correct_idx = rec["correct"]
        self.assertIsNone(rec["option_misconception_ids"][correct_idx])
        self.assertEqual(rec["options"][correct_idx], "A blueprint for creating objects")

    def test_invalid_misconception_id_coerced_to_null_and_counted(self):
        raw = {
            "question": "Which statement about classes is accurate?",
            "qtype": "concept",
            "options": [
                {"text": "Correct answer", "misconception_id": None},
                {"text": "Wrong option 1", "misconception_id": "nonexistent-concept/fake-misconception"},
                {"text": "Wrong option 2", "misconception_id": "class-definition/class-stores-instance-data"},
                {"text": "Wrong option 3", "misconception_id": "inheritance-basics/wrong-belief-from-other-concept"},
            ],
            "correct": 0,
            "explanation": "Valid explanation explaining the underlying concept accurately.",
        }
        rec, reason = normalize_question(raw, "class-definition", "Easy")
        self.assertIsNone(reason)
        self.assertEqual(rec["meta"]["invalid_misconceptions"], 2)
        # Ensure only the valid misconception for class-definition is retained
        retained = [m for m in rec["option_misconception_ids"] if m is not None]
        self.assertEqual(retained, ["class-definition/class-stores-instance-data"])

    def test_reject_duplicate_options(self):
        raw = {
            "question": "What is a class?",
            "qtype": "concept",
            "options": [
                {"text": "A blueprint", "misconception_id": None},
                {"text": "A blueprint", "misconception_id": None},
                {"text": "A method", "misconception_id": None},
                {"text": "A field", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Explanation here.",
        }
        rec, reason = normalize_question(raw, "class-definition", "Easy")
        self.assertIsNone(rec)
        self.assertEqual(reason, "duplicate_options")

    def test_reject_explanation_naming_option(self):
        for phrase in [
            "Option B is the correct answer because...",
            "Choice 2 correctly identifies the instance field.",
            "As shown in (A), constructors cannot return values.",
            "B is correct because classes do not allocate instance memory.",
        ]:
            raw = {
                "question": "What is a class?",
                "qtype": "concept",
                "options": ["A", "B", "C", "D"],
                "correct": 0,
                "explanation": phrase,
            }
            rec, reason = normalize_question(raw, "class-definition", "Easy")
            self.assertIsNone(rec, f"Failed to reject phrase: {phrase}")
            self.assertEqual(reason, "explanation_names_option")

    def test_reject_missing_java_fence_for_code_output_and_bug_find(self):
        raw = {
            "question": "What is the output of this code: int x = 5; System.out.println(x);",
            "qtype": "code_output",
            "options": ["5", "0", "null", "Error"],
            "correct": 0,
            "explanation": "Variables print their assigned value.",
        }
        rec, reason = normalize_question(raw, "class-definition", "Medium")
        self.assertIsNone(rec)
        self.assertEqual(reason, "missing_java_fence")

    def test_reject_unbalanced_fences(self):
        raw = {
            "question": "Consider ```java int x = 1; without closing fence",
            "qtype": "concept",
            "options": ["A", "B", "C", "D"],
            "correct": 0,
            "explanation": "Explanation.",
        }
        rec, reason = normalize_question(raw, "class-definition", "Easy")
        self.assertIsNone(rec)
        self.assertEqual(reason, "unbalanced_fences")


# ─────────────────────────────────────────────────────────────
# 3. Part 1.2 Tests: Blueprint Construction
# ─────────────────────────────────────────────────────────────
class TestBlueprint(unittest.TestCase):
    def test_practice_blueprint(self):
        slots = build_blueprint("practice", concepts=["method-overriding"], n=5, difficulty="Medium")
        self.assertEqual(len(slots), 5)
        for s in slots:
            self.assertEqual(s["concept"], "method-overriding")
            self.assertEqual(s["difficulty"], "Medium")
        # Check qtype mix
        qtypes = [s["qtype"] for s in slots]
        self.assertIn("concept", qtypes)
        self.assertIn("code_output", qtypes)
        self.assertIn("bug_find", qtypes)

    def test_easy_practice_is_concept_only(self):
        slots = build_blueprint("practice", concepts=["class-definition"], n=4, difficulty="Easy")
        for s in slots:
            self.assertEqual(s["qtype"], "concept")

    def test_diagnostic_blueprint(self):
        slots = build_blueprint("diagnostic")
        self.assertEqual(len(slots), 12)
        diffs = [s["difficulty"] for s in slots]
        self.assertEqual(diffs.count("Easy"), 6)
        self.assertEqual(diffs.count("Medium"), 6)
        # All Easy slots must be concept only
        for s in slots:
            if s["difficulty"] == "Easy":
                self.assertEqual(s["qtype"], "concept")

    def test_reevaluation_blueprint(self):
        slots = build_blueprint("reevaluation", concepts=["class-definition", "constructor-basics"], difficulty="Medium")
        # 2 concepts * 2 slots = 4 slots (plus 0 retention since no student history)
        self.assertEqual(len(slots), 4)
        c_counts = collections.Counter(s["concept"] for s in slots)
        self.assertEqual(c_counts["class-definition"], 2)
        self.assertEqual(c_counts["constructor-basics"], 2)


# ─────────────────────────────────────────────────────────────
# 4. Part 1.3 & 1.4 Tests: Prioritization & Grouping
# ─────────────────────────────────────────────────────────────
class TestPrioritizationAndGrouping(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.orig_db = db.DB_PATH
        db.DB_PATH = self.temp_db
        os.environ["EDUGEN_DB_PATH"] = self.temp_db
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.orig_db
        os.environ["EDUGEN_DB_PATH"] = self.orig_db
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_prioritize_misconceptions_chose_before_gets_first(self):
        conn = db.get_db()
        conn.execute("INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Test', 't@e.com', 'p')")
        conn.execute("INSERT INTO students (id, name, user_id) VALUES (1, 'Test', 1)")
        conn.execute("INSERT INTO quiz_results (id, student_id, topic, concept, difficulty, score, total_questions) VALUES (1, 1, 'T', 'class-definition', 'Easy', 0, 1)")

        target_m = "class-definition/class-stores-instance-data"
        conn.execute(
            """INSERT INTO question_attempts
               (quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer, misconception_id)
               VALUES (1, 0, '["class-definition"]', 0, 1, 0, ?)""",
            (target_m,),
        )
        conn.commit()
        conn.close()

        prioritized = prioritize_misconceptions(student_id=1, concept="class-definition", k=3)
        self.assertGreater(len(prioritized), 0)
        self.assertEqual(prioritized[0], target_m)

    def test_group_slots(self):
        slots = [
            {"concept": "class-definition", "difficulty": "Easy", "qtype": "concept", "target_misconceptions": ["m1"]},
            {"concept": "class-definition", "difficulty": "Easy", "qtype": "concept", "target_misconceptions": ["m2"]},
            {"concept": "class-definition", "difficulty": "Medium", "qtype": "code_output", "target_misconceptions": ["m1"]},
            {"concept": "inheritance-basics", "difficulty": "Medium", "qtype": "concept", "target_misconceptions": ["m3"]},
        ]
        groups = group_slots(slots)
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(groups[0]["concept"], "class-definition")
        self.assertEqual(groups[0]["difficulty"], "Easy")
        self.assertEqual(set(groups[0]["target_misconceptions"]), {"m1", "m2"})


# ─────────────────────────────────────────────────────────────
# 5. Part 2 & Part 3 Integration Tests (Fake LLM, Submit Wiring)
# ─────────────────────────────────────────────────────────────
class TestClarifierAndSubmitWiring(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.orig_db = db.DB_PATH
        db.DB_PATH = self.temp_db
        os.environ["EDUGEN_DB_PATH"] = self.temp_db
        db.init_db()

        from app import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Seed student
        resp = self.client.post("/api/auth/signup", json={
            "name": "Quiz Student", "email": "quiz_student@example.com", "password": "password123"
        })
        self.assertEqual(resp.status_code, 201)
        self.student_id = resp.get_json()["student_id"]

    def tearDown(self):
        db.DB_PATH = self.orig_db
        os.environ["EDUGEN_DB_PATH"] = self.orig_db
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_clarifier_under_60_percent_returns_unavailable(self):
        clarifier = self.app.extensions["edugen"]["cc"]

        # Mock LLM to return invalid/duplicate options so acceptance < 60%
        def fake_call_llm(sys_prompt, user_prompt):
            return {
                "questions": [
                    {
                        "question": "Q1?",
                        "qtype": "concept",
                        "options": ["Duplicate", "Duplicate", "C", "D"],  # Will fail normalization
                        "correct": 0,
                        "explanation": "Valid",
                    }
                ]
            }

        orig_call = clarifier._call_llm
        clarifier._call_llm = fake_call_llm
        try:
            slots = build_blueprint("practice", concepts=["class-definition"], n=5, difficulty="Easy")
            res = clarifier.generate_quiz_from_blueprint(slots)
            self.assertEqual(res["generated_by"], "unavailable")
            self.assertIn("quality threshold not met", res["error"])
            self.assertIn("build_report", res)
            self.assertLess(res["build_report"]["accepted"], 0.60 * res["build_report"]["requested"])
        finally:
            clarifier._call_llm = orig_call

    def test_quiz_start_and_submit_with_misconceptions_detected(self):
        clarifier = self.app.extensions["edugen"]["cc"]

        # Mock LLM to return valid questions
        def fake_call_llm(sys_prompt, user_prompt):
            return {
                "questions": [
                    {
                        "question": "What happens when an object is instantiated?",
                        "qtype": "concept",
                        "options": [
                            {"text": "Memory is allocated in the heap for instance fields", "misconception_id": None},
                            {"text": "Instance data is stored directly inside the class definition", "misconception_id": "class-definition/class-stores-instance-data"},
                            {"text": "The JVM compiles the file to machine code immediately", "misconception_id": None},
                            {"text": "All static variables are reset to their default values", "misconception_id": None},
                        ],
                        "correct": 0,
                        "explanation": "Instantiating an object dynamically allocates heap storage for its fields.",
                        "facet": "blueprint instantiation",
                    }
                ]
            }

        orig_call = clarifier._call_llm
        clarifier._call_llm = fake_call_llm
        try:
            # 1. Start quiz
            start_resp = self.client.post("/api/quiz/start", json={
                "kind": "practice",
                "concept": "class-definition",
                "difficulty": "Easy",
                "count": 1,
            })
            self.assertEqual(start_resp.status_code, 200)
            start_data = start_resp.get_json()
            session_id = start_data["quiz_session_id"]
            self.assertEqual(len(start_data["questions"]), 1)
            # Browser only gets strings
            for opt in start_data["questions"][0]["options"]:
                self.assertIsInstance(opt, str)

            # 2. Inspect session in database to find wrong option with misconception
            conn = db.get_db()
            sess_row = conn.execute("SELECT payload_json FROM quiz_sessions WHERE id = ?", (session_id,)).fetchone()
            payload = json.loads(sess_row["payload_json"])
            q_internal = payload["questions"][0]
            conn.close()

            correct_idx = q_internal["correct"]
            # Pick the distractor with the misconception
            distractor_idx = -1
            for idx, mid in enumerate(q_internal["option_misconception_ids"]):
                if mid == "class-definition/class-stores-instance-data":
                    distractor_idx = idx
                    break
            self.assertNotEqual(distractor_idx, -1)

            # 3. Submit quiz with wrong answer
            submit_resp = self.client.post("/api/quiz/submit", json={
                "quiz_session_id": session_id,
                "answers": {"0": distractor_idx},
                "timings": {"0": 5000},
                "duration_ms": 5000,
            })
            self.assertEqual(submit_resp.status_code, 200)
            submit_data = submit_resp.get_json()
            self.assertEqual(submit_data["score"], 0)

            # Verify misconceptions_detected in JSON response
            detected = submit_data.get("misconceptions_detected", [])
            self.assertEqual(len(detected), 1)
            self.assertEqual(detected[0]["id"], "class-definition/class-stores-instance-data")
            self.assertEqual(detected[0]["count"], 1)
            self.assertIn("title", detected[0])
            self.assertIn("wrong_belief", detected[0])

            # Verify database persistence in question_attempts
            conn = db.get_db()
            qa_row = conn.execute("SELECT misconception_id FROM question_attempts WHERE quiz_result_id = ?", (submit_data["quiz_result_id"],)).fetchone()
            self.assertEqual(qa_row["misconception_id"], "class-definition/class-stores-instance-data")

            # Verify persistence in student_question_history
            sqh_row = conn.execute("SELECT misconception_id FROM student_question_history WHERE student_id = ?", (self.student_id,)).fetchone()
            self.assertEqual(sqh_row["misconception_id"], "class-definition/class-stores-instance-data")
            conn.close()

        finally:
            clarifier._call_llm = orig_call


if __name__ == "__main__":
    unittest.main()
