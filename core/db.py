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
    """Open a connection with dict-like rows and foreign keys enabled."""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
    conn = get_db(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            user_id    INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _add_column(cur, "students", "user_id", "INTEGER")
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_students_user_id
        ON students(user_id) WHERE user_id IS NOT NULL
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS quiz_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id      INTEGER NOT NULL,
            topic           TEXT NOT NULL,
            difficulty      TEXT NOT NULL,
            score           INTEGER NOT NULL,
            total_questions INTEGER NOT NULL DEFAULT 5,
            attempt_number  INTEGER NOT NULL DEFAULT 1,
            timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    # FYP-2: remember which concept the quiz targeted and where it came from
    _add_column(cur, "quiz_results", "concept", "TEXT")
    _add_column(cur, "quiz_results", "source", "TEXT DEFAULT 'bank'")
    _add_column(cur, "quiz_results", "duration_ms", "INTEGER DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS question_attempts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_result_id INTEGER NOT NULL,
            question_index INTEGER NOT NULL,
            concept_tags   TEXT NOT NULL,
            is_correct     INTEGER NOT NULL,
            student_answer INTEGER NOT NULL,
            correct_answer INTEGER NOT NULL,
            FOREIGN KEY (quiz_result_id) REFERENCES quiz_results(id)
        )
    """)
    # FYP-2 adaptivity signals beyond right/wrong
    _add_column(cur, "question_attempts", "time_taken_ms", "INTEGER DEFAULT 0")
    _add_column(cur, "question_attempts", "question_text", "TEXT")
    _add_column(cur, "question_attempts", "chosen_option_text", "TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   INTEGER NOT NULL,
            concept      TEXT,
            topic        TEXT,
            difficulty   TEXT NOT NULL,
            source       TEXT NOT NULL DEFAULT 'bank',
            payload_json TEXT NOT NULL,
            consumed     INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id       INTEGER NOT NULL,
            focus_concept    TEXT,
            difficulty       TEXT,
            action           TEXT,
            reasoning        TEXT,
            accepted         INTEGER,
            final_concept    TEXT,
            final_difficulty TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lesson_views (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            concept    TEXT NOT NULL,
            difficulty TEXT,
            source     TEXT,
            viewed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_qr_student ON quiz_results(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_result ON question_attempts(quiz_result_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rec_student ON recommendations(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lv_student ON lesson_views(student_id)")

    conn.commit()
    conn.close()
    return DB_PATH


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
