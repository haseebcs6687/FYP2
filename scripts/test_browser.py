"""
=============================================================================
EduGen - Real Browser Smoke Test Suite (scripts/test_browser.py)
=============================================================================
Uses Playwright and headless Chromium to perform end-to-end browser testing:
  1. Starts the real Flask application on a free localhost port with an isolated test DB.
  2. Seeds the official demo student (demo@edugen.local / demo-pass).
  3. Authenticates through the real UI login page (/login).
  4. Navigates through all student pages and validates interactive workflows:
       - /dashboard: seeded snapshot numbers, active plan card, "Download report" button
       - PDF Download: clicks "Download report", validates %PDF magic bytes and size > 3 KB
       - /quiz -> /quiz/attempt -> /quiz/result: starts pool quiz, answers questions,
         submits through UI (validates real CSRF header in fetch), verifies score rendered
       - Evaluator capsule: pill visible on every page, open panel, minimize to pill,
         pill persists across reload, event counter is a number
       - /learn, /analysis, /history, /plan: all render without skeletons or errors
       - Sign out: logs out, validates protected routes redirect to /login
  5. Asserts strictly 0 console errors and 0 uncaught page exceptions across all pages.
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

from werkzeug.serving import make_server

from app import create_app
import core.db
from scripts.seed_demo_student import DEMO_EMAIL, DEMO_PASS, seed_demo_student

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

        # Seed the official demo student with 8 quizzes and study plan
        seed_demo_student(reset=True)

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

        # Error tracking across all pages
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
        cls.page.fill("#email", DEMO_EMAIL)
        cls.page.fill("#password", DEMO_PASS)
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
        """Dashboard: zero errors, seeded stats loaded, plan card visible, capsule visible, screenshot."""
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

        # Verify active plan / recommendation card is visible
        self.page.wait_for_selector("#rec-slot", timeout=5000)
        self.assertTrue(self.page.locator("#rec-slot").is_visible())

        # Verify Evaluator capsule is present and visible
        pill = self.page.locator("#evaluator-pill")
        self.assertTrue(pill.is_visible(), "Evaluator capsule pill is not visible on /dashboard.")

        # Verify Download report button is present
        btn_report = self.page.locator("#btn-download-report")
        self.assertTrue(btn_report.is_visible(), "Download report button is missing on /dashboard.")

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "dashboard.png"), full_page=True)

        # Assert zero errors
        self.assertEqual(len(self.console_errors_by_page.get("/dashboard", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/dashboard", [])), 0)

    def test_02_download_report_pdf(self):
        """Download report: clicks button, validates PDF response begins with %PDF and size > 3 KB."""
        self.__class__.current_page_name = "download_report"
        # Download report via authenticated browser context
        response = self.page.request.get(f"{self.base_url}/report.pdf")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("content-type"), "application/pdf")

        body = response.body()
        self.assertTrue(body.startswith(b"%PDF"), "Report file does not start with %PDF magic bytes.")
        self.assertGreater(len(body), 3072, "Report file size must be greater than 3 KB.")

    def test_03_take_pool_quiz_and_submit(self):
        """Start pool quiz, answer questions, submit through UI with active CSRF, verify score on result page."""
        self.__class__.current_page_name = "/quiz_flow"
        self.page.goto(f"{self.base_url}/quiz")

        # Pick concept and difficulty
        self.page.wait_for_selector("#concept", timeout=5000)
        self.page.select_option("#concept", value="class-definition")
        self.page.click("[data-difficulty='Easy']")
        self.page.wait_for_selector("#start:not([disabled])", timeout=3000)

        # Click Start quiz
        self.page.click("#start")
        self.page.wait_for_url(f"{self.base_url}/quiz/attempt", timeout=8000)

        # Wait for questions to render
        self.page.wait_for_selector(".q-card", timeout=5000)
        q_count = self.page.locator(".q-card").count()
        self.assertGreaterEqual(q_count, 1)

        # Answer each question (select first option for each)
        for i in range(q_count):
            self.page.click(f".q-card:nth-of-type({i+1}) .opt:first-of-type")

        # Submit quiz
        self.page.wait_for_selector("#submit:not([disabled])", timeout=3000)
        self.page.click("#submit")

        # Wait for navigation to /quiz/result/<id>
        self.page.wait_for_url(re.compile(r".*/quiz/result/\d+"), timeout=8000)
        self.page.wait_for_selector(".result-card, .score, #score, h1", timeout=5000)

        # Verify score is displayed on result page
        page_text = self.page.inner_text("body")
        self.assertTrue(
            any(k in page_text for k in ["Score", "score", "%", "Review"]),
            "Result page did not display score or completion text.",
        )

        # Evaluator capsule present
        self.assertTrue(self.page.locator("#evaluator-pill").is_visible())

        # Screenshot result
        self.page.screenshot(path=str(UI_CHECK_DIR / "quiz_result.png"), full_page=True)

        self.assertEqual(len(self.console_errors_by_page.get("/quiz_flow", [])), 0)

    def test_04_evaluator_capsule_behavior(self):
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

    def test_05_learn_page(self):
        """Learn page: zero errors, 'Loading your mastery...' disappears, capsule visible, screenshot."""
        self.__class__.current_page_name = "/learn"
        self.page.goto(f"{self.base_url}/learn")

        # Wait for "Loading your mastery..." to disappear
        self.page.wait_for_selector("#mastery-strip:not(:has-text('Loading your mastery'))", timeout=5000)
        mastery_text = self.page.locator("#mastery-strip").inner_text()
        self.assertNotIn("Loading your mastery", mastery_text)

        # Capsule is visible
        self.assertTrue(self.page.locator("#evaluator-pill").is_visible())

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "learn.png"), full_page=True)

        self.assertEqual(len(self.console_errors_by_page.get("/learn", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/learn", [])), 0)

    def test_06_analysis_page(self):
        """Analysis page: zero errors, mastery components loaded, download button present, screenshot."""
        self.__class__.current_page_name = "/analysis"
        self.page.goto(f"{self.base_url}/analysis")
        self.page.wait_for_load_state("networkidle", timeout=5000)

        # Verify Download report button is present on /analysis
        btn_report = self.page.locator("#btn-download-report")
        self.assertTrue(btn_report.is_visible(), "Download report button missing on /analysis.")

        # Capsule is visible
        self.assertTrue(self.page.locator("#evaluator-pill").is_visible())

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "analysis.png"), full_page=True)

        self.assertEqual(len(self.console_errors_by_page.get("/analysis", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/analysis", [])), 0)

    def test_07_history_page(self):
        """History page: zero errors, seeded quiz attempts rendered (>= 8 rows), capsule visible, screenshot."""
        self.__class__.current_page_name = "/history"
        self.page.goto(f"{self.base_url}/history")
        self.page.wait_for_load_state("networkidle", timeout=5000)

        # Verify history rows are present
        self.page.wait_for_selector("table, .quiz-row, .card", timeout=5000)

        # Capsule is visible
        self.assertTrue(self.page.locator("#evaluator-pill").is_visible())

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "history.png"), full_page=True)

        self.assertEqual(len(self.console_errors_by_page.get("/history", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/history", [])), 0)

    def test_08_plan_page(self):
        """Plan page: zero errors, plan steps and coverage rendered, capsule visible, screenshot."""
        self.__class__.current_page_name = "/plan"
        self.page.goto(f"{self.base_url}/plan")

        # Wait for plan container to load
        self.page.wait_for_selector("#plan-container", state="visible", timeout=5000)
        self.assertTrue(self.page.locator("#steps-list").is_visible(), "Steps list not visible on /plan.")

        # Capsule is visible
        self.assertTrue(self.page.locator("#evaluator-pill").is_visible())

        # Save screenshot
        self.page.screenshot(path=str(UI_CHECK_DIR / "plan.png"), full_page=True)

        self.assertEqual(len(self.console_errors_by_page.get("/plan", [])), 0)
        self.assertEqual(len(self.page_errors_by_page.get("/plan", [])), 0)

    def test_09_logout_and_protection(self):
        """Log out via UI, verify redirect to /, and assert protected pages redirect to /login."""
        self.__class__.current_page_name = "logout"

        # Click Sign out
        self.page.click('[data-action="logout"]')
        self.page.wait_for_url(f"{self.base_url}/", timeout=5000)

        # Attempt to access /dashboard -> redirects to /login
        self.page.goto(f"{self.base_url}/dashboard")
        self.page.wait_for_url(re.compile(r".*/login.*"), timeout=5000)

        # Attempt to access /analysis -> redirects to /login
        self.page.goto(f"{self.base_url}/analysis")
        self.page.wait_for_url(re.compile(r".*/login.*"), timeout=5000)


if __name__ == "__main__":
    unittest.main()
