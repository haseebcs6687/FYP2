"""
=============================================================================
EduGen - Central Event Bus (core/event_bus.py)
=============================================================================
Single unified telemetry and event backbone for EduGen FYP-2:
  - Contextvars carrying ambient student_id and run_id across function calls
  - Structured emit() API with strict payload size sanitization
  - Persistence to agent_events and pipeline_runs in SQLite
  - In-memory ring buffer ensuring existing UI log polling (/api/logs) works
  - Context-propagating background thread executor
  - Event retention and cleanup helper (14 days, max 5000 per student)
=============================================================================
"""

import contextlib
from contextvars import ContextVar, copy_context
from datetime import datetime, timedelta
import json
import threading
import time
from typing import Any, Dict, List, Optional

# Context variables for ambient pipeline tracking
_current_student_id: ContextVar[Optional[int]] = ContextVar("student_id", default=None)
_current_run_id: ContextVar[Optional[int]] = ContextVar("run_id", default=None)

# Agent slug mapping for UI console
AGENTS = {
    "Coordinator": "coordinator",
    "Performance Analysis": "performance",
    "Adaptive Content": "adaptive",
    "Concept Clarifier": "clarifier",
    "Retriever": "retriever",
    "System": "system",
}

VALID_LEVELS = {"info", "success", "warn", "warning", "error", "handoff"}

# In-memory ring buffer for legacy UI console (/api/logs)
MAX_ENTRIES = 300
_lock = threading.Lock()
_ring_buffer: List[Dict[str, Any]] = []
_counter = 0

# Telemetry on persistence failures (exposed in /api/status)
_persist_failures = 0


def get_current_student_id() -> Optional[int]:
    return _current_student_id.get()


def get_current_run_id() -> Optional[int]:
    return _current_run_id.get()


def get_persist_failures() -> int:
    global _persist_failures
    with _lock:
        return _persist_failures


def reset_persist_failures() -> None:
    global _persist_failures
    with _lock:
        _persist_failures = 0


def sanitize_summary(obj: Any, depth: int = 0) -> Any:
    """
    Sanitize and truncate payloads to ensure SMALL JSON summaries:
      - Max string length: 200 characters
      - Max list items: 20 elements
      - Strips large text bodies (lesson text, question bodies, raw passages)
    """
    if depth > 4:
        return "..."
    if isinstance(obj, str):
        return obj[:200]
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, (list, tuple, set)):
        items = list(obj)[:20]
        return [sanitize_summary(x, depth + 1) for x in items]
    if isinstance(obj, dict):
        res = {}
        for k, v in list(obj.items())[:25]:
            # Suppress bulky full texts from event payloads
            if str(k).lower() in ("lesson", "body", "passage", "raw_content", "corpus", "chunks", "prompt_text", "full_text"):
                if isinstance(v, str):
                    res[k] = v[:60] + "..."
                elif isinstance(v, (list, dict)):
                    res[k] = f"<{type(v).__name__} len={len(v)}>"
                else:
                    res[k] = sanitize_summary(v, depth + 1)
            else:
                res[k] = sanitize_summary(v, depth + 1)
        return res
    return str(obj)[:200]


def emit(
    agent: str,
    action: str,
    message: str,
    level: str = "info",
    student_id: Optional[int] = None,
    run_id: Optional[int] = None,
    input: Optional[Any] = None,
    output: Optional[Any] = None,
    duration_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Emit a structured agent event:
      - Automatically populates student_id and run_id from context if not given
      - Writes to DB if student_id or run_id is present
      - Adds to memory ring buffer for legacy console
    """
    global _counter, _persist_failures

    s_id = student_id if student_id is not None else _current_student_id.get()
    r_id = run_id if run_id is not None else _current_run_id.get()

    lvl = str(level).lower().strip()
    if lvl == "warning":
        lvl = "warn"
    elif lvl not in VALID_LEVELS:
        lvl = "info"

    clean_input = sanitize_summary(input) if input is not None else None
    clean_output = sanitize_summary(output) if output is not None else None

    now_iso = datetime.now().isoformat()
    now_time = datetime.now().strftime("%H:%M:%S")

    # DB Persistence
    db_id = None
    if s_id is not None or r_id is not None:
        try:
            from core.db import get_db
            conn = get_db()
            cur = conn.cursor()
            in_json = json.dumps(clean_input) if clean_input is not None else None
            out_json = json.dumps(clean_output) if clean_output is not None else None
            cur.execute(
                """INSERT INTO agent_events (
                    run_id, student_id, agent, action, level, message, input_json, output_json, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r_id, s_id, agent, action, lvl, message, in_json, out_json, duration_ms, now_iso),
            )
            db_id = cur.lastrowid
            conn.commit()
            conn.close()
        except Exception:
            with _lock:
                _persist_failures += 1

    # In-memory ring buffer entry (legacy console compatibility)
    with _lock:
        _counter += 1
        event_id = db_id if db_id is not None else _counter
        event = {
            "id": event_id,
            "run_id": r_id,
            "student_id": s_id,
            "agent": agent,
            "action": action,
            "level": lvl,
            "message": message,
            "input": clean_input,
            "output": clean_output,
            "duration_ms": duration_ms,
            "created_at": now_iso,
            # Compat fields for /api/logs
            "timestamp": now_time,
            "slug": AGENTS.get(agent, "system"),
            "type": "warning" if lvl == "warn" else lvl,
            "payload": clean_output if clean_output is not None else clean_input,
        }
        _ring_buffer.append(event)
        if len(_ring_buffer) > MAX_ENTRIES:
            del _ring_buffer[0 : len(_ring_buffer) - MAX_ENTRIES]

    return event


def handoff(from_agent: str, to_agent: str, summary: str, payload: Optional[Any] = None) -> Dict[str, Any]:
    """Log one agent passing work to the next."""
    return emit(
        agent=from_agent,
        action="handoff",
        message=f"-> {to_agent}: {summary}",
        level="handoff",
        input={"from": from_agent, "to": to_agent, "summary": summary},
        output=payload,
    )


@contextlib.contextmanager
def pipeline_run(student_id: int, trigger: str):
    """
    Context manager to execute a pipeline run:
      - Creates a pipeline_runs row in DB with status='running'
      - Sets ambient student_id and run_id in contextvars
      - Tags all emit() and add_log() calls inside the block
      - Updates status to 'ok' or 'error' and records elapsed duration_ms
    """
    t0 = time.time()
    now_iso = datetime.now().isoformat()
    run_id = None

    try:
        from core.db import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pipeline_runs (student_id, trigger, status, started_at)
               VALUES (?, ?, 'running', ?)""",
            (student_id, trigger, now_iso),
        )
        run_id = cur.lastrowid
        conn.commit()
        conn.close()
    except Exception:
        pass

    tok_s = _current_student_id.set(student_id)
    tok_r = _current_run_id.set(run_id)

    status = "ok"
    try:
        emit("Coordinator", "run_start", f"Pipeline run started for student {student_id} (trigger: {trigger})",
             level="info", student_id=student_id, run_id=run_id, input={"trigger": trigger})
        yield run_id
    except Exception as exc:
        status = "error"
        emit("Coordinator", "run_error", f"Pipeline run failed: {exc}", level="error",
             student_id=student_id, run_id=run_id, output={"error": str(exc)})
        raise
    finally:
        elapsed_ms = int((time.time() - t0) * 1000)
        emit("Coordinator", "run_end", f"Pipeline run finished with status '{status}' in {elapsed_ms}ms",
             level="success" if status == "ok" else "error", student_id=student_id, run_id=run_id,
             output={"status": status, "duration_ms": elapsed_ms})

        _current_student_id.reset(tok_s)
        _current_run_id.reset(tok_r)

        if run_id:
            try:
                from core.db import get_db
                conn = get_db()
                conn.execute(
                    """UPDATE pipeline_runs
                       SET status = ?, finished_at = ?, duration_ms = ?
                       WHERE id = ?""",
                    (status, datetime.now().isoformat(), elapsed_ms, run_id),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass


def copy_context_and_run(func, *args, **kwargs):
    """Run a callable inside a copy of the current contextvars."""
    ctx = copy_context()
    return ctx.run(func, *args, **kwargs)


def run_in_thread_with_context(func, *args, **kwargs) -> threading.Thread:
    """Launch a background daemon thread that inherits ambient contextvars."""
    ctx = copy_context()

    def _target():
        ctx.run(func, *args, **kwargs)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t


def get_logs(after_id: int = 0) -> List[Dict[str, Any]]:
    """Legacy ring-buffer reader."""
    with _lock:
        return [e for e in _ring_buffer if e["id"] > after_id]


def all_logs() -> List[Dict[str, Any]]:
    """Legacy ring-buffer dump."""
    with _lock:
        return list(_ring_buffer)


def clear_logs() -> None:
    """Legacy ring-buffer clear."""
    global _ring_buffer, _counter
    with _lock:
        _ring_buffer = []
        _counter = 0


def cleanup_old_events(max_days: int = 14, max_per_student: int = 5000) -> int:
    """
    Retention policy helper:
      - Purges events older than max_days
      - Enforces maximum max_per_student events per student
    Returns total rows deleted.
    """
    deleted_count = 0
    try:
        from core.db import get_db
        conn = get_db()
        cur = conn.cursor()

        # 1. Purge events older than max_days
        cutoff = (datetime.now() - timedelta(days=max_days)).isoformat()
        cur.execute("DELETE FROM agent_events WHERE created_at < ?", (cutoff,))
        deleted_count += cur.rowcount

        # 2. Cap per student
        cur.execute("SELECT student_id, COUNT(*) as cnt FROM agent_events WHERE student_id IS NOT NULL GROUP BY student_id HAVING cnt > ?", (max_per_student,))
        over_students = cur.fetchall()
        for row in over_students:
            sid = row["student_id"]
            excess = row["cnt"] - max_per_student
            if excess > 0:
                cur.execute(
                    """DELETE FROM agent_events WHERE id IN (
                        SELECT id FROM agent_events WHERE student_id = ? ORDER BY id ASC LIMIT ?
                    )""",
                    (sid, excess),
                )
                deleted_count += cur.rowcount

        conn.commit()
        conn.close()
    except Exception:
        pass

    return deleted_count
