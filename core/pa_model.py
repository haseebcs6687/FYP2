"""
=============================================================================
EduGen - Performance Analysis Model (core/pa_model.py)
=============================================================================
Pure functional domain model for Phase 5 Performance Analysis:
  1. Bayesian Knowledge Tracing (BKT) per concept:
     - Reference: Corbett, A. T., & Anderson, J. R. (1995). Knowledge tracing:
       Modeling the acquisition of procedural knowledge. User Modeling and
       User-Adapted Interaction, 4(4), 253-278.
     - Item-difficulty parameterization (Pardos & Heffernan, 2011).
  2. Misconception-level tracking:
     - Categorization: 'active', 'suspected', 'resolved'
     - Exponentially decayed severity: chosen * 0.9^(avoided_streak)
     - Human-readable evidence strings and catalog metadata attachment
  3. Facet error mapping per concept and facet
  4. Skill profiling by question type (concept, code_output, bug_find)
  5. Untagged error aggregation per concept
=============================================================================
"""

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from core.concepts import CONCEPTS, concept_title, module_of
from core.misconceptions import MISCONCEPTIONS, is_valid_misconception

# ─────────────────────────────────────────────────────────────────────────────
# 1. BKT PARAMETERS & CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
# Baseline literature constants from Corbett & Anderson (1995):
BKT_P_INIT = 0.25    # Prior probability that a concept is known before any observation
BKT_P_LEARN = 0.15   # Probability of transitioning from unlearned to learned state per question
BKT_GUESS = 0.25     # Standard 4-option multiple-choice baseline guessing rate

# Item difficulty parameterization (Corbett & Anderson 1995; Pardos & Heffernan 2011):
# Easy: slip 0.05, guess 0.25
# Medium: slip 0.10, guess 0.20
# Hard: slip 0.15, guess 0.15
# Rationale: On harder questions, plausible distractors reduce blind guess probability,
# while subtle conceptual traps increase slip probability. Consequently, answering a
# Hard question correctly provides stronger evidence of mastery than an Easy question.
BKT_SLIP_BY_DIFF = {
    "Easy": 0.05,
    "Medium": 0.10,
    "Hard": 0.15,
}

BKT_GUESS_BY_DIFF = {
    "Easy": 0.25,
    "Medium": 0.20,
    "Hard": 0.15,
}

# Classification thresholds
WEAK_THRESHOLD = 50.0        # BKT mastery (0-100) below this -> weak
STRONG_THRESHOLD = 80.0      # BKT mastery at or above -> strong
MIN_ATTEMPTS = 2             # Fewer attempts -> insufficient evidence
EWMA_ALPHA = 0.45            # Recency weight for legacy EWMA comparison
MASTERY_MIN_DISPLAY = 2.0    # Display clamp lower bound
MASTERY_MAX_DISPLAY = 98.0   # Display clamp upper bound


def clamp_mastery(val: float) -> float:
    """
    Clamps displayed mastery percentage to [2.0, 98.0] to prevent misleading
    0.0% or 100.0% saturation while keeping underlying p_known raw.
    """
    return round(min(MASTERY_MAX_DISPLAY, max(MASTERY_MIN_DISPLAY, float(val))), 1)


def update_bkt(p_known: float, is_correct: bool, difficulty: str = "Medium", apply_transition: bool = True) -> float:
    """
    Standard Bayesian Knowledge Tracing posterior update followed by learning transition.

    1. Posterior update:
       If correct:
         P(L_t | obs=1) = (P_prev * (1 - P_slip)) / [P_prev * (1 - P_slip) + (1 - P_prev) * P_guess]
       If incorrect:
         P(L_t | obs=0) = (P_prev * P_slip) / [P_prev * P_slip + (1 - P_prev) * (1 - P_guess)]

    2. Learning transition:
       P(L_t+1) = P(L_t | obs) + (1 - P(L_t | obs)) * P_learn
       (If apply_transition is False, returns the current posterior belief P(L_t | obs))
    """
    diff_key = str(difficulty or "Medium").capitalize()
    slip = BKT_SLIP_BY_DIFF.get(diff_key, 0.10)
    guess = BKT_GUESS_BY_DIFF.get(diff_key, 0.20)

    p_prev = min(1.0, max(0.0, float(p_known)))

    if is_correct:
        num = p_prev * (1.0 - slip)
        den = num + (1.0 - p_prev) * guess
    else:
        num = p_prev * slip
        den = num + (1.0 - p_prev) * (1.0 - guess)

    p_post = (num / den) if den > 0.0 else p_prev
    if not apply_transition:
        return min(1.0, max(0.0, p_post))

    p_next = p_post + (1.0 - p_post) * BKT_P_LEARN
    return min(1.0, max(0.0, p_next))


def compute_concept_bkt(events: List[Dict[str, Any]]) -> Tuple[float, float]:
    """
    Chronologically roll BKT over a list of attempt events for one concept.
    Returns: (p_known, ewma_accuracy) where p_known is in [0.0, 1.0] and ewma is in [0.0, 100.0].
    """
    if not events:
        return BKT_P_INIT, 0.0

    p_known = BKT_P_INIT
    ewma = None
    n = len(events)

    for i, e in enumerate(events):
        is_correct = bool(e.get("is_correct"))
        diff = e.get("difficulty") or "Medium"
        is_last = (i == n - 1)
        p_known = update_bkt(p_known, is_correct, difficulty=diff, apply_transition=not is_last)

        val = 100.0 if is_correct else 0.0
        ewma = val if ewma is None else (EWMA_ALPHA * val + (1.0 - EWMA_ALPHA) * ewma)

    return p_known, round(ewma or 0.0, 1)


def get_confidence(attempts_count: int) -> str:
    """Confidence level in mastery measurement based on sample size."""
    if attempts_count < 3:
        return "low"
    elif attempts_count <= 5:
        return "medium"
    return "high"


# ─────────────────────────────────────────────────────────────────────────────
# 2. MISCONCEPTION TRACKER
# ─────────────────────────────────────────────────────────────────────────────
def compute_misconception_stats(
    attempts: List[Dict[str, Any]],
    total_quizzes: int = 0,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Tracks misconception lifecycle per (student, misconception):
      - chosen: total times selected as a wrong distractor
      - offered: total times this misconception was available among options
      - avoided_streak: consecutive times offered and NOT selected since last chosen
      - severity: chosen * 0.9^(avoided_streak)
      - status:
          * 'active'   : chosen >= 2 and avoided_streak < 2
          * 'resolved' : chosen >= 1 and avoided_streak >= 2
          * 'suspected': chosen == 1 and avoided_streak < 2

    Returns:
      {"active": [...], "suspected": [...], "resolved": [...]}
      with items sorted descending by severity.
    """
    records: Dict[str, Dict[str, Any]] = {}
    distinct_quiz_ids = []

    for att in attempts:
        qrid = att.get("quiz_result_id")
        if qrid and qrid not in distinct_quiz_ids:
            distinct_quiz_ids.append(qrid)

        ts = att.get("timestamp")
        chosen_mid = att.get("misconception_id")
        concept = att.get("concept") or (att.get("concept_tags", [None])[0])

        # Parse offered misconceptions from attempt row
        raw_offered = att.get("offered_misconceptions")
        offered_list = []
        if isinstance(raw_offered, list):
            offered_list = [m for m in raw_offered if m]
        elif isinstance(raw_offered, str) and raw_offered.strip():
            try:
                parsed = json.loads(raw_offered)
                if isinstance(parsed, list):
                    offered_list = [m for m in parsed if m]
            except Exception:
                offered_list = []

        # If offered_list was empty (legacy attempts), ensure chosen_mid is registered
        if chosen_mid and chosen_mid not in offered_list:
            offered_list.append(chosen_mid)

        for mid in offered_list:
            if mid not in records:
                m_info = MISCONCEPTIONS.get(mid, {})
                m_concept = concept or m_info.get("concept", "")
                m_facet = att.get("facet") or m_info.get("facet", "")
                records[mid] = {
                    "misconception_id": mid,
                    "concept": m_concept,
                    "facet": m_facet,
                    "chosen": 0,
                    "offered": 0,
                    "avoided_streak": 0,
                    "first_seen": ts,
                    "last_seen": ts,
                    "last_chosen_timestamp": None,
                    "last_chosen_quiz_idx": None,
                }

            rec = records[mid]
            rec["offered"] += 1
            rec["last_seen"] = ts or rec["last_seen"]
            if not rec["first_seen"]:
                rec["first_seen"] = ts

            if chosen_mid == mid:
                rec["chosen"] += 1
                rec["avoided_streak"] = 0
                rec["last_chosen_timestamp"] = ts
                rec["last_chosen_quiz_idx"] = len(distinct_quiz_ids)
            else:
                if rec["chosen"] > 0:
                    rec["avoided_streak"] += 1

    active_list = []
    suspected_list = []
    resolved_list = []

    total_q_count = max(len(distinct_quiz_ids), total_quizzes, 1)

    for mid, rec in records.items():
        chosen = rec["chosen"]
        if chosen == 0:
            continue

        offered = rec["offered"]
        avoided = rec["avoided_streak"]

        # Severity calculation: chosen * (0.9 ** avoided_streak)
        severity = round(float(chosen) * (0.9 ** avoided), 3)

        # Status classification
        if chosen >= 2 and avoided < 2:
            status = "active"
        elif chosen >= 1 and avoided >= 2:
            status = "resolved"
        elif chosen == 1 and avoided < 2:
            status = "suspected"
        else:
            status = "resolved"

        rec["status"] = status
        rec["severity"] = severity

        # Catalog enrichment
        m_cat = MISCONCEPTIONS.get(mid, {})
        rec["title"] = m_cat.get("title", mid)
        rec["wrong_belief"] = m_cat.get("wrong_belief", "")
        rec["correct_idea"] = m_cat.get("correct_idea", "")
        if not rec["facet"]:
            rec["facet"] = m_cat.get("facet", "")

        # Build one-sentence human-readable evidence string
        last_quiz_idx = rec["last_chosen_quiz_idx"] or total_q_count
        quizzes_ago = max(0, total_q_count - last_quiz_idx)

        q_plural = "question" if offered == 1 else "questions"
        if avoided == 0:
            when_str = "most recently in current quiz" if quizzes_ago == 0 else f"last chosen {quizzes_ago} quiz{'zes' if quizzes_ago != 1 else ''} ago"
            evidence = f"Chose this option in {chosen} of the {offered} {q_plural} where it appeared ({when_str})."
        else:
            evidence = f"Chose this option in {chosen} of the {offered} {q_plural} where it appeared (avoided across {avoided} consecutive recent opportunities)."

        rec["evidence"] = evidence

        # Add to appropriate bucket
        item_copy = dict(rec)
        if status == "active":
            active_list.append(item_copy)
        elif status == "suspected":
            suspected_list.append(item_copy)
        elif status == "resolved":
            resolved_list.append(item_copy)

    # Sort each list by severity descending
    active_list.sort(key=lambda x: -x["severity"])
    suspected_list.sort(key=lambda x: -x["severity"])
    resolved_list.sort(key=lambda x: -x["severity"])

    return {
        "active": active_list,
        "suspected": suspected_list,
        "resolved": resolved_list,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. FACET MAP
# ─────────────────────────────────────────────────────────────────────────────
def compute_facet_map(attempts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Computes per-concept and per-facet error rate:
      - offered: number of questions belonging to this facet
      - chosen: number of questions where student answered incorrectly in this facet
      - error_rate: chosen / offered
      - weak: True when chosen >= 2 and error_rate >= 0.5
    """
    counts = defaultdict(lambda: defaultdict(lambda: {"offered": 0, "chosen": 0}))

    for att in attempts:
        facet = att.get("facet")
        concept_tags = att.get("concept_tags") or []
        concept = att.get("concept") or (concept_tags[0] if concept_tags else None)

        if not concept or not facet:
            continue

        counts[concept][facet]["offered"] += 1
        if not att.get("is_correct"):
            counts[concept][facet]["chosen"] += 1

    facet_map = {}
    for concept, facets in counts.items():
        facet_map[concept] = {}
        for facet_name, data in facets.items():
            offered = data["offered"]
            chosen = data["chosen"]
            err_rate = round(float(chosen) / float(offered), 2) if offered > 0 else 0.0
            weak = bool(chosen >= 2 and err_rate >= 0.5)
            facet_map[concept][facet_name] = {
                "offered": offered,
                "chosen": chosen,
                "error_rate": err_rate,
                "weak": weak,
            }

    return facet_map


# ─────────────────────────────────────────────────────────────────────────────
# 4. SKILL PROFILE
# ─────────────────────────────────────────────────────────────────────────────
def compute_skill_profile(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Accuracy by question type (concept / code_output / bug_find) overall and per module:
      - Identifies skill gaps when any qtype is >= 25 points below other qtypes
        with at least 4 attempts each.
    """
    VALID_QTYPES = ("concept", "code_output", "bug_find")

    overall = {qt: {"attempts": 0, "correct": 0, "accuracy": 0.0} for qt in VALID_QTYPES}
    by_module: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {qt: {"attempts": 0, "correct": 0, "accuracy": 0.0} for qt in VALID_QTYPES}
    )

    for att in attempts:
        qtype = att.get("qtype") or "concept"
        if qtype not in VALID_QTYPES:
            qtype = "concept"

        concept_tags = att.get("concept_tags") or []
        concept = att.get("concept") or (concept_tags[0] if concept_tags else None)
        mod = module_of(concept) if concept else "general"

        is_c = 1 if att.get("is_correct") else 0

        overall[qtype]["attempts"] += 1
        overall[qtype]["correct"] += is_c

        by_module[mod][qtype]["attempts"] += 1
        by_module[mod][qtype]["correct"] += is_c

    # Calculate accuracies
    for qt in VALID_QTYPES:
        att_cnt = overall[qt]["attempts"]
        cor_cnt = overall[qt]["correct"]
        overall[qt]["accuracy"] = round(100.0 * cor_cnt / att_cnt, 1) if att_cnt else 0.0

    for mod, mod_data in by_module.items():
        for qt in VALID_QTYPES:
            att_cnt = mod_data[qt]["attempts"]
            cor_cnt = mod_data[qt]["correct"]
            mod_data[qt]["accuracy"] = round(100.0 * cor_cnt / att_cnt, 1) if att_cnt else 0.0

    # Detect skill gaps (overall)
    skill_gaps = []
    eligible = {qt: overall[qt] for qt in VALID_QTYPES if overall[qt]["attempts"] >= 4}

    if len(eligible) >= 2:
        for qt_a, stat_a in eligible.items():
            for qt_b, stat_b in eligible.items():
                if qt_a == qt_b:
                    continue
                diff = stat_a["accuracy"] - stat_b["accuracy"]
                if diff >= 25.0:
                    if qt_a == "concept" and qt_b == "code_output":
                        gap_msg = f"Knows the theory (concept: {stat_a['accuracy']}%) but fails code tracing (code_output: {stat_b['accuracy']}%)"
                    elif qt_a == "concept" and qt_b == "bug_find":
                        gap_msg = f"Knows the theory (concept: {stat_a['accuracy']}%) but struggles with bug finding (bug_find: {stat_b['accuracy']}%)"
                    elif qt_a == "code_output" and qt_b == "bug_find":
                        gap_msg = f"Strong code tracing (code_output: {stat_a['accuracy']}%) but struggles with bug identification (bug_find: {stat_b['accuracy']}%)"
                    else:
                        gap_msg = f"Skill gap detected: {qt_a} ({stat_a['accuracy']}%) vs {qt_b} ({stat_b['accuracy']}%, gap: {round(diff, 1)} pts)"
                    if gap_msg not in skill_gaps:
                        skill_gaps.append(gap_msg)

    return {
        "overall": overall,
        "by_module": dict(by_module),
        "skill_gaps": skill_gaps,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. UNTAGGED ERRORS
# ─────────────────────────────────────────────────────────────────────────────
def compute_untagged_errors(attempts: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Count wrong answers where misconception_id is None / empty per concept.
    These still affect mastery via BKT downward updates, but do not provide misconception evidence.
    """
    untagged = defaultdict(int)
    for att in attempts:
        if not att.get("is_correct"):
            if not att.get("misconception_id"):
                concept_tags = att.get("concept_tags") or []
                concept = att.get("concept") or (concept_tags[0] if concept_tags else None)
                if concept:
                    untagged[concept] += 1
    return dict(untagged)
