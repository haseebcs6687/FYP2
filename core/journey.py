"""
=============================================================================
EduGen - Student Journey Logic (core/journey.py)
=============================================================================
Pure algorithmic state machine and decision logic for the student learning loop.
Contains NO database queries and NO LLM calls.

Journey States:
  - NEW: Student has not yet completed a diagnostic evaluation quiz.
  - PLAN_ACTIVE: Student has an active, ordered study plan in progress.
  - COMPLETE: All target concepts are mastered and closing evaluations passed.
=============================================================================
"""

from typing import Any, Dict, List, Optional
from core.concepts import concept_title
from core.study_planner import plan_step_concepts

STATE_NEW = "NEW"
STATE_PLAN_ACTIVE = "PLAN_ACTIVE"
STATE_COMPLETE = "COMPLETE"

VALID_STATES = {STATE_NEW, STATE_PLAN_ACTIVE, STATE_COMPLETE}
QUIZ_KINDS = {"check", "probe", "reevaluation"}


def is_lesson_step(step: Dict[str, Any]) -> bool:
    """Return True if step represents a learning/lesson step (not a quiz step)."""
    k = str(step.get("kind", "")).lower().strip()
    return k not in QUIZ_KINDS


def is_quiz_step(step: Dict[str, Any]) -> bool:
    """Return True if step represents a quiz check, probe, or reevaluation step."""
    return not is_lesson_step(step)


def compute_next_action(
    state: str,
    plan: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    quiz_history_count: int = 0,
) -> Dict[str, Any]:
    """
    3.1 compute_next_action:
    Pure decision function returning exactly one action dict:
      - {"type": "take_quiz", "quiz": {"kind": "diagnostic"}} (NEW or missing plan)
      - {"type": "study_step", "step_id": ..., "concept": ..., "style": ..., "title": ...}
      - {"type": "take_quiz", "step_id": ..., "quiz": {"kind": "practice", "concept": ..., "n": 3, "difficulty": "Easy"}} ('check' step)
      - {"type": "take_quiz", "step_id": ..., "quiz": {"kind": "probe", "concept": ..., "n": 8}} ('probe' step)
      - {"type": "take_quiz", "step_id": ..., "quiz": {"kind": "reevaluation", "concepts": [...]}} ('reevaluation' step)
      - {"type": "course_complete", "message": ...} (COMPLETE)

    Rule: Quiz steps whose position comes AFTER unfinished lesson steps are not
    offered yet (lessons first), except when all preceding lesson steps are completed or skipped.
    """
    state_norm = str(state or STATE_NEW).strip().upper()

    # 1. Explicit COMPLETE state (when not overridden by a plan with pending steps)
    if state_norm == STATE_COMPLETE and not (steps and any(str(s.get("status", "pending")).lower().strip() not in ("done", "skipped") for s in steps)):
        return {
            "type": "course_complete",
            "message": "Congratulations! You have mastered all target Java OOP concepts in your personalized study plan.",
            "upcoming": [],
        }

    # 2. NEW student or missing plan / steps
    if state_norm == STATE_NEW or not plan or not steps:
        return {
            "type": "take_quiz",
            "quiz": {"kind": "diagnostic"},
            "message": "Welcome to EduGen! Take the diagnostic quiz to establish your baseline and generate your personalized study plan.",
            "upcoming": [],
        }

    # 3. Completion check on CURRENT plan ONLY:
    # complete iff the current plan's reevaluation step is 'done', or every step of the current plan is done/skipped.
    # No other source.
    reeval_done = any(
        s.get("kind") == "reevaluation" and str(s.get("status", "")).lower().strip() == "done"
        for s in (steps or [])
    )
    all_done = all(
        str(s.get("status", "pending")).lower().strip() in ("done", "skipped")
        for s in (steps or [])
    )

    if reeval_done or all_done:
        return {
            "type": "course_complete",
            "message": "Congratulations! You have mastered all target Java OOP concepts in your personalized study plan.",
            "upcoming": [],
        }

    # 3. Sort steps in plan order by position
    sorted_steps = sorted(steps, key=lambda s: int(s.get("position", 0)))

    # Find first unfinished step in plan order
    target_step = None
    target_idx = -1
    for idx, s in enumerate(sorted_steps):
        st = str(s.get("status", "pending")).lower().strip()
        if st not in ("done", "skipped"):
            target_step = s
            target_idx = idx
            break

    # If all steps are done or skipped
    if target_step is None:
        return {
            "type": "course_complete",
            "message": "All steps in your current study plan have been completed.",
            "upcoming": [],
        }

    # Check for upcoming steps (next unfinished steps following the target step, max 3)
    upcoming_raw = [
        s for s in sorted_steps[target_idx + 1 :]
        if str(s.get("status", "pending")).lower().strip() not in ("done", "skipped")
    ][:3]
    upcoming = [
        {
            "id": s.get("id"),
            "position": s.get("position"),
            "concept": s.get("concept"),
            "title": s.get("title") or concept_title(s.get("concept", "")),
            "kind": s.get("kind"),
            "status": s.get("status", "pending"),
            "lesson_style": s.get("lesson_style"),
        }
        for s in upcoming_raw
    ]

    c = target_step.get("concept", "")
    t = target_step.get("title") or concept_title(c)
    sid = target_step.get("id")
    kind = str(target_step.get("kind", "weak")).lower().strip()
    style = target_step.get("lesson_style", "detailed")

    # 4. Return appropriate action
    if is_lesson_step(target_step):
        return {
            "type": "study_step",
            "step_id": sid,
            "concept": c,
            "style": style,
            "title": t,
            "message": f"Continue your study plan: learn '{t}' ({style} lesson).",
            "upcoming": upcoming,
        }

    if kind == "check":
        diff = target_step.get("difficulty") or "Easy"
        return {
            "type": "take_quiz",
            "step_id": sid,
            "quiz": {
                "kind": "practice",
                "concept": c,
                "n": 3,
                "difficulty": diff,
            },
            "message": f"Quick diagnostic check: verify your prerequisite knowledge of '{t}' (3 questions).",
            "upcoming": upcoming,
        }

    if kind == "probe":
        return {
            "type": "take_quiz",
            "step_id": sid,
            "quiz": {
                "kind": "probe",
                "concept": c,
                "n": 8,
            },
            "message": f"Concept probe quiz: sweeping potential misconceptions on '{t}' (8 questions).",
            "upcoming": upcoming,
        }

    if kind == "reevaluation":
        targeted_concepts = plan_step_concepts(target_step) or [c]
        # Filter out sentinel if any
        targeted_concepts = [tc for tc in targeted_concepts if tc and tc != "all-plan-concepts"]
        if not targeted_concepts and steps:
            # Fall back to distinct non-sentinel canonical concepts across plan steps
            targeted_concepts = [
                s.get("concept") for s in steps
                if s.get("concept") and s.get("concept") != "all-plan-concepts"
            ]
            # Deduplicate preserving order
            seen_c = set()
            targeted_concepts = [x for x in targeted_concepts if not (x in seen_c or seen_c.add(x))]
        if not targeted_concepts:
            targeted_concepts = [c]

        return {
            "type": "take_quiz",
            "step_id": sid,
            "quiz": {
                "kind": "reevaluation",
                "concepts": targeted_concepts,
            },
            "message": "Final re-evaluation quiz: verifying mastery across all learned concepts.",
            "upcoming": upcoming,
        }

    # Fallback to lesson step
    return {
        "type": "study_step",
        "step_id": sid,
        "concept": c,
        "style": style,
        "title": t,
        "message": f"Study '{t}'.",
        "upcoming": upcoming,
    }
