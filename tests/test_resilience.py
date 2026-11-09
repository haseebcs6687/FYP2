"""
=============================================================================
EduGen - System Resilience & Graceful Degradation Tests (tests/test_resilience.py)
=============================================================================
Tests graceful failure and offline fallback behavior with zero network calls:
  1. Ollama down (ConnectionError / timeout):
     - RAG retrieval falls back to lexical/BM25 without crashing
     - Quiz generation serves from pool without 500
     - Lesson generation serves cached/local note without 500
  2. Groq down (Timeout, RateLimit 429, missing/invalid key):
     - Pool quiz generation succeeds with 100% pool hit rate
     - Live quiz generation with exhausted pool fails gracefully (friendly JSON, no 500)
     - Lesson generation falls back to local concept note (no 500)
     - Performance Analysis executes cleanly (offline rule-based BKT engine)
     - Evaluator event bus captures events cleanly
  3. Both down (Total AI service outage):
     - Student can login (/api/login)
     - Student can view dashboard (/dashboard)
     - Student can view study plan (/plan)
     - Student can start and submit a pool quiz (/api/quiz/start and /api/quiz/submit)
  4. Health check endpoint (GET /api/health):
     - Returns 200 with db status, ollama status, groq status, and pool counts
     - Zero secret keys or credential leakage
=============================================================================
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.db as db
from app import create_app
from core.event_bus import emit, get_logs
from rag.retriever import Retriever
from scripts.test_csrf_helper import csrf_headers, csrf_post


class ResilienceTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary SQLite database populated from data/edugen.db
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.temp_dir, "test_resilience.db")
        real_db = BASE_DIR / "data" / "edugen.db"
        if real_db.exists():
            shutil.copy(str(real_db), cls.db_path)
        else:
            db.init_db(cls.db_path)

        os.environ["EDUGEN_DB_PATH"] = cls.db_path
        db.DB_PATH = cls.db_path

        # Find demo student IDs in database
        conn = db.get_db(cls.db_path)
        r = conn.execute(
            "SELECT u.id as uid, s.id as sid FROM users u LEFT JOIN students s ON s.user_id = u.id WHERE u.email = 'demo@edugen.local'"
        ).fetchone()
        if r:
            cls.demo_uid = r["uid"]
            cls.demo_sid = r["sid"]
        else:
            cls.demo_uid = 1
            cls.demo_sid = 1
        conn.close()

        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["SECRET_KEY"] = "test-resilience-secret"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.demo_uid
            sess["student_id"] = self.demo_sid
            sess["user_name"] = "Demo Student"
            sess["email"] = "demo@edugen.local"

    # ─────────────────────────────────────────────────────────────
    # 1. Ollama Outage Scenarios
    # ─────────────────────────────────────────────────────────────

    def test_rag_retrieval_ollama_down(self):
        """When Ollama raises ConnectionError, RAG falls back to lexical retrieval without 500."""
        retriever = Retriever(backend="ollama")
        brief = {
            "concept": "class-definition",
            "query": "class definition Java syntax",
            "difficulty": "Easy",
            "action": "remediate",
            "focus_notes": ["Explain class anatomy"],
        }
        with patch("requests.post", side_effect=Exception("Ollama Connection Refused")):
            res = retriever.retrieve(brief)
            self.assertIsInstance(res, dict)
            self.assertIn("passages", res)
            self.assertIn("citations", res)
            # Should still return citations/passages via lexical fallback
            self.assertGreater(len(res["passages"]), 0)

    def test_quiz_generation_ollama_down(self):
        """When Ollama is down, pool-based quiz generation still succeeds via SQLite pool."""
        with patch("requests.post", side_effect=Exception("Ollama Connection Refused")):
            res = csrf_post(
                self.client,
                "/api/quiz/start",
                json={"concept": "default-constructor", "difficulty": "Easy", "count": 3},
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(len(data.get("questions", [])), 3)
            self.assertEqual(data.get("generated_by"), "pool")

    def test_lesson_generation_ollama_down(self):
        """When Ollama is down, lesson endpoint serves content without 500."""
        with patch("requests.post", side_effect=Exception("Ollama Connection Refused")):
            res = self.client.get("/api/lesson/class-definition/Easy")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("explanation", data)
            self.assertIn(data.get("generated_by"), ("llm+rag", "llm", "local-note"))

    # ─────────────────────────────────────────────────────────────
    # 2. Groq Outage Scenarios
    # ─────────────────────────────────────────────────────────────

    def test_quiz_generation_groq_down_pool_serves(self):
        """When Groq LLM raises 429/timeout, quizzes with sufficient pool questions still serve 100%."""
        with patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq 429 Rate Limit")):
            res = csrf_post(
                self.client,
                "/api/quiz/start",
                json={"concept": "default-constructor", "difficulty": "Easy", "count": 3},
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(len(data.get("questions", [])), 3)
            self.assertEqual(data.get("generated_by"), "pool")

    def test_live_quiz_generation_groq_down_graceful(self):
        """When pool cannot fill a slot and Groq is down, returns friendly message without 500 stack trace."""
        # Concept with empty Hard pool: null-pointer-exception
        with patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq Connection Timeout")):
            res = csrf_post(
                self.client,
                "/api/quiz/start",
                json={"concept": "null-pointer-exception", "difficulty": "Hard", "count": 3},
            )
            # Must return 503 (or graceful partial), never 500
            self.assertIn(res.status_code, (200, 503))
            data = res.get_json()
            if res.status_code == 503:
                self.assertIn("error", data)
                self.assertNotIn("Traceback", json.dumps(data))

    def test_lesson_generation_groq_down(self):
        """When Groq is down, lesson generation falls back to local concept note without 500."""
        with patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", return_value=None):
            res = self.client.get("/api/lesson/data-hiding/Medium")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get("generated_by"), "local-note")
            self.assertIn("explanation", data)
            self.assertGreater(len(data["explanation"]), 20)

    def test_performance_analysis_groq_down(self):
        """Performance analysis executes completely offline using BKT graph rules (zero LLM calls)."""
        from agents.performance_analysis_agent import PerformanceAnalysisAgent
        pa = PerformanceAnalysisAgent()
        with patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq Offline")):
            report = pa.analyze_student(self.demo_sid, db_path=self.db_path)
            self.assertIsInstance(report, dict)
            self.assertIn("overall_performance", report)
            self.assertIn("concept_stats", report)
            self.assertIn("weak_topics", report)

    def test_evaluator_events_groq_down(self):
        """Event bus captures structured telemetry cleanly without calling external services."""
        with patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq Down")):
            emit("Coordinator", "test_event", "Resilience event test", level="info", student_id=self.demo_sid)
            events = get_logs()
            self.assertGreater(len(events), 0)
            found = any(e.get("action") == "test_event" for e in events)
            self.assertTrue(found)

    # ─────────────────────────────────────────────────────────────
    # 3. Both Services Down (Total AI Outage)
    # ─────────────────────────────────────────────────────────────

    def test_both_down_student_login(self):
        """Student login operates purely on SQLite users table without external AI dependencies."""
        with patch("requests.post", side_effect=Exception("Network Outage")), \
             patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq Outage")):
            res = csrf_post(
                self.client,
                "/api/auth/login",
                json={"email": "demo@edugen.local", "password": "demo-pass"},
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get("email"), "demo@edugen.local")

    def test_both_down_dashboard_view(self):
        """Dashboard renders server-side template without external network calls."""
        with patch("requests.post", side_effect=Exception("Network Outage")), \
             patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq Outage")):
            res = self.client.get("/dashboard")
            self.assertEqual(res.status_code, 200)
            self.assertIn(b"EduGen", res.data)

    def test_both_down_plan_view(self):
        """Study plan page renders server-side template without external network calls."""
        with patch("requests.post", side_effect=Exception("Network Outage")), \
             patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq Outage")):
            res = self.client.get("/plan")
            self.assertEqual(res.status_code, 200)
            self.assertIn(b"Study Plan", res.data)

    def test_both_down_pool_quiz_and_submit(self):
        """Starting and submitting a pool quiz functions completely when both Ollama and Groq are down."""
        with patch("requests.post", side_effect=Exception("Network Outage")), \
             patch("agents.concept_clarifier_agent.ConceptClarifierAgent._call_llm", side_effect=Exception("Groq Outage")):
            # 1. Start quiz
            res_start = csrf_post(
                self.client,
                "/api/quiz/start",
                json={"concept": "default-constructor", "difficulty": "Easy", "count": 3},
            )
            self.assertEqual(res_start.status_code, 200)
            quiz_data = res_start.get_json()
            session_id = quiz_data.get("quiz_session_id") or quiz_data.get("session_id")
            questions = quiz_data.get("questions", [])
            self.assertEqual(len(questions), 3)

            # 2. Submit quiz
            answers = {str(i): 0 for i in range(len(questions))}
            times = {str(i): 5000 for i in range(len(questions))}
            res_submit = csrf_post(
                self.client,
                "/api/quiz/submit",
                json={"quiz_session_id": session_id, "session_id": session_id, "answers": answers, "timings": times},
            )
            self.assertEqual(res_submit.status_code, 200)
            result_data = res_submit.get_json()
            self.assertIn("score", result_data)
            self.assertEqual(result_data.get("total"), 3)

    # ─────────────────────────────────────────────────────────────
    # 4. System Health Check Endpoint
    # ─────────────────────────────────────────────────────────────

    def test_api_health_endpoint(self):
        """GET /api/health returns database, ollama, groq status and pool counts without exposing secrets."""
        res = self.client.get("/api/health")
        self.assertIn(res.status_code, (200, 503))
        data = res.get_json()
        self.assertIn("database", data)
        self.assertIn("ollama", data)
        self.assertIn("groq", data)
        self.assertIn("pool", data)

        # Confirm no secrets or credentials leaked
        data_str = json.dumps(data)
        self.assertNotIn("gsk_", data_str)
        self.assertNotIn("password", data_str)
        self.assertNotIn("secret", data_str.lower().replace("test-resilience-secret", ""))


if __name__ == "__main__":
    unittest.main()
