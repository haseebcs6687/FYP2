"""
=============================================================================
EduGen - Coordinator Agent  (FYP-2)
=============================================================================
Agent type : Central router and orchestration layer
Role       : Decide which agents run, in what order, with what payload, and
             record the hand-offs. No pedagogy, no analysis, no LLM calls -
             pure control flow.

Routing
-------
  first visit (no quiz history)
      Coordinator -> Concept Clarifier                 (entry concept, Easy)

  returning student
      Coordinator -> Performance Analysis              (weakness report)
                  -> Adaptive Content                  (decision + retrieval brief)
                  -> Concept Clarifier                 (RAG retrieve + LLM generate)

Every stage appends to a `trace`, which the /pipeline page renders as a live
diagram. The trace is the deliverable that proves the system is agentic rather
than a single monolithic request handler.
=============================================================================
"""

import time

from core.agent_log import add_log, handoff
from core.concepts import ENTRY_CONCEPT, concept_title
from core.db import get_db


class CoordinatorAgent(object):

    DEFAULT_CONCEPT = ENTRY_CONCEPT
    DEFAULT_DIFFICULTY = "Easy"

    def __init__(self, pa_agent, ac_agent, cc_agent, retriever=None):
        self.pa = pa_agent
        self.ac = ac_agent
        self.cc = cc_agent
        self.retriever = retriever
        print("[Coordinator] Orchestration layer initialised.")

    # ─────────────────────────────────────────────────────────
    # Session start: the single endpoint the frontend needs
    # ─────────────────────────────────────────────────────────
    def handle_student_visit(self, student_id, mode="lesson", generate=True):
        started = time.time()
        trace = []
        add_log("Coordinator", "Session request received for student {}".format(student_id))

        quiz_count = self._quiz_count(student_id)
        first_visit = quiz_count == 0

        trace.append(_stage(
            "Coordinator", "Route session",
            "First visit - skip analysis" if first_visit
            else "{} quiz attempt(s) on record - run the full pipeline".format(quiz_count),
            {"quiz_count": quiz_count, "first_visit": first_visit},
        ))

        # ── Route A: first visit ─────────────────────────────
        if first_visit:
            decision = {
                "rule": "R0",
                "focus_concept": self.DEFAULT_CONCEPT,
                "focus_title": concept_title(self.DEFAULT_CONCEPT),
                "recommended_difficulty": self.DEFAULT_DIFFICULTY,
                "action": "first_lesson",
                "reasoning": (
                    "This is your first session, so there is no performance data to adapt to yet. "
                    "We start at {} on Easy and the system begins adapting after your first quiz."
                ).format(concept_title(self.DEFAULT_CONCEPT)),
                "evidence": {"quizzes_taken": 0},
                "alternatives": [],
                "retrieval_brief": self._brief(self.DEFAULT_CONCEPT, self.DEFAULT_DIFFICULTY, mode),
            }
            handoff("Coordinator", "Concept Clarifier",
                    "introductory lesson on '{}'".format(self.DEFAULT_CONCEPT),
                    decision["retrieval_brief"])

            content = self._generate(decision, mode) if generate else None
            trace.append(_stage("Concept Clarifier", "Generate content",
                                _content_summary(content), _content_meta(content)))

            return self._package(student_id, first_visit, None, decision, content, trace, started,
                                 ["Coordinator", "Concept Clarifier"])

        # ── Route B: full pipeline ───────────────────────────
        add_log("Coordinator", "Routing to Performance Analysis Agent")
        analysis = self.pa.analyze_student(student_id)
        trace.append(_stage(
            "Performance Analysis", "Analyse concept mastery",
            "{} weak, {} moderate, {} strong across {} concepts (overall {}%)".format(
                len(analysis["weak_topics"]), len(analysis["moderate_topics"]),
                len(analysis["strong_topics"]), len(analysis["concept_stats"]),
                analysis["overall_performance"]),
            {
                "weak": [w["concept_tag"] for w in analysis["weak_topics"][:5]],
                "root_causes": [r["teach_first"] for r in analysis["root_causes"][:3]],
                "overall": analysis["overall_performance"],
            },
        ))
        handoff("Performance Analysis", "Adaptive Content", "weakness report", {
            "weak_count": len(analysis["weak_topics"]),
            "primary": analysis["recommendation_input"]["primary_weak_topic"],
        })

        decision = self.ac.decide(analysis, mode=mode)
        trace.append(_stage(
            "Adaptive Content", "Decide next step",
            "{} -> teach '{}' at {}".format(decision["rule"], decision["focus_title"],
                                            decision["recommended_difficulty"]),
            {
                "rule": decision["rule"],
                "action": decision["action"],
                "concept": decision["focus_concept"],
                "difficulty": decision["recommended_difficulty"],
                "evidence": decision["evidence"],
            },
        ))
        handoff("Adaptive Content", "Concept Clarifier", "retrieval brief for '{}'".format(
            decision["focus_concept"]), decision["retrieval_brief"])

        content = self._generate(decision, mode) if generate else None
        trace.append(_stage("Concept Clarifier", "Retrieve and generate",
                            _content_summary(content), _content_meta(content)))

        return self._package(
            student_id, first_visit, analysis, decision, content, trace, started,
            ["Coordinator", "Performance Analysis", "Adaptive Content", "Concept Clarifier"],
        )

    # ─────────────────────────────────────────────────────────
    # Direct requests (student picked a concept themselves)
    # ─────────────────────────────────────────────────────────
    def request_lesson(self, concept, difficulty, student_id=None, focus_notes=None):
        add_log("Coordinator", "Lesson requested directly: '{}' ({})".format(concept, difficulty))
        brief = self._brief(concept, difficulty, "lesson", focus_notes)
        handoff("Coordinator", "Concept Clarifier", "lesson brief for '{}'".format(concept), brief)
        return self.cc.generate_lesson(brief)

    def request_quiz(self, concept, difficulty, num_questions=5, focus_notes=None):
        add_log("Coordinator", "Quiz requested directly: '{}' ({})".format(concept, difficulty))
        brief = self._brief(concept, difficulty, "quiz", focus_notes)
        handoff("Coordinator", "Concept Clarifier", "quiz brief for '{}'".format(concept), brief)
        return self.cc.generate_quiz(brief, num_questions=num_questions)

    # ─────────────────────────────────────────────────────────
    def _generate(self, decision, mode):
        brief = decision["retrieval_brief"]
        if mode == "quiz":
            return self.cc.generate_quiz(brief)
        return self.cc.generate_lesson(brief)

    def _brief(self, concept, difficulty, mode, focus_notes=None):
        from rag.retriever import Retriever
        brief = Retriever.build_brief(concept, difficulty, mode=mode)
        brief["focus_notes"] = focus_notes or []
        brief["issued_by"] = "Coordinator Agent"
        brief["concept_title"] = concept_title(concept)
        return brief

    def _quiz_count(self, student_id):
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM quiz_results WHERE student_id = ?", (student_id,)
        ).fetchone()
        conn.close()
        return row["n"] if row else 0

    def _package(self, student_id, first_visit, analysis, decision, content, trace, started, flow):
        elapsed = int((time.time() - started) * 1000)
        add_log("Coordinator", "Session assembled in {} ms".format(elapsed), "success")
        return {
            "student_id": student_id,
            "first_visit": first_visit,
            "pipeline_flow": flow,
            "trace": trace,
            "elapsed_ms": elapsed,
            "focus_concept": decision["focus_concept"],
            "focus_title": decision.get("focus_title", concept_title(decision["focus_concept"])),
            "recommended_difficulty": decision["recommended_difficulty"],
            "action": decision["action"],
            "rule": decision.get("rule"),
            "reasoning": decision["reasoning"],
            "evidence": decision.get("evidence", {}),
            "alternatives": decision.get("alternatives", []),
            "retrieval_brief": decision.get("retrieval_brief"),
            "analysis": _analysis_summary(analysis),
            "lesson": content if (content and "questions" not in (content or {})) else None,
            "quiz": content if (content and "questions" in (content or {})) else None,
        }


# ─────────────────────────────────────────────────────────────
def _stage(agent, action, summary, payload=None):
    return {
        "agent": agent,
        "action": action,
        "summary": summary,
        "payload": payload or {},
        "at": time.strftime("%H:%M:%S"),
    }


def _content_summary(content):
    if not content:
        return "Skipped (metadata-only request)"
    if "questions" in content:
        return "{} questions via {}".format(len(content.get("questions", [])),
                                            content.get("generated_by"))
    return "Lesson '{}' via {}".format(content.get("title", ""), content.get("generated_by"))


def _content_meta(content):
    if not content:
        return {}
    return {
        "generated_by": content.get("generated_by"),
        "grounded": content.get("grounded"),
        "sources": [c["source"] for c in content.get("sources", [])][:5],
        "model": content.get("model"),
    }


def _analysis_summary(analysis):
    if not analysis:
        return None
    return {
        "overall_performance": analysis["overall_performance"],
        "total_quizzes_taken": analysis["total_quizzes_taken"],
        "weak_topics": analysis["weak_topics"][:6],
        "moderate_topics": analysis["moderate_topics"][:6],
        "strong_topics": analysis["strong_topics"][:6],
        "root_causes": analysis["root_causes"][:3],
        "due_for_review": analysis["due_for_review"][:3],
        "module_breakdown": analysis["module_breakdown"],
    }
