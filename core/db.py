"""
=============================================================================
EduGen - Database Layer
=============================================================================
SQLite schema, connection helper and forward migrations.

FYP-1 tables (users, students, quiz_results, question_attempts) are preserved
so an existing data/edugen.db keeps working. FYP-2 adds:

  quiz_sessions   - stores LLM-generated quizzes server-side so they can be
                    graded on submit (FYP-1 could not grade generated quizzes)
  recommendations - audit trail of every Adaptive Content Agent decision and
                    whether the student accepted or overrode it
  lesson_views    - which lessons were actually read, used as an adaptivity
                    signal by the Adaptive Content Agent
=============================================================================
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("EDUGEN_DB_PATH") or os.path.join(DATA_DIR, "edugen.db")


def get_db(db_path=None):
    """Open a connection with dict-like rows and pragmas enabled."""
    path = db_path or os.environ.get("EDUGEN_DB_PATH") or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _columns(cursor, table):
    try:
        cursor.execute("PRAGMA table_info(%s)" % table)
        return {row[1] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        return set()


def _add_column(cursor, table, column, ddl):
    if column not in _columns(cursor, table):
        try:
            cursor.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, ddl))
        except sqlite3.OperationalError:
            pass


def init_db(db_path=None):
    """Create tables if missing and run forward migrations. Safe to re-run."""
    from core.migrations import run_migrations
    path = db_path or DB_PATH
    run_migrations(path, get_db)
    return path


def query_all(sql, params=(), db_path=None):
    conn = get_db(db_path)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def query_one(sql, params=(), db_path=None):
    conn = get_db(db_path)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def execute(sql, params=(), db_path=None):
    conn = get_db(db_path)
    cur = conn.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id
