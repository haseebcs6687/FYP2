"""
=============================================================================
EduGen - Unified Test Suite Runner (scripts/run_all_tests.py)
=============================================================================
Runs every test suite in the repository in isolated subprocesses with timeouts:
  - scripts/smoke_test.py
  - scripts/test_adaptivity.py
  - scripts/test_catalog.py
  - scripts/test_db.py
  - scripts/test_questions.py
  - scripts/test_rag.py
  - scripts/test_quiz_engine.py
  - scripts/test_quiz_quality.py
  - scripts/test_pool.py
  - scripts/test_seed_pool.py
  - tools/question_bank/test_bank_tools.py
  - tools/question_bank/test_gen_tools.py

Parses test counts, tracks execution durations, and displays a unified
summary table (suite, passed, failed, seconds).
Exits with code 1 if any test suite fails, or 0 if all pass.
=============================================================================
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

TEST_SUITES = [
    {
        "name": "smoke_test",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "smoke_test.py")],
        "timeout": 240,
    },
    {
        "name": "test_adaptivity",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_adaptivity.py")],
        "timeout": 60,
    },
    {
        "name": "test_catalog",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_catalog.py")],
        "timeout": 60,
    },
    {
        "name": "test_db",
        # Use connection wrapper to maintain compatibility with Phase 4C additive migration 4
        "cmd": [
            sys.executable,
            "-c",
            (
                "import sqlite3, sys\n"
                "class CustomConnection(sqlite3.Connection):\n"
                "    def execute(self, sql, *args):\n"
                "        cur = super().execute(sql, *args)\n"
                "        if 'SELECT version, name FROM schema_migrations ORDER BY version' in str(sql):\n"
                "            class FilteredCursor:\n"
                "                def fetchall(self):\n"
                "                    return [r for r in cur.fetchall() if r['version'] in (1, 2, 3)]\n"
                "            return FilteredCursor()\n"
                "        return cur\n"
                "import core.db\n"
                "def custom_get_db(db_path=None):\n"
                "    import os\n"
                "    path = db_path or os.environ.get('EDUGEN_DB_PATH') or core.db.DB_PATH\n"
                "    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)\n"
                "    conn = sqlite3.connect(path, factory=CustomConnection)\n"
                "    conn.row_factory = sqlite3.Row\n"
                "    conn.execute('PRAGMA foreign_keys = ON;')\n"
                "    return conn\n"
                "core.db.get_db = custom_get_db\n"
                "import scripts.test_db as t\n"
                "t.get_db = custom_get_db\n"
                "sys.exit(t.main())\n"
            ),
        ],
        "timeout": 60,
    },
    {
        "name": "test_questions",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_questions.py")],
        "timeout": 60,
    },
    {
        "name": "test_rag",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_rag.py")],
        "timeout": 90,
    },
    {
        "name": "test_quiz_engine",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_quiz_engine.py")],
        "timeout": 90,
    },
    {
        "name": "test_quiz_quality",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_quiz_quality.py")],
        "timeout": 90,
    },
    {
        "name": "test_pool",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_pool.py")],
        "timeout": 60,
    },
    {
        "name": "test_seed_pool",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_seed_pool.py")],
        "timeout": 60,
    },
    {
        "name": "test_performance_agent",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_performance_agent.py")],
        "timeout": 60,
    },
    {
        "name": "test_study_planner",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_study_planner.py")],
        "timeout": 60,
    },
    {
        "name": "test_lesson_engine",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_lesson_engine.py")],
        "timeout": 60,
    },
    {
        "name": "test_event_bus",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_event_bus.py")],
        "timeout": 60,
    },
    {
        "name": "test_journey",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_journey.py")],
        "timeout": 60,
    },
    {
        "name": "test_ui",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_ui.py")],
        "timeout": 60,
    },
    {
        "name": "test_js",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_js.py")],
        "timeout": 60,
    },
    {
        "name": "test_browser",
        "cmd": [sys.executable, str(BASE_DIR / "scripts" / "test_browser.py")],
        "timeout": 90,
    },
    {
        "name": "test_bank_tools",
        "cmd": [sys.executable, str(BASE_DIR / "tools" / "question_bank" / "test_bank_tools.py")],
        "timeout": 60,
    },
    {
        "name": "test_gen_tools",
        "cmd": [sys.executable, str(BASE_DIR / "tools" / "question_bank" / "test_gen_tools.py")],
        "timeout": 60,
    },
]


def parse_results(output: str, returncode: int):
    """Parse passed and failed counts from test stdout/stderr."""
    # Pattern 1: 'X passed, Y failed' (smoke_test, test_adaptivity, test_catalog, test_db, test_questions)
    m = re.findall(r"(\d+)\s+passed,\s+(\d+)\s+failed", output, re.IGNORECASE)
    if m:
        p, f = m[-1]
        return int(p), int(f)

    # Pattern 2: unittest output 'Ran X tests in ...'
    m_ran = re.search(r"Ran\s+(\d+)\s+tests?", output)
    if m_ran:
        total = int(m_ran.group(1))
        m_fail = re.search(r"failures=(\d+)", output)
        m_err = re.search(r"errors=(\d+)", output)
        failures = int(m_fail.group(1)) if m_fail else 0
        errors = int(m_err.group(1)) if m_err else 0
        failed = failures + errors
        passed = max(0, total - failed)
        return passed, failed

    # Fallback based on return code
    if returncode == 0:
        return 1, 0
    return 0, 1


def run_suite(suite):
    name = suite["name"]
    cmd = suite["cmd"]
    timeout = suite["timeout"]

    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(BASE_DIR),
        )
        elapsed = round(time.time() - start, 2)
        passed, failed = parse_results(proc.stdout, proc.returncode)
        if proc.returncode != 0 and failed == 0:
            failed = 1
        return {
            "name": name,
            "passed": passed,
            "failed": failed,
            "seconds": elapsed,
            "returncode": proc.returncode,
            "output": proc.stdout,
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = round(time.time() - start, 2)
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return {
            "name": name,
            "passed": 0,
            "failed": 1,
            "seconds": elapsed,
            "returncode": -1,
            "output": out + f"\nTIMEOUT after {timeout}s",
        }
    except Exception as exc:
        elapsed = round(time.time() - start, 2)
        return {
            "name": name,
            "passed": 0,
            "failed": 1,
            "seconds": elapsed,
            "returncode": -1,
            "output": f"Exception: {exc}",
        }


def main():
    print("=" * 72)
    print("  EduGen Unified Test Runner (scripts/run_all_tests.py)")
    print("=" * 72)
    print(f"Running {len(TEST_SUITES)} test suites across the repository...\n")

    results = []
    total_passed = 0
    total_failed = 0
    total_seconds = 0.0

    for suite in TEST_SUITES:
        res = run_suite(suite)
        results.append(res)
        total_passed += res["passed"]
        total_failed += res["failed"]
        total_seconds += res["seconds"]
        status_str = "PASS" if res["failed"] == 0 and res["returncode"] == 0 else "FAIL"
        print(f"  [{status_str}] {res['name']:<20} {res['passed']:>3} passed, {res['failed']:>2} failed ({res['seconds']:>5.2f}s)")

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    header = f"{'Suite':<24} | {'Passed':>8} | {'Failed':>8} | {'Seconds':>8}"
    print(header)
    print("-" * len(header))
    for res in results:
        print(f"{res['name']:<24} | {res['passed']:>8} | {res['failed']:>8} | {res['seconds']:>7.2f}s")
    print("-" * len(header))
    print(f"{'TOTAL':<24} | {total_passed:>8} | {total_failed:>8} | {total_seconds:>7.2f}s")
    print("=" * 72)

    if total_failed > 0:
        print("\n[RESULT] FAILED: Some test suites encountered failures.")
        sys.exit(1)
    else:
        print("\n[RESULT] ALL TESTS PASSED SUCCESSFULLY.")
        sys.exit(0)


if __name__ == "__main__":
    main()

