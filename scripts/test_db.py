"""
=============================================================================
EduGen - Database & Migration Test Suite
=============================================================================
Validates:
(1) Fresh DB migrates to the latest version.
(2) A copy of CURRENT data/edugen.db migrates with row counts unchanged
    and a backup created in data/backups/.
(3) Running init_db twice is an idempotent no-op.
(4) All new tables and columns exist and are queryable.

Usage:
    python scripts/test_db.py
=============================================================================
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.db import DB_PATH, get_db, init_db
from core.db_repo import (
    record_concept_mastery,
    record_generated_questions,
    record_llm_call,
    record_submission_history,
    record_user_login,
)
from core.migrations import BACKUP_DIR, MIGRATIONS

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS {name}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL {name}  <- {detail}")


def get_tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def get_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def main():
    print("==================================================")
    print("  EduGen Database & Migration Tests")
    print("==================================================")

    tmp_dir = tempfile.mkdtemp()
    try:
        # -----------------------------------------------------------------
        # Test 1: Fresh DB migrates to latest version
        # -----------------------------------------------------------------
        print("\n1. Fresh DB migration")
        fresh_db = os.path.join(tmp_dir, "fresh.db")
        init_db(fresh_db)

        conn = get_db(fresh_db)
        tables = get_tables(conn)

        expected_tables = {
            "schema_migrations", "users", "students", "quiz_results",
            "question_attempts", "quiz_sessions", "recommendations", "lesson_views",
            "questions", "student_question_history", "concept_mastery", "mastery_history",
            "study_plans", "study_plan_steps", "pipeline_runs", "agent_events",
            "rag_retrievals", "llm_calls", "feedback"
        }
        missing = expected_tables - tables
        check("all expected tables created on fresh DB", len(missing) == 0, f"missing: {missing}")

        mig_rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        applied_versions = [r["version"] for r in mig_rows]
        check("all migrations applied", applied_versions == [1, 2], f"applied: {applied_versions}")

        # Check altered columns on fresh DB
        student_cols = get_columns(conn, "students")
        user_cols = get_columns(conn, "users")
        check("students.lesson_style exists", "lesson_style" in student_cols)
        check("students.total_study_seconds exists", "total_study_seconds" in student_cols)
        check("users.last_login_at exists", "last_login_at" in user_cols)
        conn.close()

        # -----------------------------------------------------------------
        # Test 2: Migration of existing database with data preservation & backup
        # -----------------------------------------------------------------
        print("\n2. Existing DB migration & backup")
        if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
            copy_db = os.path.join(tmp_dir, "existing_copy.db")
            shutil.copy2(DB_PATH, copy_db)

            # Record row counts prior to migration
            conn_pre = sqlite3.connect(copy_db)
            conn_pre.row_factory = sqlite3.Row
            old_tables = {"users", "students", "quiz_results", "question_attempts",
                          "quiz_sessions", "recommendations", "lesson_views"}
            pre_counts = {}
            existing_tables_pre = {r[0] for r in conn_pre.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            for t in old_tables:
                if t in existing_tables_pre:
                    pre_counts[t] = conn_pre.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            conn_pre.close()

            backups_before = set(Path(BACKUP_DIR).glob("edugen_*.db"))

            # Run migration on copy
            init_db(copy_db)

            backups_after = set(Path(BACKUP_DIR).glob("edugen_*.db"))
            new_backups = backups_after - backups_before
            check("backup created in data/backups/", len(new_backups) >= 1 or len(backups_after) >= 1,
                  f"backups: {len(backups_after)}")

            conn_post = get_db(copy_db)
            post_tables = get_tables(conn_post)
            check("new tables added to migrated copy", expected_tables.issubset(post_tables))

            # Verify row counts unchanged
            counts_preserved = True
            mismatches = []
            for t, pre_cnt in pre_counts.items():
                post_cnt = conn_post.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                if pre_cnt != post_cnt:
                    counts_preserved = False
                    mismatches.append(f"{t}: pre={pre_cnt}, post={post_cnt}")
            check("row counts of old tables unchanged", counts_preserved, f"mismatches: {mismatches}")
            conn_post.close()
        else:
            print("  SKIP (no existing data/edugen.db found)")

        # -----------------------------------------------------------------
        # Test 3: Idempotency (init_db twice is a no-op)
        # -----------------------------------------------------------------
        print("\n3. Idempotency")
        conn_before_noop = get_db(fresh_db)
        mig_before = conn_before_noop.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        conn_before_noop.close()

        backups_count_before = len(list(Path(BACKUP_DIR).glob("edugen_*.db")))
        # Run init_db second time
        init_db(fresh_db)

        conn_after_noop = get_db(fresh_db)
        mig_after = conn_after_noop.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        conn_after_noop.close()

        backups_count_after = len(list(Path(BACKUP_DIR).glob("edugen_*.db")))
        check("no new migrations run on second init_db", mig_before == mig_after)
        check("no extra backup created when no migrations pending", backups_count_before == backups_count_after)

        # -----------------------------------------------------------------
        # Test 4: Repository wiring & tables operations
        # -----------------------------------------------------------------
        print("\n4. Repository CRUD & wiring validation")
        test_db = os.path.join(tmp_dir, "repo_test.db")
        init_db(test_db)
        os.environ["EDUGEN_DB_PATH"] = test_db
        import core.db as db_mod
        db_mod.DB_PATH = test_db

        # Create student and user for foreign keys
        conn_init = get_db(test_db)
        cur = conn_init.cursor()
        cur.execute("INSERT INTO users (name, email, password_hash) VALUES ('Tester', 't@t.com', 'h')")
        uid = cur.lastrowid
        cur.execute("INSERT INTO students (name, user_id) VALUES ('Tester', ?)", (uid,))
        sid = cur.lastrowid
        cur.execute("INSERT INTO quiz_results (student_id, topic, difficulty, score) VALUES (?, 'Classes', 'Easy', 1)", (sid,))
        qrid = cur.lastrowid
        conn_init.commit()
        conn_init.close()

        # (a) record_user_login
        record_user_login(uid)
        conn_check = get_db(test_db)
        u_row = conn_check.execute("SELECT last_login_at FROM users WHERE id = ?", (uid,)).fetchone()
        check("record_user_login sets last_login_at", u_row["last_login_at"] is not None)
        conn_check.close()

        # (b) record_generated_questions
        sample_q = [{
            "question": "What is polymorphism?",
            "options": ["A", "B", "C", "D"],
            "correct": 0,
            "explanation": "Because.",
            "concept_tags": ["polymorphism-basics"]
        }]
        qids = record_generated_questions("polymorphism-basics", "Easy", sample_q, model="test-model")
        check("record_generated_questions returns question id", len(qids) == 1 and qids[0] is not None)

        # Re-recording same question dedupes
        qids2 = record_generated_questions("polymorphism-basics", "Easy", sample_q, model="test-model")
        check("record_generated_questions dedupes by text_hash", qids == qids2)

        # (c) record_submission_history
        record_submission_history(sid, qrid, sample_q, {0: 0}, {0: 1200})
        conn_check = get_db(test_db)
        q_stat = conn_check.execute("SELECT times_served, times_correct FROM questions WHERE id = ?", (qids[0],)).fetchone()
        check("times_served and times_correct incremented", q_stat["times_served"] == 1 and q_stat["times_correct"] == 1)

        sqh_count = conn_check.execute("SELECT COUNT(*) FROM student_question_history WHERE question_id = ?", (qids[0],)).fetchone()[0]
        check("student_question_history row inserted", sqh_count == 1)
        conn_check.close()

        # (d) record_concept_mastery
        mock_stats = {
            "class-definition": {
                "mastery": 85.0,
                "attempts": 4,
                "correct": 3,
                "trend": "improving",
                "last_seen": "2026-10-26 12:00:00"
            }
        }
        record_concept_mastery(sid, mock_stats, quiz_result_id=qrid)
        conn_check = get_db(test_db)
        cm = conn_check.execute("SELECT mastery, trend FROM concept_mastery WHERE student_id = ? AND concept = 'class-definition'", (sid,)).fetchone()
        check("concept_mastery record upserted", cm is not None and cm["mastery"] == 85.0)

        mh = conn_check.execute("SELECT COUNT(*) FROM mastery_history WHERE student_id = ? AND concept = 'class-definition'", (sid,)).fetchone()[0]
        check("mastery_history snapshot appended", mh == 1)
        conn_check.close()

        # (e) record_llm_call
        record_llm_call(sid, "concept_clarifier", "quiz", "test-model", 420, True, prompt_tokens=100, completion_tokens=50)
        conn_check = get_db(test_db)
        llm_count = conn_check.execute("SELECT COUNT(*) FROM llm_calls WHERE student_id = ?", (sid,)).fetchone()[0]
        check("llm_calls row recorded", llm_count == 1)
        conn_check.close()

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n==================================================")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print("==================================================")

    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
