"""
=============================================================================
EduGen - Phase 4B Quiz Quality Gates Unit Tests
=============================================================================
Hermetic, offline test suite for Phase 4B:
  - Deterministic gates in normalize_question (length-ratio, null tags count)
  - Independent verifier (rejection of wrong answers and ambiguous questions,
    tag alignment consensus)
  - Java check compilation & execution decisions (with fake runner)
  - Novelty / deduplication (same quiz, student history, bank copy, lexical)
  - HTTP 429 rate limit retry with Retry-After
  - Diagnostic set selection avoiding seen sets
=============================================================================
"""

import collections
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.concept_clarifier_agent import ConceptClarifierAgent
from app import create_app
from core.db import get_db, init_db
from core.db_repo import (
    compute_question_hash,
    record_generated_questions,
    record_submission_history,
)
from core.java_check import JavaChecker, prepare_java_source
from core.quiz_engine import (
    check_question_novelty,
    cosine_similarity,
    normalize_question,
    token_jaccard,
)


class TestDeterministicGates(unittest.TestCase):
    """Test 2: Deterministic Gates in normalize_question."""

    def test_length_ratio_gate_rejects_long_correct_option(self):
        # Correct option is 50 chars, longest wrong is 20 chars (50 > 1.5 * 20 = 30)
        raw = {
            "question": "What is an abstract class in Java?",
            "qtype": "concept",
            "options": [
                {
                    "text": "This is an extremely detailed and much longer explanation of an abstract class",
                    "misconception_id": None,
                },
                {"text": "A class with methods", "misconception_id": "abstract-classes/instantiating-abstract-class"},
                {"text": "A final class", "misconception_id": "abstract-classes/all-methods-must-be-abstract"},
                {"text": "An interface only", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Abstract classes cannot be instantiated directly.",
        }
        rec, reason = normalize_question(raw, "abstract-classes", "Easy")
        self.assertIsNone(rec)
        self.assertEqual(reason, "correct_option_too_long")

    def test_length_ratio_gate_accepts_balanced_options(self):
        raw = {
            "question": "What is an abstract class in Java?",
            "qtype": "concept",
            "options": [
                {"text": "A class that cannot be directly instantiated", "misconception_id": None},
                {"text": "A class that can never have any concrete methods", "misconception_id": "abstract-classes/cannot-have-concrete-methods"},
                {"text": "A class that must always contain abstract methods", "misconception_id": "abstract-classes/must-have-abstract-methods"},
                {"text": "A class that acts exactly like a pure interface", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Abstract classes serve as blueprints and cannot be instantiated.",
        }
        rec, reason = normalize_question(raw, "abstract-classes", "Easy")
        self.assertIsNotNone(rec)
        self.assertIsNone(reason)

    def test_null_tag_gate_rejects_more_than_two_null_misconceptions(self):
        # 3 wrong options all have null misconception IDs
        raw = {
            "question": "What does polymorphism achieve?",
            "qtype": "concept",
            "options": [
                {"text": "Dynamic method dispatch", "misconception_id": None},
                {"text": "Faster compile speed", "misconception_id": None},
                {"text": "Smaller heap usage", "misconception_id": None},
                {"text": "Automatic garbage collection", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Polymorphism enables dynamic binding at runtime.",
        }
        rec, reason = normalize_question(raw, "dynamic-method-dispatch", "Medium")
        self.assertIsNone(rec)
        self.assertEqual(reason, "too_many_null_misconceptions")

    def test_null_tag_gate_accepts_up_to_two_nulls(self):
        # 2 wrong options null, 1 wrong option valid misconception
        raw = {
            "question": "What does polymorphism achieve?",
            "qtype": "concept",
            "options": [
                {"text": "Dynamic method dispatch at runtime", "misconception_id": None},
                {"text": "Faster code execution by JVM compiler", "misconception_id": None},
                {"text": "Fields are also dispatched dynamically in subclasses", "misconception_id": "dynamic-method-dispatch/fields-dispatched-dynamically"},
                {"text": "Automatic garbage collection of unused", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Polymorphism allows dynamic selection of overridden methods.",
        }
        rec, reason = normalize_question(raw, "dynamic-method-dispatch", "Medium")
        self.assertIsNotNone(rec)
        self.assertIsNone(reason)

    def test_live_length_ratio_gate_rejects_above_1_03x(self):
        # Longest wrong option is 50 chars. Correct option is 53 chars (> 1.03 * 50 = 51.5)
        raw = {
            "question": "What is an abstract class in Java?",
            "qtype": "concept",
            "options": [
                {"text": "A class definition providing signatures and baseline", "misconception_id": None}, # 53 chars
                {"text": "A class that cannot ever hold concrete implementations", "misconception_id": "abstract-classes/cannot-have-concrete-methods"}, # 50 chars (truncated to 50: "A class that cannot ever hold concrete implementat")
                {"text": "A pure interface construct without instance variables", "misconception_id": "abstract-classes/must-have-abstract-methods"}, # 50 chars
                {"text": "A final class structure that disables inheritance use", "misconception_id": None}, # 50 chars
            ],
            "correct": 0,
            "explanation": "Abstract classes cannot be instantiated directly.",
        }
        # Format exact lengths:
        raw["options"][0]["text"] = "X" * 53
        raw["options"][1]["text"] = "A" * 50
        raw["options"][2]["text"] = "B" * 50
        raw["options"][3]["text"] = "C" * 50
        rec, reason = normalize_question(raw, "abstract-classes", "Easy", is_live=True)
        self.assertIsNone(rec)
        self.assertEqual(reason, "correct_option_too_long")

    def test_live_length_ratio_gate_accepts_under_1_03x(self):
        # Longest wrong option is 100 chars. Correct option is 102 chars (<= 1.03 * 100 = 103)
        raw = {
            "question": "What is an abstract class in Java?",
            "qtype": "concept",
            "options": [
                {"text": "X" * 102, "misconception_id": None},
                {"text": "A" * 100, "misconception_id": "abstract-classes/cannot-have-concrete-methods"},
                {"text": "B" * 98, "misconception_id": "abstract-classes/must-have-abstract-methods"},
                {"text": "C" * 95, "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Abstract classes cannot be instantiated directly.",
        }
        rec, reason = normalize_question(raw, "abstract-classes", "Easy", is_live=True)
        self.assertIsNotNone(rec)
        self.assertIsNone(reason)

    def test_live_absolute_word_bias_rejects(self):
        # 2 wrong options have absolute words, correct does not
        raw = {
            "question": "Which statement about abstract methods in Java is correct?",
            "qtype": "concept",
            "options": [
                {"text": "Abstract methods define a signature without body.", "misconception_id": None},
                {"text": "Abstract methods always execute static routines here.", "misconception_id": "abstract-classes/cannot-have-concrete-methods"},
                {"text": "Abstract methods never require subclass override code.", "misconception_id": "abstract-classes/must-have-abstract-methods"},
                {"text": "Abstract methods are defined as private variables now.", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Abstract methods define signatures without bodies.",
        }
        rec, reason = normalize_question(raw, "abstract-classes", "Easy", is_live=True)
        self.assertIsNone(rec)
        self.assertEqual(reason, "absolute_word_bias")

    def test_live_absolute_word_bias_accepts_balanced(self):
        # Only 1 wrong option has an absolute word
        raw = {
            "question": "Which statement about abstract methods in Java is correct?",
            "qtype": "concept",
            "options": [
                {"text": "Abstract methods define a signature without body.", "misconception_id": None},
                {"text": "Abstract methods always execute static routines here.", "misconception_id": "abstract-classes/cannot-have-concrete-methods"},
                {"text": "Abstract methods specify contract behavior in Java.", "misconception_id": "abstract-classes/must-have-abstract-methods"},
                {"text": "Abstract methods are defined as private variables now.", "misconception_id": None},
            ],
            "correct": 0,
            "explanation": "Abstract methods define signatures without bodies.",
        }
        rec, reason = normalize_question(raw, "abstract-classes", "Easy", is_live=True)
        self.assertIsNotNone(rec)
        self.assertIsNone(reason)


class TestIndependentVerifier(unittest.TestCase):
    """Test 3: Independent Verifier gate in ConceptClarifierAgent."""

    def setUp(self):
        self.clarifier = ConceptClarifierAgent(api_key="test-key", model="openai/gpt-oss-120b")
        self.clarifier.client = MagicMock()

    def test_verifier_rejects_wrong_answer(self):
        # Question key is 1, verifier says answer is 2
        question = {
            "question": "What does super() do?",
            "options": ["Calls subclass", "Calls superclass constructor", "Exits method", "Creates static field"],
            "correct": 1,
            "option_misconception_ids": ["constructor-chaining/super-calls-subclass", None, None, None],
            "qtype": "concept",
        }
        fake_response = {
            "verifications": [
                {"index": 0, "answer": 2, "ambiguous": False, "labels": [None, None, None, None], "note": "Wrong"}
            ]
        }
        with patch.object(self.clarifier, "_call_llm", return_value=fake_response):
            acc, rej, tags_rem, warn, v_model = self.clarifier.verify_group([question], "constructor-chaining")

        self.assertEqual(len(acc), 0)
        self.assertEqual(len(rej), 1)
        self.assertEqual(rej[0][1], "verifier_wrong_answer")

    def test_verifier_rejects_ambiguous_question(self):
        # Verifier says ambiguous: true
        question = {
            "question": "What does super() do?",
            "options": ["Calls subclass", "Calls superclass constructor", "Exits method", "Creates static field"],
            "correct": 1,
            "option_misconception_ids": ["constructor-chaining/super-calls-subclass", None, None, None],
            "qtype": "concept",
        }
        fake_response = {
            "verifications": [
                {"index": 0, "answer": 1, "ambiguous": True, "labels": [None, None, None, None], "note": "Ambiguous stem"}
            ]
        }
        with patch.object(self.clarifier, "_call_llm", return_value=fake_response):
            acc, rej, tags_rem, warn, v_model = self.clarifier.verify_group([question], "constructor-chaining")

        self.assertEqual(len(acc), 0)
        self.assertEqual(len(rej), 1)
        self.assertEqual(rej[0][1], "verifier_ambiguous")

    def test_verifier_accepts_valid_and_aligns_tags(self):
        # Generator has tags: [tag_agree, None, tag_disagree, None]
        # Verifier returns labels: [tag_agree, None, other_tag, None]
        # Agreement kept, disagreement cleared to None
        question = {
            "question": "What does super() do in constructor?",
            "options": [
                "Calls the direct superclass constructor",
                "Invokes all subclasses recursively",
                "Reinitializes current instance variables",
                "Calls nothing if omitted",
            ],
            "correct": 0,
            "option_misconception_ids": [
                None,
                "constructor-chaining/super-calls-all-subclasses",
                "constructor-chaining/super-reinitializes-fields",
                None,
            ],
            "qtype": "concept",
        }
        fake_response = {
            "verifications": [
                {
                    "index": 0,
                    "answer": 0,
                    "ambiguous": False,
                    "labels": [
                        None,
                        "constructor-chaining/super-calls-all-subclasses",  # agrees!
                        "different-misconception",                          # disagrees!
                        None,
                    ],
                    "note": "Option 0 is unambiguously correct",
                }
            ]
        }
        with patch.object(self.clarifier, "_call_llm", return_value=fake_response):
            acc, rej, tags_rem, warn, v_model = self.clarifier.verify_group([question], "constructor-chaining")

        self.assertEqual(len(acc), 1)
        self.assertEqual(len(rej), 0)
        self.assertEqual(tags_rem, 1)  # one tag removed due to disagreement
        self.assertEqual(acc[0]["verified"], 1)
        self.assertEqual(acc[0]["verifier_model"], "qwen/qwen3.8-27b")
        # Check aligned tags
        self.assertEqual(
            acc[0]["option_misconception_ids"],
            [None, "constructor-chaining/super-calls-all-subclasses", None, None],
        )

    def test_verifier_unavailable_marks_unverified_and_warns(self):
        question = {
            "question": "What is an interface?",
            "options": ["A contract", "A class", "A variable", "A package"],
            "correct": 0,
            "option_misconception_ids": [None, None, None, None],
            "qtype": "concept",
        }
        with patch.object(self.clarifier, "_call_llm", return_value=None):
            acc, rej, tags_rem, warn, v_model = self.clarifier.verify_group([question], "interface-basics")

        # Must serve question but mark verified=0 and provide warning
        self.assertEqual(len(acc), 1)
        self.assertEqual(acc[0]["verified"], 0)
        self.assertIsNotNone(warn)
        self.assertIn("verifier_unavailable", warn)


class TestJavaCheckerLogic(unittest.TestCase):
    """Test 4: Java Checker compilation and runtime decision logic."""

    def test_class_renaming_and_stripping_public(self):
        snippet = (
            "public class Animal {\n"
            "    public void speak() {}\n"
            "}\n"
            "public class Dog extends Animal {\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(\"Woof\");\n"
            "    }\n"
            "}\n"
        )
        prepared, main_class = prepare_java_source(snippet)
        self.assertEqual(main_class, "Dog")
        self.assertIn("class Animal", prepared)
        self.assertNotIn("public class Animal", prepared)
        self.assertIn("public class Dog", prepared)

    def test_code_output_matching_and_mismatch(self):
        # Fake runner simulating matching program execution
        def fake_runner_match(cmd, timeout, cwd):
            if "javac" in cmd[0]:
                return 0, "", ""
            return 0, "42\n", ""

        checker = JavaChecker(runner=fake_runner_match)
        q_match = {
            "qtype": "code_output",
            "question": "What is printed? ```java public class Main { public static void main(String[] args) { System.out.println(42); } } ```",
            "options": ["42", "0", "null", "Error"],
            "correct": 0,
            "explanation": "Prints 42.",
        }
        ok, reason = checker.check_question(q_match)
        self.assertTrue(ok)
        self.assertIsNone(reason)

        # Fake runner simulating output mismatch
        def fake_runner_mismatch(cmd, timeout, cwd):
            if "javac" in cmd[0]:
                return 0, "", ""
            return 0, "99\n", ""

        checker_mismatch = JavaChecker(runner=fake_runner_mismatch)
        ok2, reason2 = checker_mismatch.check_question(q_match)
        self.assertFalse(ok2)
        self.assertEqual(reason2, "code_output_mismatch")

    def test_bug_find_single_error_and_explanation_keyword(self):
        # Exactly one error containing 'incompatible'
        def fake_runner_one_err(cmd, timeout, cwd):
            return 1, "", "Main.java:3: error: incompatible types: int cannot be converted to String\n1 error\n"

        checker = JavaChecker(runner=fake_runner_one_err)
        q_valid = {
            "qtype": "bug_find",
            "question": "What error occurs? ```java public class Main { public static void main(String[] args) { String s = 10; } } ```",
            "options": ["Incompatible types compile error", "Null pointer", "Runtime error", "Compiles fine"],
            "correct": 0,
            "explanation": "Fails to compile due to incompatible types: int cannot be assigned to String.",
        }
        ok, reason = checker.check_question(q_valid)
        self.assertTrue(ok)
        self.assertIsNone(reason)

        # Two errors
        def fake_runner_two_err(cmd, timeout, cwd):
            return 1, "", "Main.java:2: error: foo\nMain.java:3: error: bar\n2 errors\n"

        checker_two = JavaChecker(runner=fake_runner_two_err)
        ok_two, reason_two = checker_two.check_question(q_valid)
        self.assertFalse(ok_two)
        self.assertEqual(reason_two, "bug_find_error_count_2")

        # Zero error (code compiles)
        def fake_runner_zero_err(cmd, timeout, cwd):
            return 0, "", ""

        checker_zero = JavaChecker(runner=fake_runner_zero_err)
        ok_zero, reason_zero = checker_zero.check_question(q_valid)
        self.assertFalse(ok_zero)
        self.assertEqual(reason_zero, "bug_find_compiles")

        # Single error, but keyword missing from explanation
        q_missing_kw = dict(q_valid)
        q_missing_kw["explanation"] = "A syntax fault takes place here."
        ok_kw, reason_kw = checker.check_question(q_missing_kw)
        self.assertFalse(ok_kw)
        self.assertEqual(reason_kw, "bug_find_explanation_mismatch")

    def test_concept_snippet_must_compile(self):
        def fake_runner_fail(cmd, timeout, cwd):
            return 1, "", "Main.java:1: error: cannot find symbol\n1 error\n"

        checker = JavaChecker(runner=fake_runner_fail)
        q_concept = {
            "qtype": "concept",
            "question": "Consider ```java public class A { Undefined u; } ```",
            "options": ["A", "B", "C", "D"],
            "correct": 0,
            "explanation": "...",
        }
        ok, reason = checker.check_question(q_concept)
        self.assertFalse(ok)
        self.assertEqual(reason, "concept_snippet_compile_error")


class TestNoveltyAndDeduplication(unittest.TestCase):
    """Test 5: Novelty & Deduplication against same quiz, history, and bank reference."""

    class FakeEmbedder:
        def signature(self):
            return "fake:embedder:3"

        def embed_one(self, text):
            # Deterministic pseudo-embedding based on sha1
            h = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)
            angle = (h % 360) * (math.pi / 180.0)
            return [math.cos(angle), math.sin(angle), 0.0]

    def test_dedupe_same_quiz(self):
        q1 = {
            "question": "What is an interface?",
            "options": ["A contract", "A class", "A package", "A variable"],
            "correct": 0,
            "embedding": [1.0, 0.0, 0.0],
        }
        # Almost identical vector (cosine > 0.99)
        q2 = {
            "question": "What is an interface?",
            "options": ["A contract", "A class", "A package", "A variable"],
            "correct": 0,
            "embedding": [0.999, 0.01, 0.0],
        }
        ok, reason, mode = check_question_novelty(
            q2,
            accepted_in_quiz=[q1],
            embedder=self.FakeEmbedder(),
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "duplicate_in_quiz")
        self.assertEqual(mode, "vector")

    def test_dedupe_student_history(self):
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        conn = None
        try:
            with patch.dict(os.environ, {"EDUGEN_DB_PATH": db_path}):
                init_db(db_path)
                conn = get_db(db_path)
                cur = conn.cursor()
                cur.execute("INSERT INTO users (name, email, password_hash) VALUES ('Test', 'test@test.com', 'h')")
                uid = cur.lastrowid
                cur.execute("INSERT INTO students (name, user_id) VALUES ('Test', ?)", (uid,))
                sid = cur.lastrowid
                cur.execute("INSERT INTO quiz_results (student_id, topic, difficulty, score, total_questions) VALUES (?, 'OOP', 'Easy', 1, 1)", (sid,))
                qres_id = cur.lastrowid
                conn.commit()

                # Save seen question in DB with embedding [0.0, 1.0, 0.0]
                q_seen = {
                    "question": "Seen question stem",
                    "options": ["Opt0", "Opt1", "Opt2", "Opt3"],
                    "correct": 0,
                    "embedding": [0.0, 1.0, 0.0],
                }
                qids = record_generated_questions("inheritance-basics", "Easy", [q_seen])
                record_submission_history(sid, qres_id, [q_seen], {0: 0}, {0: 1000})

                # Close connection before query in check_question_novelty
                conn.close()
                conn = None

                # Candidate question with near-identical vector
                q_cand = {
                    "question": "Seen question stem variant",
                    "options": ["Opt0", "Opt1", "Opt2", "Opt3"],
                    "correct": 0,
                    "embedding": [0.01, 0.999, 0.0],
                }
                ok, reason, mode = check_question_novelty(
                    q_cand,
                    accepted_in_quiz=[],
                    student_id=sid,
                    embedder=self.FakeEmbedder(),
                )
                self.assertFalse(ok)
                self.assertEqual(reason, "already_seen_by_student")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if os.path.exists(db_path):
                try:
                    os.unlink(db_path)
                except Exception:
                    pass

    def test_dedupe_bank_reference_copy(self):
        ref_q = {
            "question": "What is method overriding?",
            "options": ["Redefining in subclass", "Overloading parameters", "Hiding fields", "Static binding"],
            "correct": 0,
        }
        # Candidate identical to reference question
        q_cand = {
            "question": "What is method overriding?",
            "options": ["Redefining in subclass", "Overloading parameters", "Hiding fields", "Static binding"],
            "correct": 0,
        }
        # Fake embedder returns identical vector for identical text
        ok, reason, mode = check_question_novelty(
            q_cand,
            accepted_in_quiz=[],
            ref_questions=[ref_q],
            embedder=self.FakeEmbedder(),
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "bank_reference_copy")

    def test_lexical_fallback_dedupe(self):
        # When embedder is False, use exact hash & Jaccard >= 0.80
        q1 = {
            "question": "Explain Java interface default methods and dynamic resolution",
            "options": ["A default method provides implementation", "Only static methods allowed", "No methods", "Compile error"],
            "correct": 0,
        }
        q2 = {
            "question": "Explain Java interface default methods and dynamic resolution in interfaces",
            "options": ["A default method provides implementation", "Only static methods allowed", "No methods", "Compile error"],
            "correct": 0,
        }
        ok, reason, mode = check_question_novelty(
            q2,
            accepted_in_quiz=[q1],
            embedder=False,  # force lexical mode
        )
        self.assertFalse(ok)
        self.assertEqual(mode, "lexical")
        self.assertEqual(reason, "duplicate_in_quiz")


class TestHTTP429Retry(unittest.TestCase):
    """Test 6: LLM call honours HTTP 429 with retry-after sleep and retries up to 2 times."""

    def test_429_retry_success(self):
        clarifier = ConceptClarifierAgent(api_key="fake-key", model="openai/gpt-oss-120b")
        mock_client = MagicMock()
        clarifier.client = mock_client

        # Mock exception with status_code 429 and retry-after header
        class Mock429(Exception):
            status_code = 429

        mock_resp_obj = MagicMock()
        mock_resp_obj.headers = {"retry-after": "0.1"}
        exc429 = Mock429("Rate limit exceeded")
        exc429.response = mock_resp_obj

        # 1st call fails 429, 2nd call fails 429, 3rd call succeeds!
        mock_success = MagicMock()
        mock_success.choices = [MagicMock(message=MagicMock(content=json.dumps({"status": "ok"})))]
        mock_success.usage = None

        mock_client.chat.completions.create.side_effect = [exc429, exc429, mock_success]

        t0 = time.time()
        result = clarifier._call_llm("system prompt", "user prompt")
        elapsed = time.time() - t0

        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(mock_client.chat.completions.create.call_count, 3)
        self.assertGreaterEqual(elapsed, 0.2)  # Slept twice for 0.1s


class TestDiagnosticSetSelection(unittest.TestCase):
    """Test 7: api_quiz_start never serves a diagnostic set seen by the student."""

    def setUp(self):
        self.diag_dir = BASE_DIR / "rag" / "corpus" / "diagnostic"
        self.diag_dir.mkdir(parents=True, exist_ok=True)

        # Create two diagnostic sets: set_test_1 and set_test_2
        self.set_a_file = self.diag_dir / "set_test_1.json"
        self.set_b_file = self.diag_dir / "set_test_2.json"

        set_a_data = {
            "set_name": "set_test_1",
            "concept": "diagnostic",
            "difficulty": "diagnostic",
            "questions": [
                {
                    "question": f"Question A {i}",
                    "options": ["O0", "O1", "O2", "O3"],
                    "correct": 0,
                    "explanation": "Exp A",
                    "concept": "class-definition",
                    "concept_tags": ["class-definition"],
                    "difficulty": "Easy",
                    "qtype": "concept",
                    "option_misconception_ids": [None, None, None, None],
                }
                for i in range(12)
            ],
            "total_generated": 12,
            "build_report": {"requested": 12, "accepted": 12},
        }
        with open(self.set_a_file, "w", encoding="utf-8") as f:
            json.dump(set_a_data, f)

        set_b_data = {
            "set_name": "set_test_2",
            "concept": "diagnostic",
            "difficulty": "diagnostic",
            "questions": [
                {
                    "question": f"Question B {i}",
                    "options": ["O0", "O1", "O2", "O3"],
                    "correct": 0,
                    "explanation": "Exp B",
                    "concept": "inheritance-basics",
                    "concept_tags": ["inheritance-basics"],
                    "difficulty": "Medium",
                    "qtype": "concept",
                    "option_misconception_ids": [None, None, None, None],
                }
                for i in range(12)
            ],
            "total_generated": 12,
            "build_report": {"requested": 12, "accepted": 12},
        }
        with open(self.set_b_file, "w", encoding="utf-8") as f:
            json.dump(set_b_data, f)

    def tearDown(self):
        if self.set_a_file.exists():
            self.set_a_file.unlink()
        if self.set_b_file.exists():
            self.set_b_file.unlink()

    def test_diagnostic_set_selection_avoids_seen_set(self):
        app = create_app()
        with app.app_context():
            db_path = init_db()
            conn = get_db()
            cur = conn.cursor()
            test_email = f"diag_{time.time()}@test.com"
            cur.execute("INSERT INTO users (name, email, password_hash) VALUES ('DiagStudent', ?, 'h')", (test_email,))
            uid = cur.lastrowid
            cur.execute("INSERT INTO students (name, user_id) VALUES ('DiagStudent', ?)", (uid,))
            sid = cur.lastrowid
            cur.execute("INSERT INTO quiz_results (student_id, topic, difficulty, score, total_questions) VALUES (?, 'OOP', 'Easy', 12, 12)", (sid,))
            qres_id = cur.lastrowid
            conn.commit()

            # Record all questions from set_test_1 as seen by this student
            with open(self.set_a_file, "r", encoding="utf-8") as f:
                set_a = json.load(f)
            record_generated_questions("diagnostic", "diagnostic", set_a["questions"])
            record_submission_history(sid, qres_id, set_a["questions"], {i: 0 for i in range(12)}, {i: 500 for i in range(12)})
            conn.close()

            client = app.test_client()
            with client.session_transaction() as sess:
                sess["user_id"] = uid
                sess["student_id"] = sid

            orig_glob = Path.glob
            def mock_glob(path_self, pattern):
                if "set_*.json" in pattern:
                    return iter([self.set_a_file, self.set_b_file])
                return orig_glob(path_self, pattern)

            with patch.object(Path, "glob", side_effect=mock_glob, autospec=True):
                resp = client.post("/api/quiz/start", json={"kind": "diagnostic"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data.get("kind"), "diagnostic")
            # Ensure questions served are from set_test_2, NOT set_test_1!
            q0_text = data["questions"][0]["question"]
            self.assertIn("Question B", q0_text)
            self.assertNotIn("Question A", q0_text)


if __name__ == "__main__":
    unittest.main()
