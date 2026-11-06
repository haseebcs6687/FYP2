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
import math
import random
import re
import struct

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

# Regex to detect explanation referring directly to option letters/numbers or positional wording (Phase 4C)
_OPTION_LABEL_RE = re.compile(
    r"\b(?:option|choice)\s*(?:#?\s*[1-4]|[A-Da-d])\b|"
    r"\([A-Da-d1-4]\)|"
    r"\b[A-Da-d]\s+is\s+(?:the\s+)?(?:correct|right|wrong|incorrect|best|answer)\b|"
    r"\b(?:the\s+)?(?:first|second|third|fourth|last)\s+(?:option|choice)\b|"
    r"\boption\s*\([A-Da-d1-4]\)\b|"
    r"\bthe\s+former\b|"
    r"\bthe\s+latter\b|"
    r"\bthe\s+one\s+(?:above|below)\b",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────
# 1.1 Normalization & Validation
# ─────────────────────────────────────────────────────────────
def normalize_question(raw, concept, difficulty, is_live=False):
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

    When is_live is True (or raw['is_live'] / raw['origin'] == 'live'):
      Enforces Phase 9 live generation bias guard gates:
        - len(correct option) > 1.03 x len(longest wrong option) and strictly longest -> 'correct_option_too_long'
        - >=2 wrong options contain an absolute word while correct does not -> 'absolute_word_bias'
    Otherwise (standard structural normalization):
        - len(correct option) > 1.50 x len(longest wrong option) -> 'correct_option_too_long'

    Returns (record, None) or (None, reject_reason).
    """
    if not isinstance(raw, dict):
        return None, "raw_not_a_dict"

    live_flag = bool(is_live or raw.get("is_live") or raw.get("origin") in ("live", "generated"))

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

    # Length ratio gate
    len_correct = len(cleaned_options[correct])
    wrong_lens = [len(cleaned_options[i]) for i in range(4) if i != correct]
    max_wrong = max(wrong_lens) if wrong_lens else 0
    if live_flag:
        if max_wrong > 0 and len_correct > max_wrong and len_correct > 1.03 * max_wrong:
            return None, "correct_option_too_long"
    else:
        if max_wrong > 0 and len_correct > 1.50 * max_wrong:
            return None, "correct_option_too_long"

    # Phase 9 live generation bias gate: absolute words
    if live_flag:
        abs_pattern = re.compile(r"\b(always|never|only|automatically|all|every|any)\b", re.IGNORECASE)
        wrong_abs_count = sum(1 for i in range(4) if i != correct and abs_pattern.search(cleaned_options[i]))
        correct_has_abs = bool(abs_pattern.search(cleaned_options[correct]))
        if wrong_abs_count >= 2 and not correct_has_abs:
            return None, "absolute_word_bias"

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

    # Gate: Reject if wrong options with null id are more than 2
    null_wrong_count = sum(1 for i, mid in enumerate(validated_mids) if i != correct and mid is None)
    if null_wrong_count > 2:
        return None, "too_many_null_misconceptions"

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
      <0.40 Easy, 0.40-0.70 Medium, >0.70 Hard (or <40, 40-70, >70 if percentage), unknown -> Easy.
    """
    mastery = get_concept_mastery(student_id, concept)
    if mastery is None:
        return "Easy"
    if mastery > 1.0:
        if mastery < 40.0:
            return "Easy"
        if mastery <= 70.0:
            return "Medium"
        return "Hard"
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


# ─────────────────────────────────────────────────────────────
# 1.25 Probe Quiz Helpers (Phase 5C)
# ─────────────────────────────────────────────────────────────
def _is_concept_fully_probed(student_id, concept, conn=None):
    """
    Returns True if every catalog misconception of the concept has been
    OFFERED >= 2 times to this student.
    """
    catalog = misconceptions_for(concept)
    if not catalog:
        return True
    if not student_id:
        return False

    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True

    try:
        cur = conn.execute(
            """SELECT qa.offered_misconceptions, qa.misconception_id
               FROM question_attempts qa
               JOIN quiz_results qr ON qa.quiz_result_id = qr.id
               WHERE qr.student_id = ?""",
            (student_id,),
        )
        offer_counts = collections.defaultdict(int)
        for row in cur.fetchall():
            raw = row["offered_misconceptions"]
            found_mids = set()
            if raw:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, list):
                        for mid in parsed:
                            if mid:
                                found_mids.add(mid)
                except Exception:
                    pass
            chosen = row["misconception_id"]
            if chosen:
                found_mids.add(chosen)
            for mid in found_mids:
                offer_counts[mid] += 1

        for m in catalog:
            if offer_counts.get(m["id"], 0) < 2:
                return False
        return True
    except Exception:
        return False
    finally:
        if close_conn:
            conn.close()


def _select_probe_concept(student_id):
    """
    Lowest-mastery concept that has >= 2 attempts and is not yet fully probed,
    else the lowest-mastery concept overall.
    """
    if not student_id:
        return ENTRY_CONCEPT

    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT concept, mastery, attempts
               FROM concept_mastery
               WHERE student_id = ?
               ORDER BY mastery ASC, attempts DESC""",
            (student_id,),
        ).fetchall()

        # 1. Concept with >= 2 attempts and not yet fully probed
        for r in rows:
            c = r["concept"]
            att = int(r["attempts"] or 0)
            if c in CONCEPTS and att >= 2:
                if not _is_concept_fully_probed(student_id, c, conn=conn):
                    conn.close()
                    return c

        # 2. Any concept not yet fully probed
        for r in rows:
            c = r["concept"]
            if c in CONCEPTS:
                if not _is_concept_fully_probed(student_id, c, conn=conn):
                    conn.close()
                    return c

        # 3. Lowest-mastery concept overall
        for r in rows:
            c = r["concept"]
            if c in CONCEPTS:
                conn.close()
                return c

        conn.close()
    except Exception:
        pass

    fc = _foundational_concepts()
    return fc[0] if fc else ENTRY_CONCEPT


def _prioritize_probe_targets(student_id, concept):
    """
    All catalog misconceptions of concept ordered by priority:
      1. chosen before by this student first (count descending)
      2. never offered
      3. fewest offers ascending
      Deterministic tie-break (alphabetical).
    """
    catalog = misconceptions_for(concept)
    if not catalog:
        return []

    all_mids = [m["id"] for m in catalog]
    if not student_id:
        return sorted(all_mids)

    chose_counts = collections.defaultdict(int)
    offer_counts = collections.defaultdict(int)

    try:
        conn = get_db()
        cur = conn.execute(
            """SELECT qa.misconception_id, qa.offered_misconceptions
               FROM question_attempts qa
               JOIN quiz_results qr ON qa.quiz_result_id = qr.id
               WHERE qr.student_id = ?""",
            (student_id,),
        )
        for row in cur.fetchall():
            mid = row["misconception_id"]
            if mid and mid in all_mids:
                chose_counts[mid] += 1
            raw = row["offered_misconceptions"]
            found_in_row = set()
            if raw:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, list):
                        for m in parsed:
                            if m and m in all_mids:
                                found_in_row.add(m)
                except Exception:
                    pass
            if mid and mid in all_mids:
                found_in_row.add(mid)
            for m in found_in_row:
                offer_counts[m] += 1
        conn.close()
    except Exception:
        pass

    def sort_key(m):
        chosen = chose_counts.get(m, 0)
        offered = offer_counts.get(m, 0)
        if chosen > 0:
            return (1, -chosen, offered, m)
        elif offered == 0:
            return (2, 0, 0, m)
        else:
            return (3, 0, offered, m)

    return sorted(all_mids, key=sort_key)


def _distribute_probe_targets(ordered_targets, n):
    """
    Distribute targets across n slots greedily so that each slot carries up to 3
    targets NOT yet carried by earlier slots; wrap around when exhausted.
    Guarantees no target is repeated before all are used once.
    """
    if not ordered_targets:
        return [[] for _ in range(n)]

    chunks = []
    L = len(ordered_targets)
    for i in range(0, L, 3):
        chunks.append(ordered_targets[i : i + 3])

    num_chunks = len(chunks)
    slots_targets = []
    for i in range(n):
        slots_targets.append(list(chunks[i % num_chunks]))

    return slots_targets


def _probe_qtype_distribution(n):
    """
    Mostly 'concept' with at most 2 code-based slots.
    """
    if n <= 2:
        return ["concept"] * n
    if n == 3:
        return ["concept", "code_output", "concept"]
    types = ["concept"] * n
    types[2] = "code_output"
    types[min(5, n - 1)] = "code_output"
    return types


def build_blueprint(kind="practice", student_id=None, concepts=None, n=None, difficulty=None, concept=None):
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
      'probe':
        concept-focused misconception sweep with relaxed difficulty.
        Target concept is given or student's lowest-mastery unprobed concept.
        n slots (default 8) carrying catalog misconceptions greedily distributed.
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

    if kind == "probe":
        target_concept = concept or (concepts[0] if (concepts and isinstance(concepts, (list, tuple))) else concepts)
        if not target_concept or target_concept not in CONCEPTS:
            target_concept = _select_probe_concept(student_id)

        slot_count = n if (isinstance(n, int) and n > 0) else 8
        slot_diff = difficulty or default_difficulty_for_concept(student_id, target_concept)

        ordered_targets = _prioritize_probe_targets(student_id, target_concept)
        targets_per_slot = _distribute_probe_targets(ordered_targets, slot_count)
        qtypes = _probe_qtype_distribution(slot_count)

        for i in range(slot_count):
            slots.append({
                "concept": target_concept,
                "difficulty": slot_diff,
                "relax_difficulty": True,
                "qtype": qtypes[i],
                "target_misconceptions": targets_per_slot[i],
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


# ─────────────────────────────────────────────────────────────
# 1.5 Novelty & Deduplication (Phase 4B)
# ─────────────────────────────────────────────────────────────
_DEDUPE_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize_for_dedupe(text):
    return [t for t in _DEDUPE_TOKEN_RE.findall((text or "").lower()) if len(t) > 1]


def token_jaccard(text1, text2):
    s1 = set(tokenize_for_dedupe(text1))
    s2 = set(tokenize_for_dedupe(text2))
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def serialize_embedding(vec):
    """Serialize float list into float32 binary buffer."""
    if not vec:
        return None
    try:
        return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])
    except Exception:
        return None


def deserialize_embedding(blob):
    """Deserialize float32 binary buffer (or json string) into float list."""
    if not blob:
        return None
    if isinstance(blob, (list, tuple)):
        return [float(x) for x in blob]
    if isinstance(blob, str):
        try:
            return [float(x) for x in json.loads(blob)]
        except Exception:
            return None
    try:
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob))
    except Exception:
        try:
            return [float(x) for x in json.loads(blob.decode("utf-8"))]
        except Exception:
            return None


def cosine_similarity(v1, v2):
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 <= 0.0 or n2 <= 0.0:
        return 0.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))


def get_student_seen_questions(student_id):
    """Retrieve stem, correct option, and embedding for questions this student has seen."""
    if not student_id:
        return []
    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT q.id, q.question_text, q.options_json, q.correct_index, q.embedding
               FROM questions q
               JOIN student_question_history sqh ON q.id = sqh.question_id
               WHERE sqh.student_id = ?""",
            (student_id,),
        ).fetchall()
        conn.close()
        seen = []
        for r in rows:
            q_text = str(r["question_text"] or "").strip()
            opts = []
            try:
                opts = json.loads(r["options_json"] or "[]")
            except Exception:
                pass
            c_idx = int(r["correct_index"] or 0)
            c_text = str(opts[c_idx] if (0 <= c_idx < len(opts)) else "").strip()
            emb = deserialize_embedding(r["embedding"])
            seen.append({
                "id": r["id"],
                "text": f"{q_text}\n{c_text}".strip(),
                "embedding": emb,
            })
        return seen
    except Exception:
        return []


def check_question_novelty(
    question_record,
    accepted_in_quiz,
    student_id=None,
    ref_questions=None,
    embedder=None,
    cache=None,
    prior_questions=None,
):
    """
    Quality gate 5: Novelty & Deduplication.
    - Embeds stem + correct option with active embedder (and cache).
    - Stores vector in question_record['embedding'].
    - Rejects if cosine >= 0.88 against same quiz (and prior_questions).
    - Rejects if cosine >= 0.88 against student history.
    - Rejects if cosine >= 0.93 against bank reference questions.
    - Lexical fallback if embedder unavailable (hash match or Jaccard >= 0.80).
    Returns (ok: bool, reason: str or None, dedupe_mode: 'vector' | 'lexical').
    """
    stem = str(question_record.get("question") or "").strip()
    options = question_record.get("options") or []
    c_idx = int(question_record.get("correct", 0))
    c_opt = options[c_idx] if (isinstance(options, list) and 0 <= c_idx < len(options)) else ""
    if isinstance(c_opt, dict):
        c_opt = c_opt.get("text", "")
    c_text = str(c_opt).strip()
    stem_and_answer = f"{stem}\n{c_text}".strip()

    # Determine embedder availability
    active_embedder = embedder
    if active_embedder is None:
        try:
            from rag.embedder import get_embedder
            active_embedder = get_embedder(quiet=True)
        except Exception:
            active_embedder = None
    elif active_embedder is False:
        active_embedder = None

    active_cache = cache
    if active_cache is None and active_embedder is not None:
        try:
            from rag.embedding_cache import EmbeddingCache
            active_cache = EmbeddingCache()
        except Exception:
            active_cache = None

    if active_embedder is not None:
        try:
            vector = question_record.get("embedding")
            if not vector:
                sig = active_embedder.signature()
                sha1 = hashlib.sha1(stem_and_answer.encode("utf-8")).hexdigest()
                hit = active_cache.get_many(sig, [sha1]) if active_cache else {}
                if sha1 in hit:
                    vector = hit[sha1]
                else:
                    vector = active_embedder.embed_one(stem_and_answer)
                    if active_cache:
                        active_cache.put_many(sig, [(sha1, vector)])
                question_record["embedding"] = vector

            # (a) Check against same quiz and prior questions
            pool = list(accepted_in_quiz or []) + list(prior_questions or [])
            for other_q in pool:
                other_vec = other_q.get("embedding")
                if other_vec:
                    cos = cosine_similarity(vector, other_vec)
                    if cos >= 0.88:
                        return False, "duplicate_in_quiz", "vector"

            # (b) Check against student history
            seen_list = get_student_seen_questions(student_id)
            for seen in seen_list:
                seen_vec = seen.get("embedding")
                if not seen_vec and seen.get("text"):
                    s_sha1 = hashlib.sha1(seen["text"].encode("utf-8")).hexdigest()
                    s_hit = active_cache.get_many(sig, [s_sha1]) if active_cache else {}
                    if s_sha1 in s_hit:
                        seen_vec = s_hit[s_sha1]
                    else:
                        try:
                            seen_vec = active_embedder.embed_one(seen["text"])
                            if active_cache:
                                active_cache.put_many(sig, [(s_sha1, seen_vec)])
                        except Exception:
                            seen_vec = None
                if seen_vec:
                    cos = cosine_similarity(vector, seen_vec)
                    if cos >= 0.88:
                        return False, "already_seen_by_student", "vector"

            # (c) Check against bank reference questions
            for rq in (ref_questions or []):
                rq_text = rq.get("question") or rq.get("question_text", "")
                rq_opts = rq.get("options") or []
                rq_c = rq.get("correct") or rq.get("correct_index", 0)
                rq_c_opt = rq_opts[rq_c] if (isinstance(rq_opts, list) and 0 <= rq_c < len(rq_opts)) else ""
                if isinstance(rq_c_opt, dict):
                    rq_c_opt = rq_c_opt.get("text", "")
                rq_stem_ans = f"{rq_text}\n{rq_c_opt}".strip()
                r_sha1 = hashlib.sha1(rq_stem_ans.encode("utf-8")).hexdigest()
                r_hit = active_cache.get_many(sig, [r_sha1]) if active_cache else {}
                if r_sha1 in r_hit:
                    rq_vec = r_hit[r_sha1]
                else:
                    try:
                        rq_vec = active_embedder.embed_one(rq_stem_ans)
                        if active_cache:
                            active_cache.put_many(sig, [(r_sha1, rq_vec)])
                    except Exception:
                        rq_vec = None
                if rq_vec:
                    cos = cosine_similarity(vector, rq_vec)
                    if cos >= 0.93:
                        return False, "bank_reference_copy", "vector"

            return True, None, "vector"
        except Exception:
            # If embedding fails mid-process, fall through to lexical
            pass

    # ── Lexical Fallback ──
    norm_hash = hashlib.sha256(" ".join(stem_and_answer.lower().split()).encode("utf-8")).hexdigest()

    # Compare against same quiz
    pool = list(accepted_in_quiz or []) + list(prior_questions or [])
    for other_q in pool:
        o_stem = other_q.get("question", "")
        o_opts = other_q.get("options", [])
        o_c = other_q.get("correct", 0)
        o_c_text = o_opts[o_c] if (isinstance(o_opts, list) and 0 <= o_c < len(o_opts)) else ""
        if isinstance(o_c_text, dict):
            o_c_text = o_c_text.get("text", "")
        o_text = f"{o_stem}\n{o_c_text}".strip()
        o_hash = hashlib.sha256(" ".join(o_text.lower().split()).encode("utf-8")).hexdigest()
        if norm_hash == o_hash:
            return False, "duplicate_in_quiz", "lexical"
        if token_jaccard(stem_and_answer, o_text) >= 0.80:
            return False, "duplicate_in_quiz", "lexical"

    # Compare against student history
    seen_list = get_student_seen_questions(student_id)
    for seen in seen_list:
        s_text = seen.get("text", "")
        s_hash = hashlib.sha256(" ".join(s_text.lower().split()).encode("utf-8")).hexdigest()
        if norm_hash == s_hash:
            return False, "already_seen_by_student", "lexical"
        if token_jaccard(stem_and_answer, s_text) >= 0.80:
            return False, "already_seen_by_student", "lexical"

    # Compare against bank reference questions
    for rq in (ref_questions or []):
        rq_text = rq.get("question") or rq.get("question_text", "")
        rq_opts = rq.get("options") or []
        rq_c = rq.get("correct") or rq.get("correct_index", 0)
        rq_c_opt = rq_opts[rq_c] if (isinstance(rq_opts, list) and 0 <= rq_c < len(rq_opts)) else ""
        if isinstance(rq_c_opt, dict):
            rq_c_opt = rq_c_opt.get("text", "")
        r_text = f"{rq_text}\n{rq_c_opt}".strip()
        r_hash = hashlib.sha256(" ".join(r_text.lower().split()).encode("utf-8")).hexdigest()
        if norm_hash == r_hash:
            return False, "bank_reference_copy", "lexical"
        if token_jaccard(stem_and_answer, r_text) >= 0.80:
            return False, "bank_reference_copy", "lexical"

    return True, None, "lexical"


# ─────────────────────────────────────────────────────────────
# 1.6 Verified Pool Selection (Phase 4C)
# ─────────────────────────────────────────────────────────────
def select_from_pool(slots, student_id=None, seed=None):
    """
    Select questions from the verified active question pool to fulfill blueprint slots.
    Criteria:
      - pool_status == 'active' and verified == 1
      - Exact concept and difficulty match
      - Not yet seen by the student (student_question_history)
      - Prefers slot's qtype, else any qtype
      - Prefers higher target misconception coverage
      - Tie-breaks by lowest times_served then seeded random
      - Discards candidates with within-quiz cosine similarity >= 0.88 (or Jaccard >= 0.80)
    Returns:
      (served_questions: list, unfilled_slots: list)
    """
    if not slots:
        return [], []

    try:
        conn = get_db()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
        if "pool_status" not in cols or "verified" not in cols:
            conn.close()
            return [], list(slots)

        seen_qids = set()
        if student_id:
            s_rows = conn.execute(
                "SELECT DISTINCT question_id FROM student_question_history WHERE student_id = ?",
                (student_id,),
            ).fetchall()
            seen_qids = {r["question_id"] for r in s_rows if r["question_id"]}

        query = """
            SELECT id, concept, facet, difficulty, qtype, question_text, options_json,
                   correct_index, explanation, tags_json, source, model, verified,
                   text_hash, embedding, origin, pool_status, difficulty_verified,
                   times_served, times_correct
            FROM questions
            WHERE pool_status = 'active' AND verified = 1
        """
        rows = conn.execute(query).fetchall()
        conn.close()
    except Exception:
        return [], list(slots)

    if not rows:
        return [], list(slots)

    records = []
    for r in rows:
        opts = []
        try:
            opts = json.loads(r["options_json"] or "[]")
        except Exception:
            pass

        t_data = {}
        try:
            t_data = json.loads(r["tags_json"] or "{}")
        except Exception:
            pass

        emb = deserialize_embedding(r["embedding"])
        r_keys = r.keys()
        rec = {
            "question_id": r["id"],
            "id": r["id"],
            "question": r["question_text"],
            "options": opts,
            "correct": int(r["correct_index"] or 0),
            "explanation": r["explanation"] or "",
            "concept": r["concept"],
            "concept_tags": t_data.get("tags", [r["concept"]]),
            "difficulty": r["difficulty"],
            "qtype": r["qtype"] or "concept",
            "option_misconception_ids": t_data.get("option_misconception_ids", [None] * 4),
            "facet": r["facet"],
            "embedding": emb,
            "verified": r["verified"],
            "origin": r["origin"] if "origin" in r_keys else "generated",
            "pool_status": r["pool_status"] if "pool_status" in r_keys else "active",
            "difficulty_verified": r["difficulty_verified"] if "difficulty_verified" in r_keys else None,
            "times_served": int(r["times_served"] or 0),
            "served_from": "pool",
        }
        records.append(rec)

    served = []
    unfilled = []
    used_qids = set()
    rng = random.Random(seed)

    for slot in slots:
        s_concept = slot.get("concept")
        s_diff = slot.get("difficulty")
        s_qtype = slot.get("qtype")
        s_targets = set(slot.get("target_misconceptions") or [])

        # Candidates matching concept and difficulty
        candidates = [
            c for c in records
            if c["concept"] == s_concept
            and c["difficulty"] == s_diff
            and c["id"] not in seen_qids
            and c["id"] not in used_qids
        ]

        if not candidates:
            unfilled.append(slot)
            continue

        scored_candidates = []
        for c in candidates:
            # Check near-duplicates against already served
            is_dup = False
            c_stem = c["question"]
            c_opts = c["options"]
            c_corr = c["correct"]
            c_ans = c_opts[c_corr] if (0 <= c_corr < len(c_opts)) else ""
            c_full_text = f"{c_stem}\n{c_ans}".strip()

            for s_q in served:
                if c.get("embedding") and s_q.get("embedding"):
                    if cosine_similarity(c["embedding"], s_q["embedding"]) >= 0.88:
                        is_dup = True
                        break
                else:
                    s_stem = s_q["question"]
                    s_opts = s_q["options"]
                    s_corr = s_q["correct"]
                    s_ans = s_opts[s_corr] if (0 <= s_corr < len(s_opts)) else ""
                    s_full_text = f"{s_stem}\n{s_ans}".strip()
                    if token_jaccard(c_full_text, s_full_text) >= 0.80:
                        is_dup = True
                        break

            if is_dup:
                continue

            qtype_score = 1 if (s_qtype and c["qtype"] == s_qtype) else 0
            c_mids = set(c.get("option_misconception_ids") or [])
            c_mids.discard(None)
            coverage = len(s_targets & c_mids)
            rand_tie = rng.random()

            sort_key = (-qtype_score, -coverage, c["times_served"], rand_tie)
            scored_candidates.append((sort_key, c))

        if not scored_candidates:
            unfilled.append(slot)
            continue

        scored_candidates.sort(key=lambda item: item[0])
        chosen = scored_candidates[0][1]
        served.append(chosen)
        used_qids.add(chosen["id"])

    return served, unfilled


# ─────────────────────────────────────────────────────────────
# 1.7 Probe Set Selection (Phase 5C)
# ─────────────────────────────────────────────────────────────
def select_probe_set(slots, student_id=None, seed=None):
    """
    Select questions from the verified active question pool to fulfill probe slots.
    Greedy coverage:
      - Concept match (same concept)
      - Never serve questions the student has seen (student_question_history)
      - Covers the most still-uncovered target misconceptions (weighted by priority)
      - Tie-break by closeness to slot difficulty: exact (0), adjacent (1), any (2)
      - Then lowest times_served, then seeded random tie-break
      - Within-quiz dedupe (embedding cosine >= 0.88 or token-Jaccard fallback)
    Slots that cannot be filled are returned as unfilled WITH their uncovered targets.
    Returns:
      (served_questions: list, unfilled_slots: list)
    """
    if not slots:
        return [], []

    try:
        conn = get_db()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
        if "pool_status" not in cols or "verified" not in cols:
            conn.close()
            return [], list(slots)

        seen_qids = set()
        if student_id:
            s_rows = conn.execute(
                "SELECT DISTINCT question_id FROM student_question_history WHERE student_id = ?",
                (student_id,),
            ).fetchall()
            seen_qids = {r["question_id"] for r in s_rows if r["question_id"]}

        query = """
            SELECT id, concept, facet, difficulty, qtype, question_text, options_json,
                   correct_index, explanation, tags_json, source, model, verified,
                   text_hash, embedding, origin, pool_status, difficulty_verified,
                   times_served, times_correct
            FROM questions
            WHERE pool_status = 'active' AND verified = 1
        """
        rows = conn.execute(query).fetchall()
        conn.close()
    except Exception:
        return [], list(slots)

    if not rows:
        return [], list(slots)

    records = []
    for r in rows:
        opts = []
        try:
            opts = json.loads(r["options_json"] or "[]")
        except Exception:
            pass

        t_data = {}
        try:
            t_data = json.loads(r["tags_json"] or "{}")
        except Exception:
            pass

        emb = deserialize_embedding(r["embedding"])
        r_keys = r.keys()
        rec = {
            "question_id": r["id"],
            "id": r["id"],
            "question": r["question_text"],
            "options": opts,
            "correct": int(r["correct_index"] or 0),
            "explanation": r["explanation"] or "",
            "concept": r["concept"],
            "concept_tags": t_data.get("tags", [r["concept"]]),
            "difficulty": r["difficulty"],
            "qtype": r["qtype"] or "concept",
            "option_misconception_ids": t_data.get("option_misconception_ids", [None] * 4),
            "facet": r["facet"],
            "embedding": emb,
            "verified": r["verified"],
            "origin": r["origin"] if "origin" in r_keys else "generated",
            "pool_status": r["pool_status"] if "pool_status" in r_keys else "active",
            "difficulty_verified": r["difficulty_verified"] if "difficulty_verified" in r_keys else None,
            "times_served": int(r["times_served"] or 0),
            "served_from": "pool",
        }
        records.append(rec)

    # Collect all targets requested across slots in appearance order for priority weighting
    all_targets_ordered = []
    for s in slots:
        for t in s.get("target_misconceptions", []):
            if t not in all_targets_ordered:
                all_targets_ordered.append(t)

    num_t = len(all_targets_ordered)
    target_weights = {t: (num_t - idx) for idx, t in enumerate(all_targets_ordered)}
    still_uncovered_targets = set(all_targets_ordered)

    served = []
    unfilled = []
    used_qids = set()
    rng = random.Random(seed)

    def diff_distance(slot_diff, cand_diff):
        if not slot_diff or not cand_diff:
            return 2
        sd = str(slot_diff).capitalize()
        cd = str(cand_diff).capitalize()
        if sd == cd:
            return 0
        adj = {
            "Easy": {"Medium"},
            "Medium": {"Easy", "Hard"},
            "Hard": {"Medium"},
        }
        if cd in adj.get(sd, set()):
            return 1
        return 2

    for slot in slots:
        s_concept = slot.get("concept")
        s_diff = slot.get("difficulty")
        s_qtype = slot.get("qtype")

        # Candidates matching concept that are unseen and not used yet in this quiz
        candidates = [
            c for c in records
            if c["concept"] == s_concept
            and c["id"] not in seen_qids
            and c["id"] not in used_qids
        ]

        if not candidates:
            unfilled_targets = [t for t in slot.get("target_misconceptions", []) if t in still_uncovered_targets]
            unfilled_slot = dict(slot)
            unfilled_slot["target_misconceptions"] = unfilled_targets if unfilled_targets else list(slot.get("target_misconceptions", []))
            unfilled.append(unfilled_slot)
            continue

        scored_candidates = []
        for c in candidates:
            # Check within-quiz dedupe against already served
            is_dup = False
            c_stem = c["question"]
            c_opts = c["options"]
            c_corr = c["correct"]
            c_ans = c_opts[c_corr] if (0 <= c_corr < len(c_opts)) else ""
            c_full_text = f"{c_stem}\n{c_ans}".strip()

            for s_q in served:
                if c.get("embedding") and s_q.get("embedding"):
                    if cosine_similarity(c["embedding"], s_q["embedding"]) >= 0.88:
                        is_dup = True
                        break
                else:
                    s_stem = s_q["question"]
                    s_opts = s_q["options"]
                    s_corr = s_q["correct"]
                    s_ans = s_opts[s_corr] if (0 <= s_corr < len(s_opts)) else ""
                    s_full_text = f"{s_stem}\n{s_ans}".strip()
                    if token_jaccard(c_full_text, s_full_text) >= 0.80:
                        is_dup = True
                        break

            if is_dup:
                continue

            c_mids = set(c.get("option_misconception_ids") or [])
            c_mids.discard(None)

            # Greedy coverage: weight by still-uncovered targets covered
            uncovered_matches = c_mids & still_uncovered_targets
            coverage_weight = sum(target_weights.get(m, 1) for m in uncovered_matches)

            dist = diff_distance(s_diff, c.get("difficulty"))
            qtype_score = 1 if (s_qtype and c["qtype"] == s_qtype) else 0
            rand_tie = rng.random()

            # Sort key:
            # 1. higher coverage_weight first (-coverage_weight)
            # 2. closeness to slot difficulty (0 exact, 1 adjacent, 2 any)
            # 3. preferred qtype (-qtype_score)
            # 4. lowest times_served
            # 5. random tie-break
            sort_key = (-coverage_weight, dist, -qtype_score, c["times_served"], rand_tie)
            scored_candidates.append((sort_key, c))

        if not scored_candidates:
            unfilled_targets = [t for t in slot.get("target_misconceptions", []) if t in still_uncovered_targets]
            unfilled_slot = dict(slot)
            unfilled_slot["target_misconceptions"] = unfilled_targets if unfilled_targets else list(slot.get("target_misconceptions", []))
            unfilled.append(unfilled_slot)
            continue

        scored_candidates.sort(key=lambda item: item[0])
        chosen = scored_candidates[0][1]
        served.append(chosen)
        used_qids.add(chosen["id"])

        chosen_mids = set(chosen.get("option_misconception_ids") or [])
        chosen_mids.discard(None)
        still_uncovered_targets.difference_update(chosen_mids)

    return served, unfilled

