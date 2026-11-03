"""
=============================================================================
EduGen - Event Bus Test Suite (scripts/test_event_bus.py)
=============================================================================
Hermetic tests covering:
  - Payload sanitization and truncation (strings <= 200, lists <= 20)
  - Ambient pipeline_run contextvars tagging (including add_log integration)
  - Background thread context propagation
  - Persistence gating (on when student_id/run_id present, off otherwise)
  - In-memory ring buffer compatibility with legacy /api/logs console
  - Retention policy (purge > 14 days, cap at 5000 per student)
  - /api/events ownership and since_id paging
  - /api/runs recent listing and /api/runs/<id> detail
=============================================================================
"""

from datetime import datetime, timedelta
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
from core.agent_log import add_log, clear_logs, get_logs
from core.db import init_db
from core.event_bus import (
    cleanup_old_events,
    emit,
    pipeline_run,
    run_in_thread_with_context,
    sanitize_summary,
)


class TestEventBus(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_events.db")
        os.environ["EDUGEN_DB_PATH"] = self.db_path
        init_db(self.db_path)
        clear_logs()

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test-secret"
        self.client = self.app.test_client()

        # Seed students
        from core.db import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, name, email, password_hash) VALUES (1, 'Alice', 'alice@edugen.edu', 'hash1')")
        cur.execute("INSERT INTO users (id, name, email, password_hash) VALUES (2, 'Bob', 'bob@edugen.edu', 'hash2')")
        cur.execute("INSERT INTO students (id, user_id, name) VALUES (1, 1, 'Alice')")
        cur.execute("INSERT INTO students (id, user_id, name) VALUES (2, 2, 'Bob')")
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass
        os.environ.pop("EDUGEN_DB_PATH", None)

    # 1. Sanitization & Truncation
    def test_emit_truncation_and_sanitizing(self):
        long_str = "x" * 500
        long_list = list(range(100))
        big_dict = {"lesson": "very long lesson text " * 50, "concept": "method-overriding", "count": 42}

        clean = sanitize_summary({
            "text": long_str,
            "items": long_list,
            "data": big_dict,
        })

        self.assertEqual(len(clean["text"]), 200)
        self.assertEqual(len(clean["items"]), 20)
        self.assertTrue(clean["data"]["lesson"].endswith("..."))
        self.assertEqual(clean["data"]["concept"], "method-overriding")
        self.assertEqual(clean["data"]["count"], 42)

        # Test emit with level normalization
        ev = emit("Coordinator", "test_action", "Message", level="WARNING", input=long_str)
        self.assertEqual(ev["level"], "warn")
        self.assertEqual(len(ev["input"]), 200)

    # 2. Pipeline run context tagging & add_log integration
    def test_pipeline_run_context_tagging(self):
        student_id = 1
        with pipeline_run(student_id=student_id, trigger="unit_test") as run_id:
            self.assertIsNotNone(run_id)

            # Direct emit inside context
            e1 = emit("Adaptive Content", "test_step", "Inside run")
            self.assertEqual(e1["run_id"], run_id)
            self.assertEqual(e1["student_id"], student_id)

            # add_log call inside context
            e2 = add_log("Performance Analysis", "Analysis ran inside pipeline", "info", {"stat": 99})
            self.assertEqual(e2["run_id"], run_id)
            self.assertEqual(e2["student_id"], student_id)

        # Outside context, ambient values are reset
        e3 = emit("Coordinator", "outside_run", "Outside")
        self.assertIsNone(e3["run_id"])
        self.assertIsNone(e3["student_id"])

        # Check DB pipeline_runs table
        from core.db import get_db
        conn = get_db()
        row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["trigger"], "unit_test")

    # 3. Background thread context propagation
    def test_background_thread_context_copy(self):
        student_id = 1
        results = []

        def worker():
            ev = emit("Concept Clarifier", "bg_task", "Running in thread")
            results.append(ev)

        with pipeline_run(student_id=student_id, trigger="thread_test") as run_id:
            th = run_in_thread_with_context(worker)
            th.join(timeout=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["run_id"], run_id)
        self.assertEqual(results[0]["student_id"], student_id)

    # 4. Persistence gating
    def test_persistence_on_off_by_context(self):
        from core.db import get_db
        conn = get_db()
        init_count = conn.execute("SELECT COUNT(*) as n FROM agent_events").fetchone()["n"]

        # Emit without student or run -> ring buffer only, not persisted to DB
        emit("Coordinator", "ambient_off", "No student id")
        cnt1 = conn.execute("SELECT COUNT(*) as n FROM agent_events").fetchone()["n"]
        self.assertEqual(cnt1, init_count)

        # Emit with student_id -> persisted to DB
        emit("Coordinator", "ambient_on", "With student id", student_id=1)
        cnt2 = conn.execute("SELECT COUNT(*) as n FROM agent_events").fetchone()["n"]
        self.assertEqual(cnt2, init_count + 1)
        conn.close()

    # 5. Ring buffer compatibility
    def test_ring_buffer_compatibility(self):
        clear_logs()
        add_log("Coordinator", "Message 1", "info")
        add_log("Adaptive Content", "Message 2", "warning", {"key": "val"})

        logs = get_logs(after_id=0)
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["agent"], "Coordinator")
        self.assertEqual(logs[1]["type"], "warning")
        self.assertEqual(logs[1]["payload"], {"key": "val"})

        # Paging via after_id
        logs_after = get_logs(after_id=logs[0]["id"])
        self.assertEqual(len(logs_after), 1)
        self.assertEqual(logs_after[0]["id"], logs[1]["id"])

    # 6. Retention & Cleanup
    def test_retention_cleanup(self):
        from core.db import get_db
        conn = get_db()
        cur = conn.cursor()

        # Insert old event (>15 days ago)
        old_time = (datetime.now() - timedelta(days=20)).isoformat()
        cur.execute(
            """INSERT INTO agent_events (student_id, agent, action, level, message, created_at)
               VALUES (1, 'Coordinator', 'old_event', 'info', 'Expired', ?)""",
            (old_time,),
        )
        # Insert current events
        now_time = datetime.now().isoformat()
        for i in range(10):
            cur.execute(
                """INSERT INTO agent_events (student_id, agent, action, level, message, created_at)
                   VALUES (1, 'Coordinator', 'recent_event', 'info', ?, ?)""",
                (f"Recent {i}", now_time),
            )
        conn.commit()

        # Clean with max_per_student=5
        del_count = cleanup_old_events(max_days=14, max_per_student=5)
        self.assertGreaterEqual(del_count, 1)

        # Verify old was deleted and student 1 count <= 5
        rem = conn.execute("SELECT COUNT(*) as n FROM agent_events WHERE student_id = 1").fetchone()["n"]
        conn.close()
        self.assertLessEqual(rem, 5)

    # 7. /api/events ownership and since_id paging
    def test_api_events_ownership_and_paging(self):
        # Create events for student 1 and student 2
        emit("Coordinator", "e1", "Student 1 first", student_id=1)
        emit("Coordinator", "e2", "Student 2 event", student_id=2)
        emit("Coordinator", "e3", "Student 1 second", student_id=1)

        # Login as student 1 (Alice)
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["student_id"] = 1

        res = self.client.get("/api/events")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("events", data)
        self.assertIn("last_id", data)

        # Must only see student 1's events
        for ev in data["events"]:
            self.assertEqual(ev["student_id"], 1)
        self.assertEqual(len(data["events"]), 2)

        # Paging via since_id
        first_id = data["events"][0]["id"]
        res_page = self.client.get(f"/api/events?since_id={first_id}")
        page_data = res_page.get_json()
        self.assertEqual(len(page_data["events"]), 1)
        self.assertEqual(page_data["events"][0]["message"], "Student 1 second")

    # 8. /api/runs and /api/runs/<id>
    def test_api_runs_and_run_detail(self):
        student_id = 1
        with pipeline_run(student_id=student_id, trigger="route_test") as run_id:
            emit("Adaptive Content", "sub_action", "Inside run", student_id=student_id)

        # Login as student 1
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["student_id"] = 1

        res = self.client.get("/api/runs")
        self.assertEqual(res.status_code, 200)
        runs = res.get_json().get("runs", [])
        self.assertGreaterEqual(len(runs), 1)
        self.assertEqual(runs[0]["id"], run_id)
        self.assertGreaterEqual(runs[0]["event_count"], 1)

        # Detail endpoint
        res_det = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(res_det.status_code, 200)
        det_data = res_det.get_json()
        self.assertEqual(det_data["run_id"], run_id)
        self.assertGreaterEqual(len(det_data["events"]), 1)

        # Forbidden for another student (Bob, student 2)
        with self.client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["student_id"] = 2
        res_bob = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(res_bob.status_code, 404)


if __name__ == "__main__":
    unittest.main()
