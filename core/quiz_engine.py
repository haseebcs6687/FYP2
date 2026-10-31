"""
=============================================================================
EduGen - Quiz Engine (Phase 4A)
=============================================================================
Misconception-first quiz generation logic:
  - Blueprint construction for practice, diagnostic, and reevaluation
  - Misconception prioritization based on student attempt history
  - Canonical normalization, validation, and deterministic option shuffling
  - Slot grouping for batched generation
=============================================================================
"""

import collections
from datetime import datetime, timedelta
import hashlib
import json
import random
import re

from core.concepts import (
    CONCEPTS,
    ENTRY_CONCEPT,
    MODULE_CONCEPTS,
    MODULES,
)
from core.db import get_db
from core.misconceptions import (
    MISCONCEPTIONS,
    is_valid_misconception,
    misconceptions_for,
)

# Regex to detect explanation referring directly to option letters/numbers
_OPTION_LABEL_RE = re.compile(
    r"\b(?:option|choice)\s*(?:#?\s*[1-4]|[A-Da-d])\b|"
    r"\([A-Da-d1-4]\)|"
    r"\b[A-Da-d]\s+is\s+(?:the\s+)?(?:correct|right|wrong|incorrect|best|answer)\b",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────
# 1.1 Normalization & Validation
# ─────────────────────────────────────────────────────────────
def normalize_question(raw, concept, difficulty):
    """
    Validate and normalize a raw question record into canonical shape:
    {
      question, options[4 strings], correct (0-3), explanation,
      concept, concept_tags, difficulty,
      qtype ('concept'|'code_output'|'bug_find'),
      option_misconception_ids[4] (null at the correct index),
      facet, reference_ids[],
      meta: {...}
    }

    Returns (record, None) or (None, reject_reason).
    """
    if not isinstance(raw, dict):
        return None, "raw_not_a_dict"

    question_text = str(raw.get("question") or "").strip()
    if not question_text:
        return None, "empty_question"

    # Unbalanced code fences check
    if question_text.count("```") % 2 != 0:
        return None, "unbalanced_fences"

    explanation = str(raw.get("explanation") or "").strip()
    if explanation.count("```") % 2 != 0:
        return None, "unbalanced_fences"

    # Explanation naming option by letter/number check
    if _OPTION_LABEL_RE.search(explanation):
        return None, "explanation_names_option"

    # qtype validation
    qtype = raw.get("qtype") or "concept"
    if qtype not in ("concept", "code_output", "bug_find"):
        return None, "invalid_qtype"

    # code_output / bug_find must contain a ```java fence
    if qtype in ("code_output", "bug_find"):
        if "```java" not in question_text.lower():
            return None, "missing_java_fence"

    # Parse options and misconception IDs
    raw_options = raw.get("options")
    if not isinstance(raw_options, list) or len(raw_options) != 4:
        return None, "options_must_have_length_4"

    cleaned_options = []
    option_misconception_ids = []

    for item in raw_options:
        if isinstance(item, dict):
            opt_str = str(item.get("text", "")).strip()
            m_id = item.get("misconception_id")
        else:
            opt_str = str(item).strip()
            m_id = None
        cleaned_options.append(opt_str)
        option_misconception_ids.append(m_id)

    # If raw has a separate option_misconceptions list
    if any(m is None for m in option_misconception_ids) and "option_misconceptions" in raw:
        alt_mids = raw.get("option_misconceptions") or []
        for i in range(min(4, len(alt_mids))):
            if option_misconception_ids[i] is None and alt_mids[i]:
                option_misconception_ids[i] = alt_mids[i]

    # Duplicate options check
    if len(set(cleaned_options)) != 4 or any(len(o) == 0 for o in cleaned_options):
        return None, "duplicate_options"

    # Correct index validation
    try:
        correct = int(raw.get("correct"))
    except (TypeError, ValueError):
        return None, "correct_out_of_range"

    if correct < 0 or correct > 3:
        return None, "correct_out_of_range"

    # Misconception IDs validation
    # Must exist in core.misconceptions for THIS concept, otherwise set to None
    invalid_mids_count = 0
    validated_mids = []
    for i, mid in enumerate(option_misconception_ids):
        if i == correct:
            validated_mids.append(None)
            continue
        if mid and is_valid_misconception(mid, concept=concept):
            validated_mids.append(mid)
        else:
            if mid:
                invalid_mids_count += 1
            validated_mids.append(None)

    # Deterministic option shuffling seeded by sha1 of question text
    seed_val = int(hashlib.sha1(question_text.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed_val)
    perm = [0, 1, 2, 3]
    rng.shuffle(perm)

    shuffled_options = [cleaned_options[i] for i in perm]
    shuffled_mids = [validated_mids[i] for i in perm]
    new_correct = perm.index(correct)
    shuffled_mids[new_correct] = None  # Ensure correct option is strictly None

    concept_tags = raw.get("concept_tags") or [concept]
    if concept not in concept_tags:
        concept_tags.insert(0, concept)

    record = {
        "question": question_text,
        "options": shuffled_options,
        "correct": new_correct,
        "explanation": explanation,
        "concept": concept,
        "concept_tags": concept_tags,
        "difficulty": difficulty,
        "qtype": qtype,
        "option_misconception_ids": shuffled_mids,
        "facet": raw.get("facet"),
        "reference_ids": raw.get("reference_ids", []),
        "meta": {
            "invalid_misconceptions": invalid_mids_count,
        },
    }
    return record, None


# ─────────────────────────────────────────────────────────────
# 1.2 Default Difficulty & Blueprint
# ─────────────────────────────────────────────────────────────
def get_concept_mastery(student_id, concept):
    """Return student mastery float (0.0 to 1.0) or None if no record."""
    if not student_id:
        return None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT mastery FROM concept_mastery WHERE student_id = ? AND concept = ?",
            (student_id, concept),
        ).fetchone()
        conn.close()
        if row is not None:
            return float(row["mastery"])
    except Exception:
        pass
    return None


def default_difficulty_for_concept(student_id, concept):
    """
    Default difficulty from concept_mastery:
      <0.40 Easy, 0.40-0.70 Medium, >0.70 Hard, unknown -> Easy.
    """
    mastery = get_concept_mastery(student_id, concept)
    if mastery is None:
        return "Easy"
    if mastery < 0.40:
        return "Easy"
    if mastery <= 0.70:
        return "Medium"
    return "Hard"


def _qtype_distribution(n, difficulty):
    """
    Generate list of n qtypes matching ~60% concept, 25% code_output, 15% bug_find.
    If difficulty is Easy: concept only.
    """
    if difficulty == "Easy":
        return ["concept"] * n

    if n <= 1:
        return ["concept"]
    if n == 2:
        return ["concept", "code_output"]

    n_code = round(n * 0.25)
    n_bug = round(n * 0.15)
    # Ensure bug_find gets at least 1 when n >= 4
    if n >= 4 and n_bug == 0:
        n_bug = 1
    if n_code + n_bug >= n:
        n_code = max(0, n - 1 - n_bug)
    n_concept = max(1, n - n_code - n_bug)

    types = (["concept"] * n_concept) + (["code_output"] * n_code) + (["bug_find"] * n_bug)
    # Trim or pad to exact length n
    if len(types) > n:
        types = types[:n]
    while len(types) < n:
        types.append("concept")
    return types


def _foundational_concepts():
    """
    Identify 12 foundational concepts across the 8 OOP modules.
    Foundational concepts are those with fewest prerequisites.
    Returns list of 12 concept tags.
    """
    # Order modules by sequence
    sorted_modules = sorted(MODULES.keys(), key=lambda m: MODULES[m]["order"])
    foundational = []

    # For each module, sort concepts by number of prerequisites ascending
    module_foundational = {}
    for mid in sorted_modules:
        c_list = MODULE_CONCEPTS.get(mid, [])
        ranked = sorted(c_list, key=lambda c: (len(CONCEPTS[c].get("prerequisites", [])), c))
        module_foundational[mid] = ranked

    # Pick 1 from each module (8 concepts)
    for mid in sorted_modules:
        if module_foundational[mid]:
            foundational.append(module_foundational[mid][0])

    # Pick 2nd foundational concept from first 4 modules (total 12 concepts)
    for mid in sorted_modules[:4]:
        if len(module_foundational[mid]) > 1:
            foundational.append(module_foundational[mid][1])

    return foundational[:12]


def build_blueprint(kind="practice", student_id=None, concepts=None, n=None, difficulty=None):
    """
    Build a list of question slots for a quiz session.
    Each slot: {concept, difficulty, qtype, target_misconceptions:[ids]}.

    kinds:
      'practice':
        one concept, n default 5.
      'diagnostic':
        first visit, 12 slots: 1-2 foundational concepts per module, Easy x6 + Medium x6.
      'reevaluation':
        given concepts (or lowest 3), 2 slots each at difficulty,
        plus up to 2 retention slots from concepts mastered in last 14 days.
    """
    slots = []

    if kind == "diagnostic":
        diag_concepts = _foundational_concepts()
        # 6 Easy + 6 Medium
        diffs = ["Easy"] * 6 + ["Medium"] * 6
        for i, c in enumerate(diag_concepts):
            d = diffs[i]
            qt = "concept" if d == "Easy" else (
                "code_output" if i in (7, 10) else ("bug_find" if i == 11 else "concept")
            )
            targets = prioritize_misconceptions(student_id, c, k=3)
            slots.append({
                "concept": c,
                "difficulty": d,
                "qtype": qt,
                "target_misconceptions": targets,
            })
        return slots

    if kind == "reevaluation":
        eval_concepts = []
        if concepts:
            if isinstance(concepts, str):
                eval_concepts = [concepts]
            elif isinstance(concepts, (list, tuple)):
                eval_concepts = list(concepts)
        else:
            # Student's 3 lowest-mastery concepts
            eval_concepts = _lowest_mastery_concepts(student_id, count=3)

        retention_concepts = _mastered_recent_concepts(student_id, exclude=eval_concepts, max_count=2)

        for c in eval_concepts:
            slot_diff = difficulty or default_difficulty_for_concept(student_id, c)
            qtypes = _qtype_distribution(2, slot_diff)
            for qt in qtypes:
                targets = prioritize_misconceptions(student_id, c, k=3)
                slots.append({
                    "concept": c,
                    "difficulty": slot_diff,
                    "qtype": qt,
                    "target_misconceptions": targets,
                })

        for c in retention_concepts:
            r_diff = difficulty or "Medium"
            targets = prioritize_misconceptions(student_id, c, k=3)
            slots.append({
                "concept": c,
                "difficulty": r_diff,
                "qtype": "code_output" if r_diff != "Easy" else "concept",
                "target_misconceptions": targets,
            })

        return slots

    # Default 'practice'
    target_concept = None
    if concepts:
        target_concept = concepts[0] if isinstance(concepts, (list, tuple)) else str(concepts)
    if not target_concept or target_concept not in CONCEPTS:
        target_concept = ENTRY_CONCEPT

    slot_count = n if (isinstance(n, int) and n > 0) else 5
    slot_diff = difficulty or default_difficulty_for_concept(student_id, target_concept)
    qtypes = _qtype_distribution(slot_count, slot_diff)

    for qt in qtypes:
        targets = prioritize_misconceptions(student_id, target_concept, k=3)
        slots.append({
            "concept": target_concept,
            "difficulty": slot_diff,
            "qtype": qt,
            "target_misconceptions": targets,
        })

    return slots


def _lowest_mastery_concepts(student_id, count=3):
    """Return list of concept tags with lowest mastery for this student."""
    if not student_id:
        return _foundational_concepts()[:count]
    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT concept FROM concept_mastery
               WHERE student_id = ?
               ORDER BY mastery ASC, attempts DESC
               LIMIT ?""",
            (student_id, count),
        ).fetchall()
        conn.close()
        found = [r["concept"] for r in rows if r["concept"] in CONCEPTS]
        if len(found) < count:
            for fc in _foundational_concepts():
                if fc not in found:
                    found.append(fc)
                if len(found) >= count:
                    break
        return found[:count]
    except Exception:
        return _foundational_concepts()[:count]


def _mastered_recent_concepts(student_id, exclude=(), max_count=2):
    """Return concepts mastered (>=0.70) in the last 14 days."""
    if not student_id:
        return []
    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT concept, updated_at FROM concept_mastery
               WHERE student_id = ? AND mastery >= 0.70
               ORDER BY updated_at DESC""",
            (student_id,),
        ).fetchall()
        conn.close()

        cutoff = datetime.now() - timedelta(days=14)
        results = []
        exclude_set = set(exclude or [])
        for r in rows:
            c = r["concept"]
            if c in exclude_set or c not in CONCEPTS:
                continue
            up_str = r["updated_at"]
            if up_str:
                try:
                    dt = datetime.fromisoformat(up_str)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
            results.append(c)
            if len(results) >= max_count:
                break
        return results
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# 1.3 Prioritize Misconceptions
# ─────────────────────────────────────────────────────────────
def prioritize_misconceptions(student_id, concept, k=3):
    """
    Order catalog misconceptions for this concept:
      (a) ids this student chose before, most frequent first
          (question_attempts.misconception_id)
      (b) ids never offered to this student (offered ids come from
          option_misconception_ids stored in questions.tags_json joined
          with student_question_history)
      (c) the rest, deterministic tie-break (alphabetical)

    Returns list of up to k misconception IDs.
    """
    catalog = misconceptions_for(concept)
    if not catalog:
        return []

    all_mids = [m["id"] for m in catalog]

    if not student_id:
        return sorted(all_mids)[:k]

    chose_counts = collections.defaultdict(int)
    offered_mids = set()

    try:
        conn = get_db()

        # (a) Student chose before from question_attempts
        cur = conn.execute(
            """SELECT qa.misconception_id, COUNT(*) as cnt
               FROM question_attempts qa
               JOIN quiz_results qr ON qa.quiz_result_id = qr.id
               WHERE qr.student_id = ? AND qa.misconception_id IS NOT NULL
               GROUP BY qa.misconception_id""",
            (student_id,),
        )
        for row in cur.fetchall():
            mid = row["misconception_id"]
            if mid in all_mids:
                chose_counts[mid] += int(row["cnt"])

        # Also check student_question_history for chosen misconceptions
        cur2 = conn.execute(
            """SELECT misconception_id, COUNT(*) as cnt
               FROM student_question_history
               WHERE student_id = ? AND misconception_id IS NOT NULL
               GROUP BY misconception_id""",
            (student_id,),
        )
        for row in cur2.fetchall():
            mid = row["misconception_id"]
            if mid in all_mids and mid not in chose_counts:
                chose_counts[mid] += int(row["cnt"])

        # (b) Offered IDs from questions.tags_json joined with student_question_history
        cur3 = conn.execute(
            """SELECT q.tags_json
               FROM student_question_history sqh
               JOIN questions q ON sqh.question_id = q.id
               WHERE sqh.student_id = ?""",
            (student_id,),
        )
        for row in cur3.fetchall():
            raw_tags = row["tags_json"]
            if not raw_tags:
                continue
            try:
                parsed = json.loads(raw_tags)
                if isinstance(parsed, dict):
                    m_list = parsed.get("option_misconception_ids") or []
                    for item in m_list:
                        if item:
                            offered_mids.add(item)
            except Exception:
                pass

        conn.close()
    except Exception:
        pass

    # Grouping
    # (a) Chose before, most frequent first
    chose_before = sorted(
        [m for m in all_mids if m in chose_counts],
        key=lambda m: (-chose_counts[m], m),
    )

    # (b) Never offered to this student
    never_offered = sorted(
        [m for m in all_mids if m not in offered_mids and m not in chose_counts]
    )

    # (c) The rest
    the_rest = sorted(
        [m for m in all_mids if m not in chose_counts and m in offered_mids]
    )

    ordered = chose_before + never_offered + the_rest
    return ordered[:k]


# ─────────────────────────────────────────────────────────────
# 1.4 Group Slots
# ─────────────────────────────────────────────────────────────
def group_slots(slots):
    """
    Group blueprint slots by (concept, difficulty) so one LLM call
    produces several questions.

    Returns list of group dicts:
      [{concept, difficulty, slots, count, target_misconceptions, qtypes}, ...]
    """
    grouped = collections.OrderedDict()

    for s in slots:
        key = (s["concept"], s["difficulty"])
        if key not in grouped:
            grouped[key] = {
                "concept": s["concept"],
                "difficulty": s["difficulty"],
                "slots": [],
                "target_misconceptions": [],
                "qtypes": [],
                "count": 0,
            }
        grouped[key]["slots"].append(s)
        grouped[key]["qtypes"].append(s.get("qtype", "concept"))
        grouped[key]["count"] += 1
        for m in s.get("target_misconceptions", []):
            if m not in grouped[key]["target_misconceptions"]:
                grouped[key]["target_misconceptions"].append(m)

    return list(grouped.values())
