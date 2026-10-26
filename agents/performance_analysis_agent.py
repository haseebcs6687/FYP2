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

# ── classification thresholds (all configurable in one place) ──
WEAK_THRESHOLD = 50.0        # mastery below this  -> weak
STRONG_THRESHOLD = 80.0      # mastery at or above -> strong
MIN_ATTEMPTS = 2             # below this          -> insufficient evidence
EWMA_ALPHA = 0.45            # recency weight; higher = trusts recent answers more
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
        db_path = db_path or DB_PATH
        attempts = _load_attempts(student_id, db_path)
        quiz_count = _count_quizzes(student_id, db_path)

        if not attempts:
            self._emit("No question attempts on record yet", "warning")
            return _empty_report(student_id)

        self._emit("Loaded {} question attempts across {} quizzes".format(
            len(attempts), quiz_count))

        stats = self._aggregate(attempts)
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

        self._emit(
            "Classified {} concepts: {} weak, {} moderate, {} strong, {} unproven".format(
                len(stats), len(buckets["weak"]), len(buckets["moderate"]),
                len(buckets["strong"]), len(buckets["insufficient"])),
            "success",
        )
        if primary:
            self._emit("Primary weak area: '{}'".format(concept_title(primary)), "warning",
                       {"concept": primary})

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

            "recommendation_input": {
                "primary_weak_topic": primary,
                "weak_topic_count": len(buckets["weak"]),
                "overall_performance": overall,
                "root_causes": root_causes,
                "due_for_review": [d["concept_tag"] for d in due],
                "trend_summary": self._trend_summary(stats),
                "concepts_seen": len(stats),
            },
        }
        return report

    # ─────────────────────────────────────────────────────────
    # Step 1 - aggregate raw attempts into per-concept evidence
    # ─────────────────────────────────────────────────────────
    def _aggregate(self, attempts):
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

            # EWMA over the chronological sequence, newest weighted highest
            mastery = None
            for e in events:
                value = 100.0 if e["is_correct"] else 0.0
                mastery = value if mastery is None else (EWMA_ALPHA * value + (1 - EWMA_ALPHA) * mastery)
            mastery = round(mastery or 0.0, 1)

            trend = _trend(events)

            times = [e["time_taken_ms"] for e in events if e["time_taken_ms"]]
            avg_ms = int(sum(times) / len(times)) if times else 0
            slow_correct = sum(1 for e in events
                               if e["is_correct"] and e["time_taken_ms"] > SLOW_ANSWER_MS)
            fragile = bool(times) and accuracy >= STRONG_THRESHOLD and slow_correct >= max(1, total // 3)

            last_seen = events[-1]["timestamp"]
            stats[tag] = {
                "concept_tag": tag,
                "topic": tag,                      # FYP-1 compatibility
                "title": concept_title(tag),
                "module": module_of(tag),
                "module_title": module_title(module_of(tag)),
                "attempts": total,
                "correct": correct,
                "accuracy": accuracy,
                "mastery": mastery,
                "trend": trend,
                "avg_time_ms": avg_ms,
                "fragile": fragile,
                "last_seen": last_seen,
                "days_since": _days_since(last_seen),
                "misconceptions": _top_misconceptions(events),
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
            "model_type": "Concept-Graph Evidence Classifier",
            "classifier_description": (
                "Aggregates per-question concept tags into recency-weighted mastery "
                "(EWMA), computes trend and response-time signals, then resolves weak "
                "concepts against the prerequisite graph to report a root cause."
            ),
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
                "recency-weighted mastery (EWMA)",
                "trend across attempt history",
                "response time per question",
                "prerequisite graph position",
                "time since last correct answer",
            ],
            "is_trained": True,
        }


# ─────────────────────────────────────────────────────────────
# Data access
# ─────────────────────────────────────────────────────────────
def _load_attempts(student_id, db_path):
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT qa.concept_tags, qa.is_correct, qa.student_answer, qa.correct_answer,
                  qa.chosen_option_text,
                  COALESCE(qa.time_taken_ms, 0) AS time_taken_ms,
                  qr.timestamp, qr.difficulty, qr.topic
           FROM question_attempts qa
           JOIN quiz_results qr ON qa.quiz_result_id = qr.id
           WHERE qr.student_id = ?
           ORDER BY qr.timestamp ASC, qa.question_index ASC""",
        (student_id,),
    ).fetchall()
    conn.close()

    attempts = []
    for row in rows:
        try:
            tags = json.loads(row["concept_tags"]) or []
        except (ValueError, TypeError):
            tags = []
        attempts.append({
            "concept_tags": tags,
            "is_correct": bool(row["is_correct"]),
            "student_answer": row["student_answer"],
            "correct_answer": row["correct_answer"],
            "chosen_option_text": row["chosen_option_text"],
            "time_taken_ms": row["time_taken_ms"] or 0,
            "timestamp": row["timestamp"],
            "difficulty": row["difficulty"],
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
        "recommendation_input": {
            "primary_weak_topic": None,
            "weak_topic_count": 0,
            "overall_performance": 0.0,
            "root_causes": [],
            "due_for_review": [],
            "trend_summary": {},
            "concepts_seen": 0,
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
