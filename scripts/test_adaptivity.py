"""
Scenario tests for the adaptive policy. Each scenario fabricates a quiz
history, runs the real Performance Analysis and Adaptive Content agents, and
asserts which rule fires. This is the evidence for the FYP-2 evaluation
chapter: the adaptivity is deterministic and explainable.

    python scripts/test_adaptivity.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["EDUGEN_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "adapt.db")

import core.db as db                                          # noqa: E402
db.DB_PATH = os.environ["EDUGEN_DB_PATH"]
db.init_db()

import agents.performance_analysis_agent as pa_mod            # noqa: E402
pa_mod.DB_PATH = db.DB_PATH
from agents.adaptive_content_agent import AdaptiveContentAgent      # noqa: E402
from agents.performance_analysis_agent import PerformanceAnalysisAgent  # noqa: E402

PA = PerformanceAnalysisAgent()
AC = AdaptiveContentAgent()
RESULTS = []


def reset():
    conn = db.get_db()
    for table in ("question_attempts", "quiz_results", "quiz_sessions",
                  "recommendations", "students", "users"):
        conn.execute("DELETE FROM " + table)
    conn.execute("INSERT INTO students (id, name) VALUES (1, 'Scenario')")
    conn.commit()
    conn.close()


def record(concept, difficulty, outcomes, days_ago=0, time_ms=8000, wrong_text="Option B"):
    """outcomes: list of booleans, one per question."""
    when = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_results
           (student_id, topic, concept, difficulty, score, total_questions,
            attempt_number, timestamp, source)
           VALUES (1, ?, ?, ?, ?, ?, 1, ?, 'test')""",
        (concept, concept, difficulty, sum(outcomes), len(outcomes), when))
    rid = cur.lastrowid
    for i, ok in enumerate(outcomes):
        cur.execute(
            """INSERT INTO question_attempts
               (quiz_result_id, question_index, concept_tags, is_correct,
                student_answer, correct_answer, time_taken_ms, chosen_option_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, i, json.dumps([concept]), int(ok), 0 if ok else 1, 0,
             time_ms, None if ok else wrong_text))
    conn.commit()
    conn.close()


def scenario(name, expected_rule, setup, expect_concept=None):
    reset()
    setup()
    report = PA.analyze_student(1, db_path=db.DB_PATH)
    decision = AC.decide(report)
    rule_ok = decision["rule"] == expected_rule
    concept_ok = expect_concept is None or decision["focus_concept"] == expect_concept
    ok = rule_ok and concept_ok
    RESULTS.append(ok)
    print("\n  {} {}".format("PASS" if ok else "FAIL", name))
    print("     expected rule {}{}".format(
        expected_rule, " on '{}'".format(expect_concept) if expect_concept else ""))
    print("     got      rule {} -> '{}' at {} ({})".format(
        decision["rule"], decision["focus_concept"],
        decision["recommended_difficulty"], decision["action"]))
    print("     reason: {}".format(decision["reasoning"][:150]))
    return decision


print("\nAdaptive policy scenarios\n" + "=" * 66)

scenario(
    "R1 - a brand new student starts at the entry concept",
    "R1", lambda: None, expect_concept="class-definition")

scenario(
    "R2 - a weak concept whose prerequisite is also weak sends the student "
    "to the prerequisite, not the symptom",
    "R2",
    lambda: (record("method-overriding", "Medium", [False, False, False, True]),
             record("inheritance-basics", "Easy", [False, False, True, False])),
    expect_concept="inheritance-basics")

scenario(
    "R3 - a weak concept with solid prerequisites is revisited directly",
    "R3",
    lambda: (record("class-definition", "Easy", [True, True, True, True, True]),
             record("static-members", "Medium", [False, False, False, True])),
    expect_concept="static-members")

scenario(
    "R4 - a mastered concept untouched for 10 days comes back for review",
    "R4",
    lambda: record("class-definition", "Easy", [True, True, True, True], days_ago=10),
    expect_concept="class-definition")

scenario(
    "R5 - nothing failing, but a concept sits in the middle",
    "R5",
    lambda: record("class-definition", "Medium", [True, False, True, False, True]),
    expect_concept="class-definition")

scenario(
    "R6 - everything mastered, so advance to an unseen concept",
    "R6",
    lambda: (record("class-definition", "Easy", [True, True, True, True]),
             record("object-instantiation", "Easy", [True, True, True, True])))

print("\n" + "=" * 66)
print("  Signal checks")
reset()
record("this-keyword", "Easy", [False, False, False], wrong_text="it refers to the class")
record("this-keyword", "Easy", [True, True, True])
report = PA.analyze_student(1, db_path=db.DB_PATH)
stat = report["concept_stats"]["this-keyword"]

checks = [
    ("recency weighting beats raw accuracy", stat["mastery"] > stat["accuracy"],
     "mastery {} vs accuracy {}".format(stat["mastery"], stat["accuracy"])),
    ("trend detected as improving", stat["trend"] == "improving", stat["trend"]),
    ("repeated wrong answer captured as a misconception",
     len(stat["misconceptions"]) == 1, stat["misconceptions"]),
    ("response time recorded", stat["avg_time_ms"] > 0, stat["avg_time_ms"]),
]
for label, ok, detail in checks:
    RESULTS.append(ok)
    print("  {} {}  ({})".format("PASS" if ok else "FAIL", label, detail))

reset()
record("this-keyword", "Easy", [False, False, True], time_ms=3000,
       wrong_text="it refers to the class")
report = PA.analyze_student(1, db_path=db.DB_PATH)
brief = AC.decide(report)["retrieval_brief"]
ok = any("refers to the class" in n for n in brief["focus_notes"])
RESULTS.append(ok)
print("  {} misconception is forwarded into the retrieval brief".format("PASS" if ok else "FAIL"))
print("     focus notes: {}".format(brief["focus_notes"]))

print("\n" + "=" * 66)
print("  {} passed, {} failed".format(sum(RESULTS), len(RESULTS) - sum(RESULTS)))
print("=" * 66 + "\n")
sys.exit(0 if all(RESULTS) else 1)
