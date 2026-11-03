"""
=============================================================================
EduGen - Agent Activity Log (Compatibility Wrapper)
=============================================================================
In Phase 8, agent logging is unified under core/event_bus.py.
This module preserves the exact API of add_log, handoff, get_logs, all_logs,
and clear_logs so existing agent calls and the /api/logs UI console continue
to operate seamlessly while benefiting from structured event persistence and
pipeline run context tagging.
=============================================================================
"""

from typing import Any, Dict, List, Optional
from core.event_bus import (
    emit,
    get_logs,
    all_logs,
    clear_logs,
    AGENTS,
    MAX_ENTRIES,
)


def add_log(
    agent_name: str,
    message: str,
    log_type: str = "info",
    payload: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Record one agent action.
    Delegates to core.event_bus.emit() with ambient pipeline context.
    """
    action = "log"
    if isinstance(payload, dict) and "action" in payload:
        action = str(payload["action"])
    elif ":" in message:
        # heuristic action name
        candidate = message.split(":", 1)[0].strip()
        if len(candidate) <= 30 and " " not in candidate:
            action = candidate.lower()

    level = "warn" if log_type in ("warning", "warn") else log_type
    return emit(
        agent=agent_name,
        action=action,
        message=message,
        level=level,
        output=payload,
    )


def handoff(
    from_agent: str,
    to_agent: str,
    summary: str,
    payload: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Log one agent passing work to the next - the core of the multi-agent pipeline.
    """
    return emit(
        agent=from_agent,
        action="handoff",
        message=f"-> {to_agent}: {summary}",
        level="handoff",
        input={"from": from_agent, "to": to_agent, "summary": summary},
        output=payload,
    )
