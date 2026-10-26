"""
=============================================================================
EduGen - Agent Activity Log
=============================================================================
An in-memory ring buffer of everything the four agents do, polled by the
floating log console in the UI (`/api/logs?after=<id>`).

This is the evidence of agentic behaviour that an FYP evaluator asks for:
"prove the agents are actually talking to each other". Keep it on during the
demo, flip EDUGEN_SHOW_LOGS=0 in .env to hide the console in production.
=============================================================================
"""

import threading
from datetime import datetime

MAX_ENTRIES = 300

AGENTS = {
    "Coordinator": "coordinator",
    "Performance Analysis": "performance",
    "Adaptive Content": "adaptive",
    "Concept Clarifier": "clarifier",
    "Retriever": "retriever",
    "System": "system",
}

_lock = threading.Lock()
_entries = []
_counter = 0


def add_log(agent_name, message, log_type="info", payload=None):
    """
    Record one agent action.

    agent_name : one of AGENTS keys (free text is accepted and shown as-is)
    log_type   : info | success | warning | error | handoff
    payload    : optional small dict shown when the entry is expanded
    """
    global _counter
    with _lock:
        _counter += 1
        entry = {
            "id": _counter,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "agent": agent_name,
            "slug": AGENTS.get(agent_name, "system"),
            "message": message,
            "type": log_type,
            "payload": payload,
        }
        _entries.append(entry)
        if len(_entries) > MAX_ENTRIES:
            del _entries[0:len(_entries) - MAX_ENTRIES]
    return entry


def handoff(from_agent, to_agent, summary, payload=None):
    """Log one agent passing work to the next - the core of the pipeline."""
    return add_log(
        from_agent,
        "-> {}: {}".format(to_agent, summary),
        log_type="handoff",
        payload=payload,
    )


def get_logs(after_id=0):
    with _lock:
        return [e for e in _entries if e["id"] > after_id]


def all_logs():
    with _lock:
        return list(_entries)


def clear_logs():
    global _entries, _counter
    with _lock:
        _entries = []
        _counter = 0
