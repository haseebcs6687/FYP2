"""
=============================================================================
EduGen - Performance Analysis Agent  (FYP-2)
=============================================================================
Agent type : Evidence aggregator + rule-based classifier over a concept graph
Role       : Measure WHAT the student knows, per concept. Nothing else.
             It never decides what to teach - that is the Adaptive Content
             Agent's job. Keeping those two responsibilities apart is what
             makes this a multi-agent system rather than one big function.

What changed since FYP-1
------------------------
FYP-1 scored a topic as weak if raw accuracy was under 50%. That throws away
three signals the database already holds. This version adds:

  1. MASTERY (recency-weighted)  - a newer attempt counts more than an old
     one, so a student who has improved is not punished forever for the first
     bad quiz. Implemented as an exponentially weighted moving average.

  2. TREND                       - comparing the first half of the attempts
     with the second half gives improving / declining / steady, which the
     Adaptive Content Agent uses to decide between repeating and advancing.

  3. ROOT CAUSE via prerequisites - if a student is weak in
     `method-overriding` and also shaky in its prerequisite
     `inheritance-basics`, the real problem is the prerequisite. The agent
     walks core/concepts.py's prerequisite graph to report that.

  4. RESPONSE TIME               - a correct answer given in 2 seconds on a
     Hard question is a different signal from one given in 90 seconds. Slow
     correct answers are flagged as `fragile`.

  5. REVIEW DECAY                - concepts mastered more than N days ago are
     marked due for review (lightweight spaced repetition).

Output: one structured dict, documented at the bottom of this file.
=============================================================================
"""

import json
import math
import os
import sqlite3
from datetime import datetime

from core.concepts import (
    CONCEPTS,
    concept_title,
    module_of,
    module_title,
    prerequisites_of,
)
from core.db import DB_PATH
from core.pa_model import (
    BKT_GUESS,
    BKT_GUESS_BY_DIFF,
    BKT_P_INIT,
    BKT_P_LEARN,
    BKT_SLIP_BY_DIFF,
    EWMA_ALPHA,
    MIN_ATTEMPTS,
    STRONG_THRESHOLD,
    WEAK_THRESHOLD,
    compute_concept_bkt,
    compute_facet_map,
    compute_misconception_stats,
    compute_skill_profile,
    compute_untagged_errors,
    get_confidence,
)

# ── classification thresholds (all configurable in one place) ──
SLOW_ANSWER_MS = 45000       # a "correct but slow" answer
REVIEW_AFTER_DAYS = 7        # mastered concepts go stale after a week



class PerformanceAnalysisAgent(object):

    def __init__(self, log=None):
        self.log = log
        print("[PA Agent] Concept-graph analyser initialised "
              "(mastery + trend + prerequisite root cause).")

    def _emit(self, message, level="info", payload=None):
        if self.log:
            self.log("Performance Analysis", message, level, payload)

    # ─────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────
    def analyze_student(self, student_id, db_path=None, quiz_data=None):
        """
        Build the full weakness report for one student.
        `quiz_data` is accepted and ignored: kept so FYP-1 call sites still work.
        """
        t_start = datetime.now()
        db_path = db_path or DB_PATH
        attempts = _load_attempts(student_id, db_path)
        quiz_count = _count_quizzes(student_id, db_path)

        if not attempts:
            self._emit("No question attempts on record yet", "warning")
            return _empty_report(student_id)

        self._emit("Loaded {} question attempts across {} quizzes".format(
            len(attempts), quiz_count))

        # Pure model calculations (Phase 5)
        misconceptions_data = compute_misconception_stats(attempts, total_quizzes=quiz_count)
        facet_map = compute_facet_map(attempts)
        skill_profile = compute_skill_profile(attempts)
        untagged_map = compute_untagged_errors(attempts)

        stats = self._aggregate(
            attempts,
            facet_map=facet_map,
            untagged_map=untagged_map,
            active_misconceptions=misconceptions_data.get("active", []),
        )
        buckets = self._classify(stats)
        root_causes = self._find_root_causes(buckets["weak"], stats)
        due = self._due_for_review(stats)

        total = len(attempts)
        correct = sum(1 for a in attempts if a["is_correct"])
        overall = round(100.0 * correct / total, 1) if total else 0.0

        primary = None
        if root_causes:
            primary = root_causes[0]["teach_first"]
        elif buckets["weak"]:
            primary = buckets["weak"][0]["concept_tag"]
        elif due:
            primary = due[0]["concept_tag"]
        elif buckets["moderate"]:
            primary = buckets["moderate"][0]["concept_tag"]

        # Extract weak facets across concepts
        weak_facets = []
        for c_tag, f_dict in facet_map.items():
            for f_name, f_stat in f_dict.items():
                if f_stat.get("weak"):
                    weak_facets.append({
                        "concept": c_tag,
                        "facet": f_name,
                        "offered": f_stat.get("offered", 0),
                        "chosen": f_stat.get("chosen", 0),
                        "error_rate": f_stat.get("error_rate", 0.0),
                    })

        active_mids = [m["misconception_id"] for m in misconceptions_data.get("active", [])[:5]]
        skill_gaps = skill_profile.get("skill_gaps", [])

        self._emit(
            "Classified {} concepts: {} weak, {} moderate, {} strong, {} unproven".format(
                len(stats), len(buckets["weak"]), len(buckets["moderate"]),
                len(buckets["strong"]), len(buckets["insufficient"])),
            "success",
        )
        if primary:
            self._emit("Primary weak area: '{}'".format(concept_title(primary)), "warning",
                       {"concept": primary})

        # Structured logging for active misconceptions and skill gaps
        for m in misconceptions_data.get("active", []):
            self._emit("Active misconception: [{}] {}".format(m["misconception_id"], m.get("evidence", "")), "warning")

        for gap in skill_gaps:
            self._emit("Skill gap: {}".format(gap), "warning")

        elapsed_ms = int((datetime.now() - t_start).total_seconds() * 1000)
        self._emit("Performance analysis completed in {} ms".format(elapsed_ms), "info")

        # Persist idempotently
        try:
            from core.db_repo import record_concept_mastery, upsert_student_misconceptions
            record_concept_mastery(student_id, stats)
            all_tracked = (
                misconceptions_data.get("active", []) +
                misconceptions_data.get("suspected", []) +
                misconceptions_data.get("resolved", [])
            )
            upsert_student_misconceptions(student_id, all_tracked)
        except Exception as exc:
            self._emit("Failed to persist performance analysis records: {}".format(exc), "warning")

        report = {
            "student_id": student_id,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall_performance": overall,
            "total_quizzes_taken": quiz_count,
            "total_questions_attempted": total,
            "total_questions_correct": correct,

            # buckets  (weak_topics / strong_topics keep their FYP-1 names)
            "weak_topics": buckets["weak"],
            "moderate_topics": buckets["moderate"],
            "strong_topics": buckets["strong"],
            "insufficient_data": buckets["insufficient"],

            # FYP-2 additions
            "root_causes": root_causes,
            "due_for_review": due,
            "module_breakdown": self._module_breakdown(stats),
            "concept_stats": stats,

            # Phase 5 additions
            "misconceptions": misconceptions_data,
            "facet_map": facet_map,
            "skill_profile": skill_profile,

            "recommendation_input": {
                "primary_weak_topic": primary,
                "weak_topic_count": len(buckets["weak"]),
                "overall_performance": overall,
                "root_causes": root_causes,
                "due_for_review": [d["concept_tag"] for d in due],
                "trend_summary": self._trend_summary(stats),
                "concepts_seen": len(stats),
                "active_misconceptions": active_mids,
                "weak_facets": weak_facets,
                "skill_gaps": skill_gaps,
            },
        }
        return report

    # ─────────────────────────────────────────────────────────
    # Step 1 - aggregate raw attempts into per-concept evidence
    # ─────────────────────────────────────────────────────────
    def _aggregate(self, attempts, facet_map=None, untagged_map=None, active_misconceptions=None):
        facet_map = facet_map or {}
        untagged_map = untagged_map or {}
        active_misconceptions = active_misconceptions or []

        buckets = {}
        for att in attempts:
            for tag in att["concept_tags"]:
                if tag not in CONCEPTS:
                    continue
                buckets.setdefault(tag, []).append(att)

        stats = {}
        for tag, events in buckets.items():
            events.sort(key=lambda e: e["timestamp"] or "")
            total = len(events)
            correct = sum(1 for e in events if e["is_correct"])
            accuracy = round(100.0 * correct / total, 1)

            # BKT mastery over chronological sequence (Phase 5)
            p_known, ewma_accuracy = compute_concept_bkt(events)
            mastery = round(100.0 * p_known, 1)
            confidence = get_confidence(total)

            trend = _trend(events)

            times = [e["time_taken_ms"] for e in events if e["time_taken_ms"]]
            avg_ms = int(sum(times) / len(times)) if times else 0
            slow_correct = sum(1 for e in events
                               if e["is_correct"] and e["time_taken_ms"] > SLOW_ANSWER_MS)
            fragile = bool(times) and accuracy >= STRONG_THRESHOLD and slow_correct >= max(1, total // 3)

            last_seen = events[-1]["timestamp"]
            tag_active_m = [m for m in active_misconceptions if m.get("concept") == tag]

            stats[tag] = {
                "concept_tag": tag,
                "topic": tag,                      # FYP-1 compatibility
                "title": concept_title(tag),
                "module": module_of(tag),
                "module_title": module_title(module_of(tag)),
                "attempts": total,
                "correct": correct,
                "accuracy": accuracy,
                "mastery": mastery,                # BKT mastery (0-100)
                "p_known": round(p_known, 4),      # Phase 5
                "ewma_accuracy": ewma_accuracy,    # Phase 5
                "confidence": confidence,          # Phase 5
                "trend": trend,
                "avg_time_ms": avg_ms,
                "fragile": fragile,
                "last_seen": last_seen,
                "days_since": _days_since(last_seen),
                "misconceptions": _top_misconceptions(events),
                "facets": facet_map.get(tag, {}),  # Phase 5
                "untagged_errors": untagged_map.get(tag, 0),  # Phase 5
                "active_misconceptions": tag_active_m,        # Phase 5
            }
        return stats

    # ─────────────────────────────────────────────────────────
    # Step 2 - classify each concept
    # ─────────────────────────────────────────────────────────
    def _classify(self, stats):
        weak, moderate, strong, insufficient = [], [], [], []
        for entry in stats.values():
            score = entry["mastery"]
            if entry["attempts"] < MIN_ATTEMPTS:
                insufficient.append(entry)
            elif score < WEAK_THRESHOLD:
                weak.append(entry)
            elif score >= STRONG_THRESHOLD:
                strong.append(entry)
            else:
                moderate.append(entry)

        weak.sort(key=lambda e: (e["mastery"], -e["attempts"], e["concept_tag"]))
        moderate.sort(key=lambda e: (e["mastery"], -e["attempts"], e["concept_tag"]))
        strong.sort(key=lambda e: (-e["mastery"], -e["attempts"], e["concept_tag"]))
        insufficient.sort(key=lambda e: (-e["attempts"], e["concept_tag"]))
        return {"weak": weak, "moderate": moderate, "strong": strong, "insufficient": insufficient}

    # ─────────────────────────────────────────────────────────
    # Step 3 - prerequisite root-cause analysis
    # ─────────────────────────────────────────────────────────
    def _find_root_causes(self, weak_entries, stats):
        """
        For each weak concept, look at its prerequisites. If a prerequisite is
        also weak (or has never been proven), teaching the prerequisite first
        is the higher-value action.
        """
        causes = []
        for entry in weak_entries:
            tag = entry["concept_tag"]
            direct = set(prerequisites_of(tag))
            shaky = []
            for prereq in prerequisites_of(tag, deep=True):
                pstat = stats.get(prereq)
                depth = 0 if prereq in direct else 1
                if pstat is None:
                    shaky.append({"concept_tag": prereq, "title": concept_title(prereq),
                                  "mastery": None, "reason": "never assessed",
                                  "_measured": False, "_depth": depth})
                elif pstat["mastery"] < STRONG_THRESHOLD:
                    shaky.append({"concept_tag": prereq, "title": concept_title(prereq),
                                  "mastery": pstat["mastery"], "reason": "below mastery",
                                  "_measured": True, "_depth": depth})
            if shaky:
                # Ranking, in order of priority:
                #   1. a prerequisite we have MEASURED as weak beats one we have
                #      simply never tested - real evidence outranks a guess
                #   2. among those, the lowest mastery
                #   3. a direct prerequisite beats a distant transitive one, so the
                #      student is sent one step back rather than all the way to the root
                shaky.sort(key=lambda s: (not s["_measured"], s["mastery"] if s["_measured"] else 0.0,
                                          s["_depth"], s["concept_tag"]))
                for s in shaky:
                    s.pop("_measured", None)
                    s.pop("_depth", None)
                causes.append({
                    "symptom": tag,
                    "symptom_title": concept_title(tag),
                    "symptom_mastery": entry["mastery"],
                    "teach_first": shaky[0]["concept_tag"],
                    "teach_first_title": shaky[0]["title"],
                    "teach_first_measured": shaky[0]["mastery"] is not None,
                    "weak_prerequisites": shaky[:3],
                    "explanation": (
                        "'{}' depends on '{}', which the student has not mastered yet. "
                        "Re-teaching the prerequisite usually fixes the symptom."
                    ).format(concept_title(tag), shaky[0]["title"]),
                })

        # A cause whose remedy we have actually measured outranks one that is only
        # inferred from a never-assessed prerequisite. Otherwise a single untested
        # foundational concept would hijack every recommendation.
        causes.sort(key=lambda c: (not c["teach_first_measured"], c["symptom_mastery"]))
        return causes

    # ─────────────────────────────────────────────────────────
    # Step 4 - spaced repetition
    # ─────────────────────────────────────────────────────────
    def _due_for_review(self, stats):
        due = []
        for entry in stats.values():
            if entry["mastery"] >= STRONG_THRESHOLD and entry["days_since"] is not None:
                if entry["days_since"] >= REVIEW_AFTER_DAYS:
                    due.append({
                        "concept_tag": entry["concept_tag"],
                        "title": entry["title"],
                        "mastery": entry["mastery"],
                        "days_since": entry["days_since"],
                    })
        due.sort(key=lambda d: -d["days_since"])
        return due

    # ─────────────────────────────────────────────────────────
    # Reporting helpers
    # ─────────────────────────────────────────────────────────
    def _module_breakdown(self, stats):
        modules = {}
        for entry in stats.values():
            mid = entry["module"]
            bucket = modules.setdefault(mid, {
                "module": mid, "title": entry["module_title"],
                "attempts": 0, "correct": 0, "concepts": 0, "mastery_sum": 0.0,
            })
            bucket["attempts"] += entry["attempts"]
            bucket["correct"] += entry["correct"]
            bucket["concepts"] += 1
            bucket["mastery_sum"] += entry["mastery"]

        out = []
        for bucket in modules.values():
            out.append({
                "module": bucket["module"],
                "title": bucket["title"],
                "attempts": bucket["attempts"],
                "accuracy": round(100.0 * bucket["correct"] / bucket["attempts"], 1)
                if bucket["attempts"] else 0.0,
                "mastery": round(bucket["mastery_sum"] / bucket["concepts"], 1)
                if bucket["concepts"] else 0.0,
                "concepts": bucket["concepts"],
            })
        out.sort(key=lambda m: m["mastery"])
        return out

    def _trend_summary(self, stats):
        counts = {"improving": 0, "declining": 0, "steady": 0, "new": 0}
        for entry in stats.values():
            counts[entry["trend"]] = counts.get(entry["trend"], 0) + 1
        return counts

    def get_model_info(self):
        return {
            "model_type": "Bayesian Knowledge Tracing (BKT) & Prerequisite Evidence Engine",
            "classifier_description": (
                "Estimates concept mastery using Bayesian Knowledge Tracing "
                "parameterized by item difficulty (Corbett & Anderson 1995; Pardos & Heffernan 2011). "
                "Tracks misconception persistence across attempts with exponential decay, "
                "maps error rates by facet, profiles skills by question type, and resolves "
                "prerequisite root causes across the concept graph."
            ),
            "parameters": {
                "p_init": BKT_P_INIT,
                "p_learn": BKT_P_LEARN,
                "guess": BKT_GUESS,
                "slip_by_difficulty": BKT_SLIP_BY_DIFF,
                "guess_by_difficulty": BKT_GUESS_BY_DIFF,
            },
            "thresholds": {
                "weak": "mastery < {}%".format(WEAK_THRESHOLD),
                "moderate": "{}% <= mastery < {}%".format(WEAK_THRESHOLD, STRONG_THRESHOLD),
                "strong": "mastery >= {}%".format(STRONG_THRESHOLD),
                "min_attempts_required": MIN_ATTEMPTS,
                "ewma_alpha": EWMA_ALPHA,
                "review_after_days": REVIEW_AFTER_DAYS,
            },
            "signals_used": [
                "per-concept accuracy",
                "Bayesian Knowledge Tracing P(known)",
                "recency-weighted mastery (EWMA)",
                "trend across attempt history",
                "response time per question",
                "prerequisite graph position",
                "misconception tracking (active / suspected / resolved)",
                "facet error rate mapping",
                "question type skill profiling",
            ],
            "is_trained": False,
        }


# ─────────────────────────────────────────────────────────────
# Data access
# ─────────────────────────────────────────────────────────────
def _load_attempts(student_id, db_path):
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    col_rows = cur.execute("PRAGMA table_info(question_attempts)").fetchall()
    col_names = {r["name"] for r in col_rows}

    has_offered = "offered_misconceptions" in col_names
    has_qtype = "qtype" in col_names
    has_facet = "facet" in col_names
    has_diff = "difficulty" in col_names

    sel_offered = "qa.offered_misconceptions," if has_offered else "NULL AS offered_misconceptions,"
    sel_qtype = "qa.qtype," if has_qtype else "NULL AS qtype,"
    sel_facet = "qa.facet," if has_facet else "NULL AS facet,"
    sel_diff = "qa.difficulty," if has_diff else "NULL AS difficulty,"

    rows = conn.execute(
        f"""SELECT qa.id, qa.concept_tags, qa.is_correct, qa.student_answer, qa.correct_answer,
                  qa.chosen_option_text, qa.misconception_id,
                  {sel_offered}
                  {sel_qtype}
                  {sel_facet}
                  {sel_diff}
                  COALESCE(qa.time_taken_ms, 0) AS time_taken_ms,
                  qr.id AS quiz_result_id, qr.timestamp, qr.difficulty AS quiz_difficulty, qr.topic
           FROM question_attempts qa
           JOIN quiz_results qr ON qa.quiz_result_id = qr.id
           WHERE qr.student_id = ?
           ORDER BY qr.timestamp ASC, qa.question_index ASC, qa.id ASC""",
        (student_id,),
    ).fetchall()
    conn.close()

    attempts = []
    for row in rows:
        try:
            tags = json.loads(row["concept_tags"]) or []
        except (ValueError, TypeError):
            tags = []
        eff_diff = row["difficulty"] or row["quiz_difficulty"] or "Medium"
        attempts.append({
            "concept_tags": tags,
            "concept": tags[0] if tags else None,
            "is_correct": bool(row["is_correct"]),
            "student_answer": row["student_answer"],
            "correct_answer": row["correct_answer"],
            "chosen_option_text": row["chosen_option_text"],
            "misconception_id": row["misconception_id"],
            "offered_misconceptions": row["offered_misconceptions"],
            "qtype": row["qtype"] or "concept",
            "facet": row["facet"],
            "difficulty": eff_diff,
            "time_taken_ms": row["time_taken_ms"] or 0,
            "quiz_result_id": row["quiz_result_id"],
            "timestamp": row["timestamp"],
            "topic": row["topic"],
        })
    return attempts


def _count_quizzes(student_id, db_path):
    if not os.path.exists(db_path):
        return 0
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM quiz_results WHERE student_id = ?", (student_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


# ─────────────────────────────────────────────────────────────
# Small pure helpers
# ─────────────────────────────────────────────────────────────
def _trend(events):
    if len(events) < 4:
        return "new"
    mid = len(events) // 2
    first = sum(1 for e in events[:mid] if e["is_correct"]) / float(mid)
    second = sum(1 for e in events[mid:] if e["is_correct"]) / float(len(events) - mid)
    delta = second - first
    if delta >= 0.2:
        return "improving"
    if delta <= -0.2:
        return "declining"
    return "steady"


def _days_since(timestamp):
    if not timestamp:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            then = datetime.strptime(str(timestamp)[:26], fmt)
            return max(0, (datetime.now() - then).days)
        except ValueError:
            continue
    return None


def _top_misconceptions(events):
    """
    Which wrong option does the student keep picking? A repeated wrong choice
    is a specific misconception, not random error - worth showing the student.
    """
    counts = {}
    for e in events:
        if e["is_correct"]:
            continue
        label = e.get("chosen_option_text")
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [{"answer": text, "times": n} for text, n in ranked[:2] if n >= 2]


def _empty_report(student_id):
    return {
        "student_id": student_id,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overall_performance": 0.0,
        "total_quizzes_taken": 0,
        "total_questions_attempted": 0,
        "total_questions_correct": 0,
        "weak_topics": [],
        "moderate_topics": [],
        "strong_topics": [],
        "insufficient_data": [],
        "root_causes": [],
        "due_for_review": [],
        "module_breakdown": [],
        "concept_stats": {},
        "misconceptions": {
            "active": [],
            "suspected": [],
            "resolved": [],
        },
        "facet_map": {},
        "skill_profile": {
            "overall": {},
            "by_module": {},
            "skill_gaps": [],
        },
        "recommendation_input": {
            "primary_weak_topic": None,
            "weak_topic_count": 0,
            "overall_performance": 0.0,
            "root_causes": [],
            "due_for_review": [],
            "trend_summary": {},
            "concepts_seen": 0,
            "active_misconceptions": [],
            "weak_facets": [],
            "skill_gaps": [],
        },
    }


# ─────────────────────────────────────────────────────────────
# FYP-1 compatibility shim (app.py used to import this directly)
# ─────────────────────────────────────────────────────────────
def get_concept_performance(student_id, db_path=None):
    """{tag: {total, correct, accuracy}} - weakest concept first."""
    agent = PerformanceAnalysisAgent()
    stats = agent._aggregate(_load_attempts(student_id, db_path or DB_PATH))
    ordered = sorted(stats.values(), key=lambda e: (e["accuracy"], e["attempts"]))
    return {
        e["concept_tag"]: {
            "total": e["attempts"],
            "correct": e["correct"],
            "accuracy": e["accuracy"],
            "mastery": e["mastery"],
        }
        for e in ordered
    }
