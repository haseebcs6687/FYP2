"""
=============================================================================
EduGen - UI, Evaluator Window & Bias Gate Verification Suite
scripts/test_ui.py
=============================================================================
Verifies mechanically:
  1. Student mode purity: none of the 11 banned strings appears in student
     page HTML or student-facing JSON endpoints across 10 pages and APIs.
  2. Evaluator activity window: pill absent on public pages (/, /login),
     present on logged-in pages with minimize/close controls and polling logic.
  3. Evaluator API endpoints: all return the exact telemetry fields listed in D3.
  4. Garbled-title cleaner: unit tests for corruption filtering and clean titles.
  5. Bias guard gates: accepts balanced questions, rejects length disparity > 1.10x,
     and rejects distractor absolute-word bias.
=============================================================================
"""

import os
import re
import sys
from pathlib import Path
import unittest
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from core.db_repo import get_db, record_generated_questions
from core.quiz_engine import normalize_question
from routes.title_cleaner import (
    clean_book_title,
    clean_passage_title,
    format_clean_sources_line,
    is_title_garbled,
)

BANNED_STRINGS = [
    "Rule R",
    "Adaptive Content Agent",
    "Agent pipeline",
    "cosine",
    ".pdf",
    "ollama",
    "Embedder",
    "passages indexed",
    "How this quiz is built",
    "fixed question bank",
    "Evidence behind",
]


class TestStudentModePurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

        # Seed demo user/student and dummy quiz result if needed
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = 'test_ui@edugen.local'")
        u = cur.fetchone()
        if not u:
            cur.execute(
                "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
                ("test_ui@edugen.local", "dummy_hash", "Test Student"),
            )
            cls.user_id = cur.lastrowid
            cur.execute(
                "INSERT INTO students (user_id, name, created_at) VALUES (?, ?, ?)",
                (cls.user_id, "Test Student", "2026-11-05T00:00:00"),
            )
            cls.student_id = cur.lastrowid
        else:
            cls.user_id = u["id"]
            s = cur.execute("SELECT id FROM students WHERE user_id = ?", (cls.user_id,)).fetchone()
            cls.student_id = s["id"]

        # Ensure a quiz session and result exists for testing result page
        cur.execute("SELECT id FROM quiz_results WHERE student_id = ? LIMIT 1", (cls.student_id,))
        r = cur.fetchone()
        if not r:
            cur.execute(
                """INSERT INTO quiz_results (student_id, topic, difficulty, score, total_questions, attempt_number, timestamp, concept, source, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cls.student_id, "classes-objects", "Easy", 4, 5, 1, "2026-11-05T00:00:00", "class-definition", "pool", 12000),
            )
            cls.result_id = cur.lastrowid
        else:
            cls.result_id = r["id"]

        conn.commit()
        conn.close()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["student_id"] = self.student_id

    def _logout(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    def test_logged_out_pages_free_of_banned_strings(self):
        self._logout()
        for endpoint in ["/", "/login"]:
            res = self.client.get(endpoint)
            self.assertEqual(res.status_code, 200, f"Page {endpoint} failed")
            html = res.get_data(as_text=True)
            for banned in BANNED_STRINGS:
                self.assertNotIn(
                    banned.lower(),
                    html.lower(),
                    f"Banned string '{banned}' found in logged-out page {endpoint}",
                )

    def test_logged_in_pages_free_of_banned_strings(self):
        self._login()
        pages = [
            "/dashboard",
            "/learn",
            "/learn/class-definition",
            "/quiz",
            f"/quiz/result/{self.result_id}",
            "/plan",
            "/analysis",
            "/history",
        ]
        for endpoint in pages:
            res = self.client.get(endpoint)
            self.assertEqual(res.status_code, 200, f"Page {endpoint} failed with {res.status_code}")
            html = res.get_data(as_text=True)
            for banned in BANNED_STRINGS:
                self.assertNotIn(
                    banned.lower(),
                    html.lower(),
                    f"Banned string '{banned}' found in student page {endpoint}",
                )

    def test_student_json_endpoints_free_of_banned_strings(self):
        self._login()
        json_endpoints = [
            "/api/session?generate=0",
            "/api/recommendation",
            "/api/analysis",
            "/api/lesson/class-definition/Easy",
            "/api/plan",
        ]
        for endpoint in json_endpoints:
            res = self.client.get(endpoint)
            self.assertIn(res.status_code, (200, 404), f"API {endpoint} failed with {res.status_code}")
            data = res.get_data(as_text=True)
            for banned in BANNED_STRINGS:
                self.assertNotIn(
                    banned.lower(),
                    data.lower(),
                    f"Banned string '{banned}' found in JSON endpoint {endpoint}",
                )


class TestEvaluatorActivityWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

        conn = get_db()
        u = conn.execute("SELECT id FROM users WHERE email = 'test_ui@edugen.local'").fetchone()
        if not u:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
                ("test_ui@edugen.local", "dummy_hash", "Test Student"),
            )
            cls.user_id = cur.lastrowid
            cur.execute(
                "INSERT INTO students (user_id, name, created_at) VALUES (?, ?, ?)",
                (cls.user_id, "Test Student", "2026-11-05T00:00:00"),
            )
            cls.student_id = cur.lastrowid
            conn.commit()
        else:
            cls.user_id = u["id"]
            s = conn.execute("SELECT id FROM students WHERE user_id = ?", (cls.user_id,)).fetchone()
            cls.student_id = s["id"]
        conn.close()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["student_id"] = self.student_id

    def _logout(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    def test_pill_absent_on_public_pages(self):
        self._logout()
        for endpoint in ["/", "/login", "/about"]:
            res = self.client.get(endpoint)
            html = res.get_data(as_text=True)
            self.assertNotIn('id="evaluator-pill"', html, f"Evaluator pill found on public page {endpoint}")
            self.assertNotIn('id="evaluator-panel"', html, f"Evaluator panel found on public page {endpoint}")

    def test_pill_and_panel_controls_present_when_logged_in(self):
        self._login()
        logged_in_pages = [
            "/dashboard",
            "/learn",
            "/quiz",
            "/analysis",
            "/history",
            "/plan",
        ]
        for endpoint in logged_in_pages:
            res = self.client.get(endpoint)
            self.assertEqual(res.status_code, 200, f"Page {endpoint} failed")
            html = res.get_data(as_text=True)
            self.assertIn('id="evaluator-pill"', html, f"Missing pill on {endpoint}")
            self.assertIn('id="evaluator-panel"', html, f"Missing panel on {endpoint}")
            self.assertIn('id="eval-minimize-btn"', html, f"Missing minimize button on {endpoint}")
            self.assertNotIn('id="eval-close-btn"', html, f"Found close button on {endpoint}")
            self.assertIn('data-tab="live"', html)
            self.assertIn('data-tab="runs"', html)
            self.assertIn('data-tab="rag"', html)
            self.assertIn('data-tab="decisions"', html)
            self.assertIn('data-tab="quiz_build"', html)
            self.assertIn('data-tab="system"', html)

    def test_polling_code_present_in_js(self):
        js_path = os.path.join(self.app.root_path, "static", "js", "edugen.js")
        with open(js_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/api/events", content)
        self.assertIn("EvaluatorWindow", content)
        self.assertIn("pollEvents", content)
        self.assertIn("eval_state", content)
        self.assertIn("isPolling", content)

        # Assert static/js/edugen.js contains no reference to state 'closed'
        self.assertNotIn("'closed'", content, "Found state 'closed' in edugen.js")
        self.assertNotIn('"closed"', content, 'Found state "closed" in edugen.js')

        # Static check that a stored state other than 'open' or 'minimized' normalizes to 'minimized'
        # The normalization pattern ensures only 'open' is kept as 'open'; everything else defaults to 'minimized'
        self.assertTrue(
            "savedState === 'open'" in content and "this.state = 'minimized'" in content,
            "State normalization to 'minimized' missing in edugen.js init()",
        )
        self.assertTrue(
            "if (st !== 'open')" in content or "st = 'minimized'" in content,
            "State normalization missing in edugen.js setState()",
        )

    def test_evaluator_endpoints_return_required_fields(self):
        self._login()

        # 1. /api/events
        res = self.client.get("/api/events")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("events", data)
        self.assertIn("last_id", data)

        # 2. /api/evaluator/system
        res = self.client.get("/api/evaluator/system")
        self.assertEqual(res.status_code, 200)
        sys_data = res.get_json()
        self.assertIn("agent_status", sys_data)
        self.assertIn("kb_size", sys_data)
        self.assertIn("embedder", sys_data)
        self.assertIn("model", sys_data)
        self.assertIn("token_budget", sys_data)
        self.assertIn("automation_ratio", sys_data)

        # 3. /api/evaluator/rag
        res = self.client.get("/api/evaluator/rag")
        self.assertEqual(res.status_code, 200)
        rag_data = res.get_json()
        self.assertIn("retrievals", rag_data)
        self.assertGreater(len(rag_data["retrievals"]), 0)
        first_ret = rag_data["retrievals"][0]
        self.assertIn("query", first_ret)
        self.assertIn("concept_filter", first_ret)
        self.assertIn("top_k_passages", first_ret)
        if first_ret["top_k_passages"]:
            p = first_ret["top_k_passages"][0]
            for key in ["source_file", "cleaned_section", "cosine", "lexical", "tag_score", "final_score"]:
                self.assertIn(key, p)

        # 4. /api/evaluator/decisions
        res = self.client.get("/api/evaluator/decisions")
        self.assertEqual(res.status_code, 200)
        dec_data = res.get_json()
        for key in ["rule_fired", "concepts_considered", "evidence", "coverage_check", "plan_steps"]:
            self.assertIn(key, dec_data)

        # 5. /api/evaluator/quiz-build
        res = self.client.get("/api/evaluator/quiz-build")
        self.assertEqual(res.status_code, 200)
        qb_data = res.get_json()
        for key in ["served_from", "gate_rejections", "verifier_result", "bias_gate_rejections"]:
            self.assertIn(key, qb_data)


class TestGarbledTitleCleaner(unittest.TestCase):
    def test_clean_book_title(self):
        self.assertEqual(clean_book_title("Thinking_In_Java.pdf"), "Thinking In Java")
        self.assertEqual(clean_book_title("data/corpus/JavaNotesForProfessionals.pdf"), "JavaNotesForProfessionals")
        self.assertEqual(clean_book_title(None), "Java Reference")

    def test_garbled_title_detection(self):
        # Corrupted fragments
        self.assertTrue(is_title_garbled("$% &outines nested in"))
        self.assertTrue(is_title_garbled("Section $% 1.2"))
        self.assertTrue(is_title_garbled("Functions & methods &classes"))
        # Low letter density (<60%)
        self.assertTrue(is_title_garbled("12345 67890 !@#"))
        self.assertTrue(is_title_garbled(""))

        # Normal titles
        self.assertFalse(is_title_garbled("Chapter 4: Classes and Objects"))
        self.assertFalse(is_title_garbled("Inheritance & Polymorphism"))

    def test_clean_passage_title_garbled_falls_back_to_book(self):
        # Corrupted title falls back to book title only
        cleaned = clean_passage_title("JavaNotesForProfessionals.pdf", "$% &outines nested in")
        self.assertEqual(cleaned, "JavaNotesForProfessionals")

        # Valid title shows '<book title>, <chapter/section>'
        cleaned_valid = clean_passage_title("Thinking_In_Java.pdf", "Chapter 7: Polymorphism")
        self.assertEqual(cleaned_valid, "Thinking In Java, Chapter 7: Polymorphism")

    def test_format_clean_sources_line(self):
        sources = [
            {"source": "JavaNotesForProfessionals.pdf", "section": "$% &outines nested in"},
            {"source": "Thinking_In_Java.pdf", "section": "Chapter 7: Polymorphism"},
        ]
        line = format_clean_sources_line(sources)
        self.assertEqual(line, "Sources: JavaNotesForProfessionals; Thinking In Java, Chapter 7: Polymorphism")


class TestQuizBiasGate(unittest.TestCase):
    def test_accepts_balanced_question(self):
        q = {
            "question": "What is the primary role of a class in Java?",
            "options": [
                "It acts as a blueprint defining the structure and behavior of objects.",
                "It directly holds the runtime data for every object instance created.",
                "It allows multiple public top-level classes in a single source file.",
                "It compiles source code directly into native machine instructions.",
            ],
            "correct": 0,
            "concept": "class-definition",
            "difficulty": "Easy",
            "explanation": "A class defines the blueprint and members for objects.",
            "option_misconceptions": [
                None,
                "class-definition/class-stores-instance-data",
                "class-definition/multiple-public-classes",
                None,
            ],
        }
        res, reason = normalize_question(q, "class-definition", "Easy", is_live=True)
        self.assertIsNotNone(res)
        self.assertIsNone(reason)

    def test_rejects_correct_option_too_long(self):
        # Correct option is much longer than 1.10x the longest wrong option
        q = {
            "question": "What is polymorphism?",
            "options": [
                "Polymorphism is the fundamental ability in object-oriented programming for different classes to provide different implementations of methods that are called through the same common interface or superclass reference.",
                "It compiles code.",
                "It deletes objects.",
                "It loads classes.",
            ],
            "correct": 0,
            "concept": "polymorphism-concept",
            "difficulty": "Easy",
            "explanation": "Polymorphism enables interchangeable method behavior.",
        }
        res, reason = normalize_question(q, "polymorphism-concept", "Easy", is_live=True)
        self.assertIsNone(res)
        self.assertEqual(reason, "correct_option_too_long")

    def test_rejects_absolute_word_bias(self):
        # 2 wrong options contain absolute words (always, never) while correct does not,
        # with balanced option lengths so length gate does not trigger first.
        q = {
            "question": "Which statement about abstract methods in Java is correct?",
            "options": [
                "Abstract methods define a method signature without an implementation body.",
                "Abstract methods always execute static utility initialization routines here.",
                "Abstract methods never require concrete subclass method overrides in Java.",
                "Abstract methods are defined as private variables within concrete classes.",
            ],
            "correct": 0,
            "concept": "abstract-classes",
            "difficulty": "Easy",
            "explanation": "Abstract methods specify signatures without implementation bodies.",
        }
        res, reason = normalize_question(q, "abstract-classes", "Easy", is_live=True)
        self.assertIsNone(res)
        self.assertEqual(reason, "absolute_word_bias")


if __name__ == "__main__":
    unittest.main()
