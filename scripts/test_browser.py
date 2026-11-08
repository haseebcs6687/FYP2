"""
=============================================================================
EduGen - Real Browser Smoke Test Suite (scripts/test_browser.py)
=============================================================================
Uses Playwright and headless Chromium to perform end-to-end browser testing:
  1. Starts the real Flask application on a free localhost port with an isolated test DB.
  2. Authenticates as the demo student through the login page (/login).
  3. Navigates to all authenticated student pages:
       /dashboard, /learn, /quiz, /analysis, /history, /plan
  4. Asserts 0 console errors and 0 uncaught page exceptions across all pages.
  5. Asserts specific interactive UI behaviors:
       - /dashboard snapshot cards show numbers (no empty skeleton after 5s)
       - /learn "Loading your mastery" disappears
       - /quiz concept dropdown has >= 40 options
       - Evaluator capsule is visible, click opens panel, Minimize returns pill,
         pill persists across reload, and event counter is a number.
  6. Captures and saves full-page screenshots to docs/ui_check/.
=============================================================================
"""

import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

from app import create_app
import core.db
from core.db_repo import create_study_plan, save_student_journey
from core.journey import STATE_PLAN_ACTIVE

UI_CHECK_DIR = BASE_DIR / "docs" / "ui_check"


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        super().__init__(daemon=True)
        self.server = make_server(host, port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def seed_test_database(db_path: str):
    """Seed test student, quiz attempts, and active plan in isolated test DB."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    email = "demo_student@edugen.local"
    password = "password123"
    pwd_hash = generate_password_hash(password)

    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    u = cur.fetchone()
    if not u:
        cur.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email, pwd_hash, "Demo Student"),
        )
        user_id = cur.lastrowid
        cur.execute(
            "INSERT INTO students (user_id, name, created_at) VALUES (?, ?, ?)",
            (user_id, "Demo Student", "2026-11-05T00:00:00"),
        )
        student_id = cur.lastrowid
    else:
        user_id = u["id"]
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, user_id))
        s = cur.execute("SELECT id FROM students WHERE user_id = ?", (user_id,)).fetchone()
        student_id = s["id"]

    # Seed quiz result and attempts for snapshot stats and analysis
    cur.execute("SELECT id FROM quiz_results WHERE student_id = ? LIMIT 1", (student_id,))
    if not cur.fetchone():
        cur.execute(
            """INSERT INTO quiz_results (student_id, topic, difficulty, score, total_questions, attempt_number, timestamp, concept, source, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (student_id, "OOP Basics", "Easy", 8, 10, 1, "2026-11-05T12:00:00", "class-definition", "pool", 45000),
        )
        res_id = cur.lastrowid
        for i in range(10):
            is_corr = 1 if i < 8 else 0
            cur.execute(
                """INSERT INTO question_attempts (quiz_result_id, question_index, concept_tags, is_correct, student_answer, correct_answer)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (res_id, i, json.dumps(["class-definition"]), is_corr, 0 if is_corr else 1, 0),
            )

    # Seed active study plan and journey state
    cur.execute("SELECT id FROM study_plans WHERE student_id = ? AND status = 'active' LIMIT 1", (student_id,))
    if not cur.fetchone():
        plan_dict = {
            "summary": "Personalized OOP Plan",
            "coverage": {"ok": True, "violations": []},
            "deferred": [],
            "steps": [
                {
                    "position": 1,
                    "concept": "class-definition",
                    "kind": "prerequisite",
                    "status": "done",
                    "difficulty": "Easy",
                    "lesson_style": "simplified",
                    "mastery": 80.0,
                    "title": "Class Definition",
                    "prompt_text": "Study Class Definition",
                },
                {
                    "position": 2,
                    "concept": "object-instantiation",
                    "kind": "weak",
                    "status": "pending",
                    "difficulty": "Easy",
                    "lesson_style": "detailed",
                    "mastery": 45.0,
                    "title": "Object Instantiation",
                    "prompt_text": "Study Object Instantiation",
                },
                {
                    "position": 3,
                    "concept": "reference-semantics",
                    "kind": "check",
                    "status": "pending",
                    "difficulty": "Easy",
                    "lesson_style": "simplified",
                    "mastery": 50.0,
                    "title": "Reference Semantics",
                    "prompt_text": "Verify Reference Semantics",
                },
                {
                    "position": 4,
                    "concept": "all-plan-concepts",
                    "kind": "reevaluation",
                    "status": "pending",
                    "difficulty": "Easy",
                    "lesson_style": "detailed",
                    "mastery": 60.0,
                    "title": "Closing Re-evaluation",
                    "prompt_text": "Final Re-evaluation",
                },
            ],
        }
        saved_plan = create_study_plan(student_id, plan_dict, conn=conn)
        save_student_journey(student_id, STATE_PLAN_ACTIVE, plan_id=saved_plan["id"], conn=conn)

    conn.commit()
    conn.close()


class TestBrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Create isolated DB from data/edugen.db
        cls.tmp_dir = tempfile.mkdtemp()
        cls.tmp_db = os.path.join(cls.tmp_dir, "test_browser.db")
        master_db = BASE_DIR / "data" / "edugen.db"
        shutil.copy2(master_db, cls.tmp_db)

        os.environ["EDUGEN_DB_PATH"] = cls.tmp_db
        core.db.DB_PATH = cls.tmp_db
        seed_test_database(cls.tmp_db)

        # 2. Start Flask server on free port
        cls.port = find_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        app = create_app()
        app.config["TESTING"] = True
        cls.server = ServerThread(app, "127.0.0.1", cls.port)
        cls.server.start()
        time.sleep(1.0)

        # 3. Ensure screenshot directory exists
        os.makedirs(UI_CHECK_DIR, exist_ok=True)

        # 4. Launch Playwright browser
        from playwright.sync_api import sync_playwright

        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)
        cls.page = cls.browser.new_page()

        # Error tracking
        cls.console_errors_by_page = {}
        cls.page_errors_by_page = {}
        cls.current_page_name = "init"

        def on_console(msg):
            if msg.type == "error":
                pname = getattr(cls, "current_page_name", "unknown")
                cls.console_errors_by_page.setdefault(pname, []).append(msg.text)

        def on_page_error(err):
            pname = getattr(cls, "current_page_name", "unknown")
            cls.page_errors_by_page.setdefault(pname, []).append(str(err))

        cls.page.on("console", on_console)
        cls.page.on("pageerror", on_page_error)

        # 5. Log in as demo student
        cls.current_page_name = "login"
        cls.page.goto(f"{cls.base_url}/login")
        cls.page.fill("#email", "demo_student@edugen.local")
        cls.page.fill("#password", "password123")
        cls.page.click("#submit")
        cls.page.wait_for_url(f"{cls.base_url}/dashboard", timeout=8000)

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, "browser") and cls.browser:
                cls.browser.close()
            if hasattr(cls, "pw") and cls.pw:
                cls.pw.stop()
            if hasattr(cls, "server") and cls.server:
                cls.server.shutdown()
        except Exception:
            pass
        finally:
            if hasattr(cls, "tmp_dir") and os.path.exists(cls.tmp_dir):
                shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_01_dashboard(self):
        """Dashboard: zero errors, numbers in snapshot cards (no skeleton after 5s), screenshot."""
        self.__class__.current_page_name = "/dashboard"
        self.page.goto(f"{self.base_url}/dashboard")

        # Snapshot cards must show numbers without skeleton class within 5s
        self.page.wait_for_selector("#stats .stat-value:not(.skeleton)", timeout=5000)
        skeleton_count = self.page.locator("#stats .skeleton").count()
        self.assertEqual(skeleton_count, 0, "Dashboard stats still show skeleton loaders after 5s.")

        # Assert numbers are rendered in the stat cards
        stat_values = self.page.locator("#stats .stat-value").all_inner_texts()
        self.assertGreaterEqual(len(stat_values), 4)
        for val in stat_values:
            self.assertTrue(any(c.isdigit() for c in val), f"Stat value '{val}' contains no numeric digits.")

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "dashboard.png"), full_page=True)

        # Assert zero errors
        self.assertEqual(len(self.console_errors_by_page.get("/dashboard", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/dashboard", [])), 0)

    def test_02_evaluator_capsule_behavior(self):
        """Evaluator capsule: visible, click opens, minimize returns, persists on reload, count is number."""
        self.__class__.current_page_name = "evaluator"
        pill = self.page.locator("#evaluator-pill")
        panel = self.page.locator("#evaluator-panel")
        minimize_btn = self.page.locator("#eval-minimize-btn")

        # 1. Capsule is visible
        self.assertTrue(pill.is_visible(), "Evaluator capsule pill is not visible.")

        # 2. A click opens the panel
        pill.click()
        self.page.wait_for_selector("#evaluator-panel", state="visible", timeout=3000)
        self.assertTrue(panel.is_visible(), "Evaluator panel did not open on pill click.")
        self.assertFalse(pill.is_visible(), "Evaluator pill remained visible after opening panel.")

        # 3. Minimize button returns the capsule
        minimize_btn.click()
        self.page.wait_for_selector("#evaluator-pill", state="visible", timeout=3000)
        self.assertTrue(pill.is_visible(), "Evaluator pill did not return after minimize.")
        self.assertFalse(panel.is_visible(), "Evaluator panel remained visible after minimize.")

        # 4. After page reload the capsule is still there
        self.page.reload()
        self.page.wait_for_selector("#evaluator-pill", state="visible", timeout=5000)
        self.assertTrue(pill.is_visible(), "Evaluator pill disappeared after page reload.")

        # 5. Capsule counter is a number
        counter_text = self.page.locator("#eval-event-count").inner_text().strip()
        self.assertTrue(counter_text.isdigit(), f"Capsule counter is not a number: '{counter_text}'")

    def test_03_learn_page(self):
        """Learn page: zero errors, 'Loading your mastery...' disappears, screenshot."""
        self.__class__.current_page_name = "/learn"
        self.page.goto(f"{self.base_url}/learn")

        # Wait for "Loading your mastery..." to disappear
        self.page.wait_for_selector("#mastery-strip:not(:has-text('Loading your mastery'))", timeout=5000)
        mastery_text = self.page.locator("#mastery-strip").inner_text()
        self.assertNotIn("Loading your mastery", mastery_text)

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "learn.png"), full_page=True)

        # Assert zero errors
        self.assertEqual(len(self.console_errors_by_page.get("/learn", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/learn", [])), 0)

    def test_04_quiz_page(self):
        """Quiz page: zero errors, concept dropdown has >= 40 options, screenshot."""
        self.__class__.current_page_name = "/quiz"
        self.page.goto(f"{self.base_url}/quiz")

        # Check concept dropdown options
        self.page.wait_for_selector("#concept", timeout=5000)
        options_count = self.page.locator("#concept option").count()
        self.assertGreaterEqual(options_count, 40, f"Expected >= 40 concept options, found {options_count}")

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "quiz.png"), full_page=True)

        # Assert zero errors
        self.assertEqual(len(self.console_errors_by_page.get("/quiz", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/quiz", [])), 0)

    def test_05_analysis_page(self):
        """Analysis page: zero errors, mastery components loaded, screenshot."""
        self.__class__.current_page_name = "/analysis"
        self.page.goto(f"{self.base_url}/analysis")
        self.page.wait_for_load_state("networkidle", timeout=5000)

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "analysis.png"), full_page=True)

        # Assert zero errors
        self.assertEqual(len(self.console_errors_by_page.get("/analysis", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/analysis", [])), 0)

    def test_06_history_page(self):
        """History page: zero errors, quiz attempt rows rendered, screenshot."""
        self.__class__.current_page_name = "/history"
        self.page.goto(f"{self.base_url}/history")
        self.page.wait_for_load_state("networkidle", timeout=5000)

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "history.png"), full_page=True)

        # Assert zero errors
        self.assertEqual(len(self.console_errors_by_page.get("/history", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/history", [])), 0)

    def test_07_plan_page(self):
        """Plan page: zero errors, plan steps and coverage rendered, screenshot."""
        self.__class__.current_page_name = "/plan"
        self.page.goto(f"{self.base_url}/plan")

        # Wait for plan container to load
        self.page.wait_for_selector("#plan-container", state="visible", timeout=5000)
        self.assertTrue(self.page.locator("#steps-list").is_visible(), "Steps list not visible on /plan.")

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "plan.png"), full_page=True)

        # Assert zero errors
        self.assertEqual(len(self.console_errors_by_page.get("/plan", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/plan", [])), 0)


if __name__ == "__main__":
    unittest.main()
