"""
=============================================================================
EduGen - Adaptive Content Agent Study Planner (core/study_planner.py)
=============================================================================
Pure algorithmic planner generating ordered, prerequisite-closed,
misconception-targeted study plans from Performance Analysis Agent reports.

Pure functions:
  - generate_study_plan(report, size_cap=7, strong_threshold=70.0)
  - check_coverage(plan, report, strong_threshold=70.0)
  - format_step_prompt(step, preceding_titles=None, user_note=None)

No DB, no Flask, no external LLM calls.
=============================================================================
"""

from collections import defaultdict, deque
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from core.concepts import (
    CONCEPTS,
    ENTRY_CONCEPT,
    LEARNING_ORDER,
    MODULES,
    PREREQUISITES,
    concept_title,
    learning_order,
    module_of,
    prerequisites_of,
)
from core.misconceptions import MISCONCEPTIONS


# ─────────────────────────────────────────────────────────────────────────────
# 1. HELPER EXTRACTION FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _extract_tag(item: Any) -> str:
    """Normalize a concept item that might be a string or a dict."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("concept_tag") or item.get("concept") or item.get("tag") or ""
    return str(item)


def _get_concept_mastery(concept: str, report: Dict[str, Any]) -> float:
    """Extract student mastery percentage for a concept, defaulting to 30.0% (unproven prior)."""
    stats = report.get("concept_stats", {})
    if concept in stats and isinstance(stats[concept], dict):
        m = stats[concept].get("mastery")
        if m is not None:
            return float(m)

    # Check weak / moderate / strong buckets if concept_stats is sparse
    for item in report.get("weak_topics", []):
        if _extract_tag(item) == concept:
            return 25.0
    for item in report.get("moderate_topics", []):
        if _extract_tag(item) == concept:
            return 55.0
    for item in report.get("strong_topics", []):
        if _extract_tag(item) == concept:
            return 85.0

    return 30.0


def _has_attempt_data(concept: str, report: Dict[str, Any]) -> bool:
    """True if student has at least 1 attempted question on this concept."""
    stats = report.get("concept_stats", {})
    if concept in stats and isinstance(stats[concept], dict):
        attempts = stats[concept].get("attempts", 0)
        return attempts > 0
    return False


def _get_concept_active_misconceptions(concept: str, report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get active misconceptions belonging to a concept from report."""
    active = report.get("misconceptions", {}).get("active", [])
    out = []
    for m in active:
        m_concept = m.get("concept")
        if not m_concept:
            mid = m.get("misconception_id", "")
            m_concept = mid.split("/")[0] if "/" in mid else ""
        if m_concept == concept:
            out.append(m)
    return out


def _get_concept_suspected_misconceptions(concept: str, report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get suspected misconceptions belonging to a concept from report."""
    suspected = report.get("misconceptions", {}).get("suspected", [])
    out = []
    for m in suspected:
        m_concept = m.get("concept")
        if not m_concept:
            mid = m.get("misconception_id", "")
            m_concept = mid.split("/")[0] if "/" in mid else ""
        if m_concept == concept:
            out.append(m)
    return out


def _get_concept_weak_facets(concept: str, report: Dict[str, Any]) -> List[str]:
    """Get list of weak facet names for a concept from facet_map."""
    facet_map = report.get("facet_map", {})
    c_facets = facet_map.get(concept, {})
    weak = []
    for f_name, f_data in c_facets.items():
        if isinstance(f_data, dict) and f_data.get("weak"):
            weak.append(f_name)
    return weak


def _detect_concept_skill_gap(concept: str, report: Dict[str, Any]) -> Optional[str]:
    """Check if concept or its module has an identified skill gap."""
    sp = report.get("skill_profile", {})
    gaps = sp.get("skill_gaps", [])
    c_mod = module_of(concept)

    # Check module-specific skill gap
    mod_stats = sp.get("by_module", {}).get(c_mod, {})
    if mod_stats:
        c_acc = mod_stats.get("concept", {}).get("accuracy", 0.0)
        co_acc = mod_stats.get("code_output", {}).get("accuracy", 0.0)
        bf_acc = mod_stats.get("bug_find", {}).get("accuracy", 0.0)
        c_att = mod_stats.get("concept", {}).get("attempts", 0)
        co_att = mod_stats.get("code_output", {}).get("attempts", 0)
        bf_att = mod_stats.get("bug_find", {}).get("attempts", 0)

        if c_att >= 2 and co_att >= 2 and (c_acc - co_acc) >= 25.0:
            return "Knows theory but struggles with code tracing (code_output)"
        if c_att >= 2 and bf_att >= 2 and (c_acc - bf_acc) >= 25.0:
            return "Knows theory but struggles with bug finding (bug_find)"

    # Fallback to general skill gap if any code tracing gap exists
    for g in gaps:
        if "code tracing" in g.lower() or "code_output" in g.lower():
            return "Struggles with code tracing"
        if "bug" in g.lower():
            return "Struggles with bug finding"

    return None


def frontier(report: Dict[str, Any], strong_threshold: float = 70.0) -> List[str]:
    """
    1. Real Advance:
    Concepts in core.concepts.learning_order() that are NOT mastered
    (no data, or mastery < strong_threshold) AND whose direct prerequisites
    are all mastered (has attempt data AND mastery >= strong_threshold).
    """
    lo = learning_order()
    front = []
    for c in lo:
        if c not in CONCEPTS:
            continue
        has_data = _has_attempt_data(c, report)
        mst = _get_concept_mastery(c, report)
        # Must not be mastered
        if has_data and mst >= strong_threshold:
            continue

        prereqs = PREREQUISITES.get(c, [])
        all_mastered = True
        for p in prereqs:
            p_has_data = _has_attempt_data(p, report)
            p_mst = _get_concept_mastery(p, report)
            if not (p_has_data and p_mst >= strong_threshold):
                all_mastered = False
                break

        if all_mastered:
            front.append(c)

    return front


def plan_step_concepts(step: Dict[str, Any]) -> List[str]:
    """
    4. Sentinel Cleanup:
    Extract the real concept tags targeted by a plan step.
    For reevaluation steps, extracts focus['concepts'].
    For probe or single-concept steps, extracts [concept].
    """
    focus = step.get("focus") or {}
    if isinstance(focus, dict):
        if "concepts" in focus and isinstance(focus["concepts"], list):
            return [c for c in focus["concepts"] if c]
        if "concept" in focus and focus["concept"]:
            return [focus["concept"]]

    c = step.get("concept")
    if c and c != "all-plan-concepts":
        return [c]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. SEED IDENTIFICATION & PREREQUISITE CLOSURE
# ─────────────────────────────────────────────────────────────────────────────

def identify_seeds(report: Dict[str, Any], strong_threshold: float = 70.0) -> List[Dict[str, Any]]:
    """
    2.1 Identify seed concepts:
      - Weak concepts (mastery < 40.0)
      - Concepts with ACTIVE misconceptions where mastery < strong_threshold
      - Up to 2 concepts due for review
      - Concepts with an identified skill gap
    Returns list of dicts: {"concept": str, "kind": str, "seed_reasons": [str]}
    """
    seeds_dict: Dict[str, Dict[str, Any]] = {}

    def add_seed(concept: str, kind: str, reason: str):
        if not concept or concept not in CONCEPTS:
            return
        if concept not in seeds_dict:
            seeds_dict[concept] = {
                "concept": concept,
                "kind": kind,
                "reasons": [reason],
            }
        else:
            seeds_dict[concept]["reasons"].append(reason)
            # Prioritize 'weak' over 'review'
            if kind == "weak":
                seeds_dict[concept]["kind"] = kind

    # 1. Weak concepts
    for item in report.get("weak_topics", []):
        tag = _extract_tag(item)
        if tag:
            m = _get_concept_mastery(tag, report)
            add_seed(tag, "weak", f"Low mastery ({m:.1f}%) in weak topics")

    # 2. Concepts with ACTIVE misconceptions (mastery < strong_threshold)
    active_mis = report.get("misconceptions", {}).get("active", [])
    for m in active_mis:
        tag = m.get("concept") or (m.get("misconception_id", "").split("/")[0] if "/" in m.get("misconception_id", "") else "")
        if tag and tag in CONCEPTS:
            mst = _get_concept_mastery(tag, report)
            if mst < strong_threshold:
                add_seed(tag, "weak", f"Active misconception [{m.get('misconception_id')}] with mastery {mst:.1f}%")

    # 3. Up to 2 concepts due for review (only if mastery < strong_threshold so mastered concepts do not receive lesson steps)
    due_list = report.get("due_for_review", [])
    for item in due_list[:2]:
        tag = _extract_tag(item)
        if tag:
            mst = _get_concept_mastery(tag, report)
            if mst < strong_threshold:
                add_seed(tag, "review", f"Concept due for retention review (mastery {mst:.1f}% < {strong_threshold}%)")

    # 4. Concepts with skill gap findings
    sp = report.get("skill_profile", {})
    if sp.get("skill_gaps"):
        for item in (report.get("weak_topics", []) + report.get("moderate_topics", [])):
            tag = _extract_tag(item)
            if tag and _detect_concept_skill_gap(tag, report):
                add_seed(tag, "weak", "Concept exhibits a theory-vs-tracing skill gap")

    return list(seeds_dict.values())


def compute_prerequisite_closure(
    seeds: List[str],
    report: Dict[str, Any],
    strong_threshold: float = 70.0,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    2.2 Prerequisite closure via core.concepts.prerequisites_of(deep=True):
      - Include a prerequisite when its mastery < strong_threshold
      - OR when it has no data AND it is within 2 edges of a seed
      - Never include a prerequisite whose mastery is already >= strong_threshold.
    Returns: (set of all included concepts (seeds + closure), dict of prerequisite reasons)
    """
    all_concepts: Set[str] = set(seeds)
    prereq_reasons: Dict[str, str] = {}

    # Compute distance from seeds to respect 2-edge rule for unproven concepts
    dist_from_seed: Dict[str, int] = {s: 0 for s in seeds}
    queue = deque(seeds)

    while queue:
        curr = queue.popleft()
        d = dist_from_seed[curr]
        for p in PREREQUISITES.get(curr, []):
            if p not in CONCEPTS:
                continue
            if p not in dist_from_seed:
                dist_from_seed[p] = d + 1
                queue.append(p)

    # Iterative closure: include unmastered or unproven (within 2 edges) prerequisites
    changed = True
    while changed:
        changed = False
        for c in list(all_concepts):
            for p in PREREQUISITES.get(c, []):
                if p not in CONCEPTS:
                    continue
                mst = _get_concept_mastery(p, report)
                has_data = _has_attempt_data(p, report)

                # Never include a prerequisite whose mastery is already >= strong_threshold
                if has_data and mst >= strong_threshold:
                    continue

                # Include if unmastered (mastery < 70 or unproven)
                should_include = not (has_data and mst >= strong_threshold)

                if should_include and p not in all_concepts:
                    all_concepts.add(p)
                    changed = True
                    if has_data:
                        prereq_reasons[p] = f"Prerequisite for {concept_title(c)} with mastery {mst:.1f}%"
                    else:
                        prereq_reasons[p] = f"Prerequisite for {concept_title(c)} (no evidence yet, verifying)"

    return all_concepts, prereq_reasons


# ─────────────────────────────────────────────────────────────────────────────
# 3. PRIORITY FORMULA & TOPOLOGICAL SORT (KAHN)
# ─────────────────────────────────────────────────────────────────────────────

def compute_priority(concept: str, seeds: List[str], report: Dict[str, Any]) -> float:
    """
    2.3 Priority Formula:
      Priority = (100 - mastery)
               + 15 * min(top active severity, 4)
               + 10 * (number of seeds that depend on this concept)
               + 8 if due_for_review

    Documented Rationale:
      - (100 - mastery): Focuses pedagogical effort on the deepest learner deficits.
      - 15 * min(top active severity, 4): Aggressively targets active misconceptions.
      - 10 * dependents: Blocks downstream concepts until upstream foundations are solid.
      - 8 if due_for_review: Prevents retention decay without starving new learning.
    """
    mastery = _get_concept_mastery(concept, report)

    # Active misconception severity
    active_mis = _get_concept_active_misconceptions(concept, report)
    top_sev = max((float(m.get("severity", 0.0)) for m in active_mis), default=0.0)

    # Number of seeds that depend on this concept
    dep_count = 0
    for s in seeds:
        if s != concept and concept in prerequisites_of(s, deep=True):
            dep_count += 1

    # Due for review bonus
    due_bonus = 0.0
    due_list = [_extract_tag(x) for x in report.get("due_for_review", [])]
    if concept in due_list:
        due_bonus = 8.0

    priority = (100.0 - mastery) + 15.0 * min(top_sev, 4.0) + 10.0 * float(dep_count) + due_bonus
    return round(priority, 2)


def topological_sort_kahn(
    concepts: Set[str],
    priorities: Dict[str, float],
) -> List[str]:
    """
    2.4 Topological sort over selected concepts using real prerequisite edges.
    Ties broken by:
      1) Priority (descending)
      2) Module order (ascending)
      3) Canonical LEARNING_ORDER index (ascending)
    Guarantees every prerequisite precedes its dependents.
    """
    in_degree: Dict[str, int] = {c: 0 for c in concepts}
    dependents_graph: Dict[str, List[str]] = defaultdict(list)

    for c in concepts:
        direct = set(PREREQUISITES.get(c, [])) & concepts
        in_degree[c] = len(direct)
        for p in direct:
            dependents_graph[p].append(c)

    def sort_key(c: str) -> Tuple[float, int, int]:
        prio = priorities.get(c, 0.0)
        mod_id = module_of(c)
        mod_ord = MODULES.get(mod_id, {}).get("order", 999) if mod_id else 999
        lo_idx = LEARNING_ORDER.index(c) if c in LEARNING_ORDER else 999
        return (-prio, mod_ord, lo_idx)

    # Queue contains nodes with in_degree == 0
    ready = [c for c, deg in in_degree.items() if deg == 0]
    ready.sort(key=sort_key)

    ordered: List[str] = []

    while ready:
        node = ready.pop(0)
        ordered.append(node)

        for dep in dependents_graph[node]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                ready.append(dep)
                ready.sort(key=sort_key)

    if len(ordered) < len(concepts):
        # Cycle detected (or unreachable nodes): append remainder deterministically
        remaining = [c for c in concepts if c not in ordered]
        remaining.sort(key=sort_key)
        ordered.extend(remaining)

    return ordered


# ─────────────────────────────────────────────────────────────────────────────
# 4. SIZE CAP & DEFERRAL
# ─────────────────────────────────────────────────────────────────────────────

def apply_size_cap(
    ordered_concepts: List[str],
    seeds: List[str],
    priorities: Dict[str, float],
    size_cap: int = 7,
    check_cap: int = 4,
    report: Optional[Dict[str, Any]] = None,
    prereq_reasons: Optional[Dict[str, str]] = None,
) -> Tuple[List[str], List[Dict[str, Any]], Optional[str]]:
    """
    2.5 Size cap (default 7 learning steps, 4 check steps):
      - Check steps do NOT count against the 7 learning steps.
      - At most check_cap (4) check steps per plan; extra unproven prerequisites
        are deferred with 'will be verified when its dependent is reached'.
      - If learning candidates > size_cap, defer lowest-priority non-prerequisite items.
      - Retain concepts carrying ACTIVE misconceptions (and their prerequisite closures) first.
      - If closure alone exceeds the cap, keep closure and record note.
    Returns: (retained_concepts, deferred_items, closure_exceeded_note)
    """
    prereq_reasons = prereq_reasons or {}

    def is_check_candidate(c: str) -> bool:
        if report and c in prereq_reasons:
            return not _has_attempt_data(c, report)
        return False

    check_candidates = [c for c in ordered_concepts if is_check_candidate(c)]
    learning_candidates = [c for c in ordered_concepts if not is_check_candidate(c)]

    if len(learning_candidates) <= size_cap and len(check_candidates) <= check_cap:
        return ordered_concepts, [], None

    closure_note = None
    retained_learning: Set[str] = set()

    # Step 1: Retain learning candidates with ACTIVE misconceptions and their required learning prerequisites
    if report:
        active_mis_concepts = [c for c in learning_candidates if _get_concept_active_misconceptions(c, report)]
        active_sorted = sorted(active_mis_concepts, key=lambda c: priorities.get(c, 0.0), reverse=True)
        for c in active_sorted:
            needed = {c} | (set(prerequisites_of(c, deep=True)) & set(learning_candidates))
            candidate_union = retained_learning | needed
            if len(candidate_union) <= size_cap:
                retained_learning = candidate_union
            else:
                retained_learning = candidate_union
                closure_note = (
                    f"Prerequisite closure for active misconceptions in '{concept_title(c)}' requires "
                    f"{len(retained_learning)} steps, exceeding size cap of {size_cap}. Keeping closure to maintain validity."
                )

    # Step 2: Fill remaining learning capacity up to size_cap
    by_prio = sorted(
        [c for c in learning_candidates if c not in retained_learning],
        key=lambda c: priorities.get(c, 0.0),
        reverse=True,
    )

    for candidate in by_prio:
        needed = {candidate} | (set(prerequisites_of(candidate, deep=True)) & set(learning_candidates))
        candidate_union = retained_learning | needed
        if len(candidate_union) <= size_cap:
            retained_learning = candidate_union

    # Fallback if nothing was retained yet
    if not retained_learning and by_prio:
        top_seed = by_prio[0]
        retained_learning = {top_seed} | (set(prerequisites_of(top_seed, deep=True)) & set(learning_candidates))
        closure_note = f"Prerequisite closure for '{concept_title(top_seed)}' requires {len(retained_learning)} steps, exceeding size cap of {size_cap}. Keeping closure to maintain validity."

    # Step 3: Check steps for unproven prerequisites needed by retained learning
    needed_checks = set()
    for c in retained_learning:
        for p in prerequisites_of(c, deep=True):
            if p in check_candidates:
                needed_checks.add(p)

    retained_checks: Set[str] = set()
    sorted_checks = sorted(needed_checks, key=lambda c: priorities.get(c, 0.0), reverse=True)
    for c in sorted_checks[:check_cap]:
        retained_checks.add(c)

    # Build deferred list
    deferred = []
    for c in ordered_concepts:
        if c in check_candidates and c not in retained_checks:
            deferred.append({
                "concept": c,
                "title": concept_title(c),
                "priority": priorities.get(c, 0.0),
                "reason": "will be verified when its dependent is reached",
            })
        elif c in learning_candidates and c not in retained_learning:
            deferred.append({
                "concept": c,
                "title": concept_title(c),
                "priority": priorities.get(c, 0.0),
                "reason": f"Deferred to maintain plan focus (size cap: {size_cap}); priority {priorities.get(c, 0.0):.1f}",
            })

    final_retained = retained_learning | retained_checks
    final_ordered = [c for c in ordered_concepts if c in final_retained]
    return final_ordered, deferred, closure_note


# ─────────────────────────────────────────────────────────────────────────────
# 5. STEP CONSTRUCTION & PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def format_step_prompt(
    step: Dict[str, Any],
    preceding_titles: Optional[List[str]] = None,
    user_note: Optional[str] = None,
) -> str:
    """
    2.8 Deterministic learning step prompt template:
    "Teach <title> at <difficulty> level in a <style> style.
     Student evidence: <mastery>% mastery, weak facets <...>.
     Explicitly correct these misconceptions: <wrong_belief> -> <correct_idea> (one line each).
     <If skill gap:> Include <n> short code-tracing examples.
     Already covered earlier in this plan: <titles>.
     Student's additional request: <user_note or 'none'>"
    """
    title = step.get("title") or concept_title(step.get("concept", ""))
    difficulty = step.get("difficulty", "Medium")
    style = step.get("lesson_style", "detailed")
    mastery = float(step.get("mastery", 30.0))

    focus = step.get("focus") or {}
    weak_facets = focus.get("weak_facets") or []
    facets_str = ", ".join(weak_facets) if weak_facets else "none"

    misconceptions = focus.get("misconceptions") or []
    if misconceptions:
        mis_lines = []
        for m in misconceptions:
            wb = m.get("wrong_belief") or m.get("title") or "Common mistake"
            ci = m.get("correct_idea") or "Accurate OOP principle"
            mis_lines.append(f"{wb} -> {ci}")
        mis_str = "; ".join(mis_lines)
    else:
        mis_str = "none"

    skill_gap = focus.get("skill_gap")
    if skill_gap:
        if "tracing" in skill_gap.lower() or "code_output" in skill_gap.lower():
            skill_clause = "Include 3 short code-tracing examples. "
        elif "bug" in skill_gap.lower():
            skill_clause = "Include 3 short bug-finding examples. "
        else:
            skill_clause = "Include 3 targeted application examples. "
    else:
        skill_clause = ""

    preceding_titles = preceding_titles or []
    covered_str = ", ".join(preceding_titles) if preceding_titles else "none"

    clean_note = (user_note or step.get("user_note") or "").strip()
    if clean_note:
        clean_note = clean_note[:400]
    else:
        clean_note = "none"

    prompt = (
        f"Teach {title} at {difficulty} level in a {style} style. "
        f"Student evidence: {mastery:.1f}% mastery, weak facets {facets_str}. "
        f"Explicitly correct these misconceptions: {mis_str}. "
        f"{skill_clause}"
        f"Already covered earlier in this plan: {covered_str}. "
        f"Student's additional request: {clean_note}"
    )
    return prompt


def _build_learning_step(
    concept: str,
    kind: str,
    reason: str,
    priority: float,
    report: Dict[str, Any],
) -> Dict[str, Any]:
    """2.6 Construct a single learning step with calibrated difficulty, style, and focus."""
    mastery = _get_concept_mastery(concept, report)
    has_data = _has_attempt_data(concept, report)

    # Calibrated difficulty: mastery <40 Easy, 40-70 Medium, >=70 Hard
    if not has_data or mastery < 40.0:
        difficulty = "Easy"
    elif mastery < 70.0:
        difficulty = "Medium"
    else:
        difficulty = "Hard"

    # Prerequisites that are weak (<40 or unproven) start Easy
    if kind == "prerequisite" and (not has_data or mastery < 40.0):
        difficulty = "Easy"

    # Focus components
    active_mis = _get_concept_active_misconceptions(concept, report)
    susp_mis = _get_concept_suspected_misconceptions(concept, report)
    all_mis = active_mis + susp_mis
    weak_facets = _get_concept_weak_facets(concept, report)
    skill_gap = _detect_concept_skill_gap(concept, report)

    # 3. SKILL GAP DIFFICULTY:
    # A step whose only reason is a skill gap (no weak mastery, no active misconception)
    # gets difficulty at most Medium; prompt unchanged except the code-tracing instruction.
    is_only_skill_gap = (
        skill_gap is not None
        and has_data
        and mastery >= 40.0
        and len(active_mis) == 0
    )
    if is_only_skill_gap and difficulty == "Hard":
        difficulty = "Medium"

    # Lesson style: advance steps always use detailed style; otherwise simplified if < 40
    if kind == "advance":
        lesson_style = "detailed"
    else:
        lesson_style = "simplified" if mastery < 40.0 else "detailed"

    # Focus item count for est_minutes: 5 + 3 per focus item, cap 20
    focus_item_count = len(all_mis) + len(weak_facets) + (1 if skill_gap else 0)
    est_minutes = min(20, 5 + 3 * focus_item_count)

    focus_dict = {
        "misconceptions": [
            {
                "id": m.get("misconception_id"),
                "status": m.get("status", "suspected"),
                "severity": m.get("severity", 0.0),
                "wrong_belief": m.get("wrong_belief") or MISCONCEPTIONS.get(m.get("misconception_id", ""), {}).get("wrong_belief", ""),
                "correct_idea": m.get("correct_idea") or MISCONCEPTIONS.get(m.get("misconception_id", ""), {}).get("correct_idea", ""),
            }
            for m in all_mis
        ],
        "weak_facets": weak_facets,
        "skill_gap": skill_gap,
    }

    return {
        "concept": concept,
        "title": concept_title(concept),
        "module": module_of(concept),
        "kind": kind,
        "difficulty": difficulty,
        "lesson_style": lesson_style,
        "priority": priority,
        "mastery": mastery,
        "est_minutes": est_minutes,
        "reason": reason,
        "focus": focus_dict,
        "status": "pending",
        "user_note": None,
        "prompt_text": None,  # Will be populated with preceding titles
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. CLOSING STEPS & MASTER PLAN GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def generate_study_plan(
    report: Dict[str, Any],
    size_cap: int = 7,
    check_cap: int = 4,
    strong_threshold: float = 70.0,
) -> Dict[str, Any]:
    """
    Master plan generation algorithm:
      1. Cold start check (no quiz attempts -> return empty plan).
      2. Course complete check (all concepts mastered -> mixed review reevaluation).
      3. Identify seed concepts (weak, active misconceptions, review, skill gaps).
      4. Advance concepts: if no weak seeds, take up to 2 frontier concepts.
      5. Compute prerequisite closure (mastery < 70 or unproven <= 2 edges).
      6. Compute priority scores and sort topologically (Kahn).
      7. Apply size cap and create deferred items (check steps cap 4, learning cap 7).
      8. Assemble check steps (unproven prereqs) and learning steps with calibrated difficulty.
      9. If weak seeds present and learning steps < 3: add ONE advance step from frontier.
      10. Append closing probe quiz step and final reevaluation quiz step.
      11. Run coverage checker.
    """
    total_attempts = report.get("total_questions_attempted", 0)
    if total_attempts == 0 and not report.get("concept_stats"):
        empty_plan = {
            "steps": [],
            "deferred": [],
            "summary": "No diagnostic history available. Complete the diagnostic quiz to generate your study plan.",
            "reason": "take the diagnostic quiz first",
        }
        empty_plan["coverage"] = check_coverage(empty_plan, report, strong_threshold)
        return empty_plan

    # 1. Course Complete Check:
    # If all 44 concepts in the curriculum are mastered (mastery >= strong_threshold),
    # return a plan with a single 'reevaluation' step over a mixed review (the 3 oldest-mastered concepts).
    all_mastered = all(
        _has_attempt_data(c, report) and _get_concept_mastery(c, report) >= strong_threshold
        for c in CONCEPTS
    )
    front = frontier(report, strong_threshold)
    has_weak_report = bool(report.get("weak_topics")) or bool(report.get("misconceptions", {}).get("active"))

    if all_mastered or (not front and not has_weak_report):
        due_list = [_extract_tag(x) for x in report.get("due_for_review", []) if _extract_tag(x) in CONCEPTS]
        review_concepts = due_list[:3] if len(due_list) >= 3 else [c for c in learning_order() if c in CONCEPTS][:3]
        avg_mst = sum(_get_concept_mastery(c, report) for c in review_concepts) / max(len(review_concepts), 1)
        course_step = {
            "concept": "all-plan-concepts",
            "title": "Comprehensive Reevaluation Quiz",
            "module": None,
            "kind": "reevaluation",
            "difficulty": "Medium",
            "lesson_style": None,
            "priority": 0.0,
            "mastery": round(avg_mst, 1),
            "est_minutes": 10,
            "reason": "Course complete - mixed review",
            "focus": {"concepts": review_concepts},
            "status": "pending",
            "user_note": None,
            "prompt_text": None,
            "closing_quiz": True,
            "position": 1,
        }
        plan = {
            "steps": [course_step],
            "deferred": [],
            "summary": "Course complete - mixed review covering 3 concepts.",
            "reason": "Course complete - mixed review",
        }
        plan["coverage"] = check_coverage(plan, report, strong_threshold)
        return plan

    # 2. Seed Identification
    seed_objs = identify_seeds(report, strong_threshold)
    weak_seeds = [s for s in seed_objs if s["kind"] in ("weak", "probe")]

    # 3. Real Advance:
    # With no weak seeds, take up to 2 frontier concepts as kind 'advance'
    if not weak_seeds:
        for c in front[:2]:
            has_data = _has_attempt_data(c, report)
            mst = _get_concept_mastery(c, report)
            diff = "Easy" if not has_data else ("Easy" if mst < 40 else ("Medium" if mst < 70 else "Hard"))
            seed_objs.append({
                "concept": c,
                "kind": "advance",
                "reasons": [f"Next concept on your path: {concept_title(c)}; prerequisites mastered"],
                "difficulty": diff,
                "lesson_style": "detailed",
            })

    seeds_list = [s["concept"] for s in seed_objs]
    seed_kind_map = {s["concept"]: s["kind"] for s in seed_objs}
    seed_reason_map = {s["concept"]: s["reasons"][0] for s in seed_objs}

    # 4. Prerequisite Closure
    all_selected, prereq_reasons = compute_prerequisite_closure(seeds_list, report, strong_threshold)

    # 5. Priority & Kahn Topological Sort
    priorities = {c: compute_priority(c, seeds_list, report) for c in all_selected}
    topological_concepts = topological_sort_kahn(all_selected, priorities)

    # 6. Size Cap & Deferral (Check cap 4, Learning cap 7)
    retained_concepts, deferred_items, closure_note = apply_size_cap(
        topological_concepts,
        seeds_list,
        priorities,
        size_cap=size_cap,
        check_cap=check_cap,
        report=report,
        prereq_reasons=prereq_reasons,
    )

    # 7. Build Steps: Check steps (unproven prereqs) vs Learning steps
    plan_steps = []
    preceding_titles = []

    for c in retained_concepts:
        prio = priorities.get(c, 0.0)
        # Check step for unproven prerequisite
        if c in prereq_reasons and not _has_attempt_data(c, report):
            check_step = {
                "concept": c,
                "title": f"Check: {concept_title(c)}",
                "module": module_of(c),
                "kind": "check",
                "difficulty": "Easy",
                "lesson_style": None,
                "priority": prio,
                "mastery": 30.0,
                "est_minutes": 3,
                "reason": prereq_reasons.get(c, f"Verify prerequisite {concept_title(c)}"),
                "focus": {
                    "quiz_kind": "practice",
                    "concept": c,
                    "n": 3,
                    "difficulty": "Easy",
                },
                "status": "pending",
                "user_note": None,
                "prompt_text": None,
                "closing_quiz": False,
            }
            plan_steps.append(check_step)
        else:
            # Learning step
            if c in prereq_reasons:
                kind = "prerequisite"
                reason = prereq_reasons[c]
            else:
                kind = seed_kind_map.get(c, "weak")
                reason = seed_reason_map.get(c, f"Targeted for remediation ({_get_concept_mastery(c, report):.1f}% mastery)")

            step = _build_learning_step(c, kind, reason, prio, report)
            step["prompt_text"] = format_step_prompt(step, preceding_titles=preceding_titles)
            preceding_titles.append(step["title"])
            plan_steps.append(step)

    # 8. If weak seeds present and fewer than 3 learning steps, add ONE advance step from frontier
    learning_steps = [s for s in plan_steps if s.get("kind") in ("weak", "prerequisite", "review", "advance")]
    if weak_seeds and len(learning_steps) < 3:
        retained_set = set(retained_concepts)
        deferred_set = {d.get("concept") for d in deferred_items}
        for c in front:
            if c in retained_set or c in deferred_set:
                continue
            # Advance concept must not be a prerequisite of any step already in the plan
            if any(c in prerequisites_of(s["concept"], deep=True) for s in plan_steps):
                continue
            has_data = _has_attempt_data(c, report)
            mst = _get_concept_mastery(c, report)
            diff = "Easy" if not has_data else ("Easy" if mst < 40 else ("Medium" if mst < 70 else "Hard"))
            prio = compute_priority(c, seeds_list, report)
            adv_step = _build_learning_step(
                c,
                "advance",
                f"Next concept on your path: {concept_title(c)}; prerequisites mastered",
                prio,
                report,
            )
            adv_step["prompt_text"] = format_step_prompt(adv_step, preceding_titles=preceding_titles)
            preceding_titles.append(adv_step["title"])
            plan_steps.append(adv_step)
            retained_concepts.append(c)
            break

    # 9. Closing Steps
    # (a) ONE probe step for highest-severity active/suspected misconception
    probe_concept = None
    top_mis_id = None
    max_sev = -1.0

    all_tracked = report.get("misconceptions", {}).get("active", []) + report.get("misconceptions", {}).get("suspected", [])
    for m in all_tracked:
        sev = float(m.get("severity", 0.0))
        m_c = m.get("concept") or (m.get("misconception_id", "").split("/")[0] if "/" in m.get("misconception_id", "") else "")
        if m_c in retained_concepts and sev > max_sev:
            max_sev = sev
            probe_concept = m_c
            top_mis_id = m.get("misconception_id")

    if not probe_concept and retained_concepts:
        # Fallback to lowest-mastery retained concept
        probe_concept = min(retained_concepts, key=lambda c: _get_concept_mastery(c, report))

    closing_steps = []
    if probe_concept:
        probe_mst = _get_concept_mastery(probe_concept, report)
        p_diff = "Easy" if probe_mst < 40 else ("Medium" if probe_mst < 70 else "Hard")
        reason_str = (
            f"Diagnostic probe quiz sweeping misconception [{top_mis_id}] in {concept_title(probe_concept)}"
            if top_mis_id else f"Diagnostic probe quiz on {concept_title(probe_concept)}"
        )
        closing_steps.append({
            "concept": probe_concept,
            "title": f"Probe Quiz: {concept_title(probe_concept)}",
            "module": module_of(probe_concept),
            "kind": "probe",
            "difficulty": p_diff,
            "lesson_style": None,
            "priority": 0.0,
            "mastery": probe_mst,
            "est_minutes": 8,
            "reason": reason_str,
            "focus": {
                "concept": probe_concept,
                "target_misconceptions": [top_mis_id] if top_mis_id else [],
                "probe_misconception_id": top_mis_id,
            },
            "status": "pending",
            "user_note": None,
            "prompt_text": None,
            "closing_quiz": True,
        })

    # (b) ONE final reevaluation step covering all plan concepts
    all_plan_concepts = [
        s["concept"] for s in plan_steps
        if s.get("concept") and s["concept"] != "all-plan-concepts"
    ]
    avg_plan_mst = (
        round(sum(_get_concept_mastery(c, report) for c in all_plan_concepts) / max(len(all_plan_concepts), 1), 1)
        if all_plan_concepts else 50.0
    )
    closing_steps.append({
        "concept": "all-plan-concepts",
        "title": "Comprehensive Reevaluation Quiz",
        "module": None,
        "kind": "reevaluation",
        "difficulty": "Medium",
        "lesson_style": None,
        "priority": 0.0,
        "mastery": avg_plan_mst,
        "est_minutes": 10,
        "reason": f"Comprehensive reevaluation quiz covering all {len(all_plan_concepts)} study plan concepts",
        "focus": {"concepts": all_plan_concepts},
        "status": "pending",
        "user_note": None,
        "prompt_text": None,
        "closing_quiz": True,
    })

    all_steps = plan_steps + closing_steps
    for idx, s in enumerate(all_steps, start=1):
        s["position"] = idx

    n_learning = sum(1 for s in plan_steps if s.get("kind") in ("weak", "prerequisite", "review", "advance"))
    n_check = sum(1 for s in plan_steps if s.get("kind") == "check")
    summary = f"Generated {n_learning} learning steps + {n_check} check steps + {len(closing_steps)} quiz verification steps."
    if closure_note:
        summary += f" ({closure_note})"

    plan = {
        "steps": all_steps,
        "deferred": deferred_items,
        "summary": summary,
        "reason": "plan generated",
    }
    plan["coverage"] = check_coverage(plan, report, strong_threshold)
    return plan


def plan_after_check(
    plan: Dict[str, Any],
    concept: str,
    check_mastery: float,
    report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    2. Check Steps: Update study plan after a check quiz completes:
      - If check_mastery < 50.0: convert check step to a lesson step
        (kind 'prerequisite', Easy, simplified) with generated prompt_text.
      - If check_mastery >= 50.0: mark check step as done and dependents keep order.
    """
    updated_plan = json.loads(json.dumps(plan))
    steps = updated_plan.get("steps", [])

    step_idx = None
    target_step = None
    for idx, s in enumerate(steps):
        if s.get("concept") == concept and s.get("kind") == "check":
            step_idx = idx
            target_step = s
            break

    if target_step is None:
        return updated_plan

    if check_mastery < 50.0:
        # Convert to prerequisite lesson step
        target_step["kind"] = "prerequisite"
        target_step["difficulty"] = "Easy"
        target_step["lesson_style"] = "simplified"
        target_step["mastery"] = float(check_mastery)
        target_step["status"] = "pending"
        target_step["title"] = concept_title(concept)
        target_step["reason"] = f"Prerequisite check failed ({check_mastery:.1f}% mastery); foundational remediation needed"
        target_step["focus"] = {
            "misconceptions": [],
            "weak_facets": [],
            "skill_gap": None,
        }
        prec_titles = [s["title"] for s in steps[:step_idx] if s.get("title") and s.get("kind") != "reevaluation"]
        target_step["prompt_text"] = format_step_prompt(target_step, preceding_titles=prec_titles)
    else:
        # Prerequisite verified: mark as done
        target_step["status"] = "done"
        target_step["mastery"] = float(check_mastery)
        target_step["reason"] = f"Prerequisite check passed ({check_mastery:.1f}% mastery)"

    # Refresh coverage if report is provided
    if report:
        updated_plan["coverage"] = check_coverage(updated_plan, report)

    return updated_plan


# ─────────────────────────────────────────────────────────────────────────────
# 7. COVERAGE CHECKER
# ─────────────────────────────────────────────────────────────────────────────

def check_coverage(
    plan: Dict[str, Any],
    report: Dict[str, Any],
    strong_threshold: float = 70.0,
) -> Dict[str, Any]:
    """
    2.10 Formal Coverage Checker:
      Checks:
        (a) order_valid: Every prerequisite of a planned concept is mastered (>= strong_threshold)
            or appears in an earlier active non-skipped step (lesson or check),
            or was deferred with 'will be verified when its dependent is reached'.
        (b) weak_concepts_covered: Every weak concept is in an active plan lesson step (not check) or deferred.
        (c) active_misconceptions_addressed: Every active misconception is addressed by
            at least one active step focus.
        (d) no_cycles_or_duplicates: No duplicate concepts or cyclic dependencies.
        (e) closing_steps_present: Contains both probe and reevaluation closing quiz steps,
            or single reevaluation if course complete.

      Skipped steps count as NOT covering; checker details exactly what becomes uncovered.
    """
    steps = plan.get("steps", [])
    deferred = plan.get("deferred", [])
    deferred_concepts = {d.get("concept") for d in deferred}

    violations = []
    checks = []

    # Active non-skipped steps (learning and check) before closing quizzes
    active_steps = [
        s for s in steps
        if not s.get("closing_quiz") and s.get("kind") != "reevaluation" and s.get("status") != "skipped"
    ]
    active_concepts = [s.get("concept") for s in active_steps]
    active_concept_set = set(active_concepts)

    # Active learning steps (excluding check steps)
    active_learning_steps = [s for s in active_steps if s.get("kind") != "check"]
    active_learning_concept_set = {s.get("concept") for s in active_learning_steps}

    # ── Check (a): Order valid & prerequisite presence ──────────────────────
    order_ok = True
    order_details = []
    seen_in_plan: Set[str] = set()

    for idx, s in enumerate(active_steps):
        c = s.get("concept")
        direct_prereqs = PREREQUISITES.get(c, [])
        for p in direct_prereqs:
            p_mst = _get_concept_mastery(p, report)
            p_has_data = _has_attempt_data(p, report)
            p_mastered = p_has_data and p_mst >= strong_threshold
            p_deferred_check = (not p_has_data) and any(
                d.get("concept") == p and "will be verified" in d.get("reason", "")
                for d in deferred
            )

            if not p_mastered and p not in seen_in_plan and not p_deferred_check:
                order_ok = False
                msg = f"Prerequisite '{p}' of '{c}' is neither mastered ({p_mst:.1f}%) nor completed earlier in the plan."
                order_details.append(msg)
                violations.append(msg)

        seen_in_plan.add(c)

    checks.append({
        "name": "order_valid",
        "ok": order_ok,
        "detail": "All prerequisites are mastered or precede their dependents." if order_ok else "; ".join(order_details),
    })

    # ── Check (b): Every weak concept in plan or deferred ───────────────────
    # A check step NEVER counts as covering a weak concept
    weak_ok = True
    weak_details = []
    weak_list = [_extract_tag(x) for x in report.get("weak_topics", [])]

    for w in weak_list:
        if w not in active_learning_concept_set and w not in deferred_concepts:
            weak_ok = False
            msg = f"Weak concept '{w}' is neither in active learning steps nor deferred."
            weak_details.append(msg)
            violations.append(msg)

    checks.append({
        "name": "weak_concepts_covered",
        "ok": weak_ok,
        "detail": "All weak concepts are scheduled in lessons or deferred." if weak_ok else "; ".join(weak_details),
    })

    # ── Check (c): Active misconceptions addressed ─────────────────────────
    # A check step NEVER counts as addressing a misconception
    mis_ok = True
    mis_details = []
    addressed_mis_ids = set()
    for s in active_learning_steps:
        for m in s.get("focus", {}).get("misconceptions", []):
            if m.get("id"):
                addressed_mis_ids.add(m["id"])

    # Also check probe step
    probe_steps = [s for s in steps if s.get("kind") == "probe" and s.get("status") != "skipped"]
    for ps in probe_steps:
        pmid = ps.get("focus", {}).get("probe_misconception_id")
        if pmid:
            addressed_mis_ids.add(pmid)
        for tm in ps.get("focus", {}).get("target_misconceptions", []):
            if tm:
                addressed_mis_ids.add(tm)

    active_mis_list = report.get("misconceptions", {}).get("active", [])
    for m in active_mis_list:
        mid = m.get("misconception_id")
        if mid and mid not in addressed_mis_ids:
            mis_ok = False
            msg = f"Active misconception '{mid}' ({m.get('concept', 'unknown')}) is not addressed by any active step."
            mis_details.append(msg)
            violations.append(msg)

    checks.append({
        "name": "active_misconceptions_addressed",
        "ok": mis_ok,
        "detail": "All active misconceptions are addressed in step focus." if mis_ok else "; ".join(mis_details),
    })

    # ── Check (d): No cycles or duplicate concepts ─────────────────────────
    cycle_ok = True
    cycle_details = []

    # Check duplicates in active concepts
    if len(active_concepts) != len(active_concept_set):
        cycle_ok = False
        dups = [c for c in active_concept_set if active_concepts.count(c) > 1]
        msg = f"Duplicate concepts found in plan steps: {dups}."
        cycle_details.append(msg)
        violations.append(msg)

    # Check cycles via simple DFS on active concepts
    adj: Dict[str, List[str]] = defaultdict(list)
    for c in active_concept_set:
        for p in PREREQUISITES.get(c, []):
            if p in active_concept_set:
                adj[p].append(c)

    visited: Dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited
    has_cycle = False

    def dfs(node: str) -> bool:
        visited[node] = 1
        for neighbor in adj[node]:
            if visited.get(neighbor) == 1:
                return True
            if visited.get(neighbor) != 2:
                if dfs(neighbor):
                    return True
        visited[node] = 2
        return False

    for c in active_concept_set:
        if visited.get(c) != 2:
            if dfs(c):
                has_cycle = True
                break

    if has_cycle:
        cycle_ok = False
        msg = "Cyclic dependency detected in study plan concepts."
        cycle_details.append(msg)
        violations.append(msg)

    checks.append({
        "name": "no_cycles_or_duplicates",
        "ok": cycle_ok,
        "detail": "No duplicate steps or cyclic dependencies." if cycle_ok else "; ".join(cycle_details),
    })

    # ── Check (e): Closing steps present ───────────────────────────────────
    closing_ok = True
    closing_details = []

    non_skipped_steps = [s for s in steps if s.get("status") != "skipped"]
    kinds = [s.get("kind") for s in non_skipped_steps]

    has_probe = "probe" in kinds
    has_reeval = "reevaluation" in kinds
    is_course_complete = plan.get("reason") == "Course complete - mixed review"

    if is_course_complete:
        if not has_reeval:
            closing_ok = False
            msg = "Missing final 'reevaluation' quiz step for course complete plan."
            closing_details.append(msg)
            violations.append(msg)
    else:
        if not has_probe:
            closing_ok = False
            msg = "Missing closing 'probe' quiz step."
            closing_details.append(msg)
            violations.append(msg)

        if not has_reeval:
            closing_ok = False
            msg = "Missing final 'reevaluation' quiz step."
            closing_details.append(msg)
            violations.append(msg)

    checks.append({
        "name": "closing_steps_present",
        "ok": closing_ok,
        "detail": "Both probe and reevaluation closing quiz steps are present (or mixed review for completed course)." if closing_ok else "; ".join(closing_details),
    })

    return {
        "ok": len(violations) == 0,
        "checks": checks,
        "violations": violations,
    }
