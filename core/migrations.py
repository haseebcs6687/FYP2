"""
=============================================================================
EduGen - Database Migration Engine
=============================================================================
Manages forward database migrations safely and idempotently.

Rules:
- All migrations run in transactions.
- schema_migrations tracks versions applied.
- Before applying any pending migration to an existing non-empty DB,
  a copy is saved to data/backups/edugen_<timestamp>.db (last 5 kept).
- Pragmas enforced: foreign_keys=ON, journal_mode=WAL, busy_timeout=5000.
=============================================================================
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")


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


def backup_db(db_path):
    """
    Copy an existing non-empty db file to data/backups/edugen_<timestamp>.db.
    Retains only the 5 most recent backups.
    """
    if not db_path or not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_file = os.path.join(BACKUP_DIR, f"edugen_{ts}.db")
    shutil.copy2(db_path, backup_file)

    # Clean up older backups, keeping only the last 5
    backups = sorted(
        Path(BACKUP_DIR).glob("edugen_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[5:]:
        try:
            old.unlink()
        except OSError:
            pass

    return backup_file


def migration_1_initial(conn):
    """Migration 1: Base FYP-1 and FYP-2 schema."""
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


def migration_2_new_tables(conn):
    """Migration 2: Analytics, question repository, evidence tracking, and study plans."""
    cur = conn.cursor()

    # 1. questions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            concept       TEXT NOT NULL,
            difficulty    TEXT NOT NULL,
            qtype         TEXT NOT NULL DEFAULT 'concept',
            question_text TEXT NOT NULL,
            options_json  TEXT NOT NULL,
            correct_index INTEGER NOT NULL,
            explanation   TEXT,
            tags_json     TEXT,
            source        TEXT NOT NULL DEFAULT 'llm_rag',
            model         TEXT,
            verified      INTEGER DEFAULT 0,
            text_hash     TEXT UNIQUE NOT NULL,
            embedding     BLOB,
            times_served  INTEGER DEFAULT 0,
            times_correct INTEGER DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_concept ON questions(concept)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_text_hash ON questions(text_hash)")

    # 2. student_question_history
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_question_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id     INTEGER NOT NULL,
            question_id    INTEGER NOT NULL,
            quiz_result_id INTEGER,
            served_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            was_correct    INTEGER,
            chosen_index   INTEGER,
            time_taken_ms  INTEGER,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (question_id) REFERENCES questions(id),
            FOREIGN KEY (quiz_result_id) REFERENCES quiz_results(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sqh_student ON student_question_history(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sqh_question ON student_question_history(question_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sqh_result ON student_question_history(quiz_result_id)")

    # 3. concept_mastery
    cur.execute("""
        CREATE TABLE IF NOT EXISTS concept_mastery (
            student_id INTEGER NOT NULL,
            concept    TEXT NOT NULL,
            mastery    REAL NOT NULL DEFAULT 0.0,
            attempts   INTEGER NOT NULL DEFAULT 0,
            correct    INTEGER NOT NULL DEFAULT 0,
            trend      TEXT DEFAULT 'stable',
            last_seen  TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, concept),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cm_student ON concept_mastery(student_id)")

    # 4. mastery_history
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mastery_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id     INTEGER NOT NULL,
            concept        TEXT NOT NULL,
            mastery        REAL NOT NULL,
            quiz_result_id INTEGER,
            recorded_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (quiz_result_id) REFERENCES quiz_results(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mh_student_concept ON mastery_history(student_id, concept)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mh_result ON mastery_history(quiz_result_id)")

    # 5. study_plans
    cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plans (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id    INTEGER NOT NULL,
            status        TEXT NOT NULL DEFAULT 'active',
            summary       TEXT,
            analysis_json TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sp_student ON study_plans(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sp_status ON study_plans(status)")

    # 6. study_plan_steps
    cur.execute("""
        CREATE TABLE IF NOT EXISTS study_plan_steps (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id       INTEGER NOT NULL,
            position      INTEGER NOT NULL DEFAULT 1,
            concept       TEXT NOT NULL,
            difficulty    TEXT NOT NULL DEFAULT 'Easy',
            kind          TEXT NOT NULL DEFAULT 'weak',
            status        TEXT NOT NULL DEFAULT 'pending',
            reason        TEXT,
            prompt_text   TEXT,
            user_note     TEXT,
            coverage_json TEXT,
            started_at    TIMESTAMP,
            completed_at  TIMESTAMP,
            FOREIGN KEY (plan_id) REFERENCES study_plans(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sps_plan ON study_plan_steps(plan_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sps_concept ON study_plan_steps(concept)")

    # 7. pipeline_runs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL,
            trigger     TEXT NOT NULL DEFAULT 'visit',
            status      TEXT NOT NULL DEFAULT 'running',
            started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pr_student ON pipeline_runs(student_id)")

    # 8. agent_events
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER,
            student_id  INTEGER,
            agent       TEXT NOT NULL,
            action      TEXT NOT NULL,
            level       TEXT NOT NULL DEFAULT 'info',
            message     TEXT NOT NULL,
            input_json  TEXT,
            output_json TEXT,
            duration_ms INTEGER,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES pipeline_runs(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ae_run ON agent_events(run_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ae_student ON agent_events(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ae_agent ON agent_events(agent)")

    # 9. rag_retrievals
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rag_retrievals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       INTEGER,
            student_id   INTEGER,
            concept      TEXT NOT NULL,
            mode         TEXT NOT NULL DEFAULT 'lesson',
            query        TEXT NOT NULL,
            embedder     TEXT NOT NULL,
            results_json TEXT NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES pipeline_runs(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rr_run ON rag_retrievals(run_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rr_student ON rag_retrievals(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rr_concept ON rag_retrievals(concept)")

    # 10. llm_calls
    cur.execute("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id        INTEGER,
            agent             TEXT NOT NULL DEFAULT 'concept_clarifier',
            purpose           TEXT NOT NULL,
            model             TEXT NOT NULL,
            latency_ms        INTEGER NOT NULL DEFAULT 0,
            prompt_tokens     INTEGER,
            completion_tokens INTEGER,
            ok                INTEGER NOT NULL DEFAULT 1,
            error             TEXT,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_student ON llm_calls(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_agent ON llm_calls(agent)")

    # 11. feedback
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_ref  TEXT NOT NULL,
            rating      INTEGER NOT NULL,
            comment     TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fb_student ON feedback(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fb_target ON feedback(target_type, target_ref)")

    # 12. ALTER existing tables
    _add_column(cur, "students", "lesson_style", "TEXT DEFAULT 'detailed'")
    _add_column(cur, "students", "total_study_seconds", "INTEGER DEFAULT 0")
    _add_column(cur, "users", "last_login_at", "TIMESTAMP NULL")


def migration_3_misconceptions_and_facets(conn):
    """
    Migration 3: add misconception tracking columns and question facet column.
    Additive only:
      - question_attempts.misconception_id TEXT
      - student_question_history.misconception_id TEXT
      - questions.facet TEXT
    """
    cur = conn.cursor()
    _add_column(cur, "question_attempts", "misconception_id", "TEXT")
    _add_column(cur, "student_question_history", "misconception_id", "TEXT")
    _add_column(cur, "questions", "facet", "TEXT")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_facet ON questions(facet)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sqh_misconception ON student_question_history(misconception_id)")


MIGRATIONS = [
    (1, "initial_schema", migration_1_initial),
    (2, "analytics_and_evidence", migration_2_new_tables),
    (3, "misconceptions_and_facets", migration_3_misconceptions_and_facets),
]


def run_migrations(db_path, conn_factory):
    """
    Apply all pending migrations to the database.
    - If the database file exists with size > 0 and has pending migrations,
      a backup is created first.
    - Runs each migration inside an explicit transaction.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = conn_factory(db_path)

    # Ensure schema_migrations exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    applied = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }

    pending = [m for m in MIGRATIONS if m[0] not in applied]
    if not pending:
        conn.close()
        return []

    # If pending migrations exist and DB has existing data, back it up
    conn.close()
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        backup_db(db_path)

    conn = conn_factory(db_path)
    applied_now = []

    for version, name, func in pending:
        conn.execute("BEGIN IMMEDIATE")
        try:
            func(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now().isoformat()),
            )
            conn.commit()
            applied_now.append((version, name))
        except Exception:
            conn.rollback()
            conn.close()
            raise

    conn.close()
    return applied_now
