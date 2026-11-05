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

import json
import threading
import time
from typing import Any, Dict, List, Optional

from core.agent_log import add_log
from core.event_bus import emit, handoff, pipeline_run, run_in_thread_with_context
from core.concepts import ENTRY_CONCEPT, concept_title
from core.db import get_db
from core.db_repo import (
    get_student_journey,
    save_student_journey,
    get_active_study_plan,
    get_study_plan_steps,
    update_study_plan_step_status,
)
from core.journey import (
    STATE_NEW,
    STATE_PLAN_ACTIVE,
    STATE_COMPLETE,
    compute_next_action,
    is_lesson_step,
    is_quiz_step,
)
from core.study_planner import plan_after_check, check_coverage, plan_step_concepts


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

    def request_quiz(self, concept, difficulty, num_questions=5, focus_notes=None, student_id=None):
        add_log("Coordinator", "Quiz requested directly: '{}' ({})".format(concept, difficulty))
        brief = self._brief(concept, difficulty, "quiz", focus_notes, student_id=student_id)
        handoff("Coordinator", "Concept Clarifier", "quiz brief for '{}'".format(concept), brief)
        return self.cc.generate_quiz(brief, num_questions=num_questions)

    # ─────────────────────────────────────────────────────────
    def _generate(self, decision, mode):
        brief = decision["retrieval_brief"]
        if mode == "quiz":
            return self.cc.generate_quiz(brief)
        return self.cc.generate_lesson(brief)

    def _brief(self, concept, difficulty, mode, focus_notes=None, student_id=None):
        from rag.retriever import Retriever
        brief = Retriever.build_brief(concept, difficulty, mode=mode)
        brief["focus_notes"] = focus_notes or []
        brief["student_id"] = student_id
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

    # ─────────────────────────────────────────────────────────
    # Phase 8: Autonomous Coordinator Loop & Journey Machine
    # ─────────────────────────────────────────────────────────
    _student_locks = {}
    _lock_mutex = threading.Lock()

    def _get_student_lock(self, student_id: int):
        with self._lock_mutex:
            if student_id not in self._student_locks:
                self._student_locks[student_id] = threading.Lock()
            return self._student_locks[student_id]

    def on_quiz_submitted(self, student_id: int, quiz_result_id: int, quiz_session_id: int = None) -> Dict[str, Any]:
        """
        3.2 Coordinator.on_quiz_submitted:
        Executes the autonomous loop after a quiz is submitted:
          - Runs inside pipeline_run(student_id, trigger='quiz_submit')
          - Per-student lock prevents race conditions
          - Idempotent: if journey.last_result_id == quiz_result_id, returns stored outcome
          - Stage 1: Performance Analysis (analyze_student)
          - Stage 2: Adaptive Content dispatch by quiz session kind/step
          - Stage 3: Compute next_action
          - Stage 4: Background prefetch of next lesson step (non-blocking)
        """
        with self._get_student_lock(student_id):
            # Idempotency check
            journey = get_student_journey(student_id)
            if journey and journey.get("last_result_id") == quiz_result_id:
                last_outcome = (journey.get("context") or {}).get("last_outcome")
                if last_outcome:
                    return last_outcome

            with pipeline_run(student_id, trigger="quiz_submit") as run_id:
                stage_summaries = []

                # Stage 1: Performance Analysis
                handoff("Coordinator", "Performance Analysis", "analyzing student mastery after quiz submit")
                analysis = self.pa.analyze_student(student_id)
                stage_summaries.append({
                    "stage": "performance_analysis",
                    "agent": "Performance Analysis",
                    "summary": f"{len(analysis.get('weak_topics', []))} weak, {len(analysis.get('strong_topics', []))} strong across {len(analysis.get('concept_stats', {}))} concepts",
                    "at": time.strftime("%H:%M:%S"),
                })

                # Stage 2: Dispatch by quiz session kind / plan step
                conn = get_db()
                q_res = conn.execute("SELECT * FROM quiz_results WHERE id = ?", (quiz_result_id,)).fetchone()
                q_sess = None
                if quiz_session_id:
                    q_sess = conn.execute("SELECT * FROM quiz_sessions WHERE id = ?", (quiz_session_id,)).fetchone()
                else:
                    q_sess = conn.execute(
                        "SELECT * FROM quiz_sessions WHERE student_id = ? ORDER BY id DESC LIMIT 1",
                        (student_id,),
                    ).fetchone()
                conn.close()

                sess_payload = {}
                if q_sess and q_sess["payload_json"]:
                    try:
                        sess_payload = json.loads(q_sess["payload_json"])
                    except Exception:
                        sess_payload = {}

                plan_step_id = sess_payload.get("plan_step_id")
                quiz_kind = sess_payload.get("kind")
                if not quiz_kind:
                    if q_res and (q_res["source"] == "prebuilt_diagnostic" or (q_res["total_questions"] or 0) >= 10):
                        quiz_kind = "diagnostic"
                    else:
                        quiz_kind = "practice"

                active_plan = self.ac.get_active_plan(student_id) if hasattr(self.ac, "get_active_plan") else None
                if not active_plan:
                    active_plan = get_active_study_plan(student_id)

                plan_changed = False
                target_concept = q_res["concept"] if q_res else "class-definition"
                state = journey.get("state", STATE_NEW) if journey else STATE_NEW

                # Case A: Diagnostic quiz or no active plan -> build full study plan
                if quiz_kind == "diagnostic" or not active_plan:
                    handoff("Performance Analysis", "Adaptive Content", "build full study plan")
                    new_plan = self.ac.build_plan(student_id, report=analysis)
                    plan_changed = True
                    active_plan = new_plan
                    steps = new_plan.get("steps", [])
                    state = STATE_COMPLETE if not steps else STATE_PLAN_ACTIVE
                    stage_summaries.append({
                        "stage": "adaptive_content",
                        "agent": "Adaptive Content",
                        "summary": f"Built study plan with {len(steps)} steps",
                        "at": time.strftime("%H:%M:%S"),
                    })

                # Case B: 'check' step quiz
                elif plan_step_id and any(s.get("id") == plan_step_id and s.get("kind") == "check" for s in active_plan.get("steps", [])):
                    handoff("Coordinator", "Adaptive Content", f"evaluating check quiz for step {plan_step_id}")
                    tot = q_res["total_questions"] if q_res and q_res["total_questions"] else len(sess_payload.get("questions", [])) or 1
                    sc = q_res["score"] if q_res else 0
                    accuracy = (sc / tot) * 100.0
                    if accuracy >= 50.0:
                        update_study_plan_step_status(plan_step_id, "done")
                    updated_plan = plan_after_check(active_plan, target_concept, accuracy, report=analysis)
                    for s in updated_plan.get("steps", []):
                        if s.get("id") == plan_step_id:
                            if accuracy >= 50.0:
                                s["status"] = "done"
                            else:
                                update_study_plan_step(step_id=plan_step_id, status="pending", prompt_text=s.get("prompt_text"))
                    if hasattr(self.ac, "save_plan"):
                        self.ac.save_plan(student_id, updated_plan)
                    plan_changed = True
                    active_plan = updated_plan
                    cov = check_coverage(active_plan, analysis)
                    emit("Adaptive Content", "coverage_check", f"Coverage refreshed after check quiz: {'OK' if cov.get('ok') else 'Violations'}",
                         output={"ok": cov.get("ok", True), "violations": cov.get("violations", [])})
                    stage_summaries.append({
                        "stage": "check_evaluation",
                        "agent": "Adaptive Content",
                        "summary": f"Check quiz on '{target_concept}' ({accuracy:.1f}%): updated plan",
                        "at": time.strftime("%H:%M:%S"),
                    })

                # Case C: 'probe' step quiz
                elif plan_step_id and any(s.get("id") == plan_step_id and s.get("kind") == "probe" for s in active_plan.get("steps", [])):
                    update_study_plan_step_status(plan_step_id, "done")
                    for s in active_plan.get("steps", []):
                        if s.get("id") == plan_step_id:
                            s["status"] = "done"

                    active_mids = [
                        m["misconception_id"] if "misconception_id" in m else m.get("id")
                        for m in analysis.get("student_misconceptions", [])
                        if m.get("status") == "active"
                    ]
                    covered_mids = set()
                    for s in active_plan.get("steps", []):
                        for m in (s.get("focus") or {}).get("misconceptions", []):
                            mid = m.get("id") or m.get("misconception_id")
                            if mid:
                                covered_mids.add(mid)

                    uncovered_active = [m for m in active_mids if m and m not in covered_mids]
                    if uncovered_active:
                        emit("Adaptive Content", "replan", f"Re-planning required: {len(uncovered_active)} active misconceptions uncovered",
                             output={"uncovered": uncovered_active})
                        new_plan = self.ac.build_plan(student_id)
                        plan_changed = True
                        active_plan = new_plan
                        stage_summaries.append({
                            "stage": "replan",
                            "agent": "Adaptive Content",
                            "summary": f"Replanned to address {len(uncovered_active)} newly active misconceptions",
                            "at": time.strftime("%H:%M:%S"),
                        })
                    else:
                        cov = check_coverage(active_plan, analysis)
                        stage_summaries.append({
                            "stage": "probe_evaluation",
                            "agent": "Coordinator",
                            "summary": "Probe quiz completed; active misconceptions covered",
                            "at": time.strftime("%H:%M:%S"),
                        })

                # Case D: 'reevaluation' step quiz
                elif plan_step_id and any(s.get("id") == plan_step_id and s.get("kind") == "reevaluation" for s in active_plan.get("steps", [])):
                    update_study_plan_step_status(plan_step_id, "done")
                    for s in active_plan.get("steps", []):
                        if s.get("id") == plan_step_id:
                            s["status"] = "done"

                    tot = q_res["total_questions"] if q_res and q_res["total_questions"] else len(sess_payload.get("questions", [])) or 1
                    sc = q_res["score"] if q_res else 0
                    accuracy = (sc / tot) * 100.0

                    if accuracy >= 50.0:
                        state = STATE_COMPLETE
                        stage_summaries.append({
                            "stage": "reevaluation",
                            "agent": "Coordinator",
                            "summary": f"Re-evaluation passed ({accuracy:.1f}%); study plan completed",
                            "at": time.strftime("%H:%M:%S"),
                        })
                    else:
                        handoff("Coordinator", "Adaptive Content", "Re-evaluating mastery and replanning from fresh performance analysis")
                        new_plan = self.ac.build_plan(student_id)
                        active_plan = new_plan
                        plan_changed = True
                        steps = new_plan.get("steps", [])
                        if not steps or all(s.get("kind") == "reevaluation" for s in steps):
                            state = STATE_COMPLETE
                        stage_summaries.append({
                            "stage": "reevaluation",
                            "agent": "Adaptive Content",
                            "summary": "Re-evaluation completed; new study plan calibrated",
                            "at": time.strftime("%H:%M:%S"),
                        })

                # Case E: Any other quiz (free practice)
                else:
                    cov = check_coverage(active_plan, analysis) if active_plan else {"ok": True, "violations": []}
                    stage_summaries.append({
                        "stage": "practice_quiz",
                        "agent": "Coordinator",
                        "summary": "Practice quiz recorded; mastery updated",
                        "at": time.strftime("%H:%M:%S"),
                    })

                # Stage 3: Compute next action
                steps = active_plan.get("steps", []) if active_plan else []
                next_act = compute_next_action(
                    state=state,
                    plan=active_plan,
                    steps=steps,
                    quiz_history_count=self._quiz_count(student_id),
                )
                if next_act.get("type") == "course_complete":
                    state = STATE_COMPLETE

                old_st = journey.get("state") if journey else STATE_NEW
                if state != old_st:
                    emit("Coordinator", "state_change", f"Journey state changed from {old_st} to {state}",
                         output={"old_state": old_st, "new_state": state})

                outcome = {
                    "pipeline": stage_summaries,
                    "next_action": next_act,
                    "plan_changed": plan_changed,
                }

                save_student_journey(
                    student_id=student_id,
                    state=state,
                    plan_id=active_plan.get("id") if active_plan else None,
                    current_step_id=next_act.get("step_id"),
                    last_run_id=run_id,
                    last_result_id=quiz_result_id,
                    context={"last_outcome": outcome},
                )

                # Stage 4: Schedule background prefetch
                if next_act.get("type") == "study_step":
                    self._schedule_prefetch(student_id, next_act, active_plan)

                return outcome

    def get_journey(self, student_id: int) -> Dict[str, Any]:
        """
        3.3 Coordinator.get_journey:
        Returns current journey state, plan summary, next_action, and progress.
        Creates student_journey row on first use.
        """
        journey = get_student_journey(student_id)
        qc = self._quiz_count(student_id)
        if not journey:
            init_state = STATE_NEW if qc == 0 else STATE_PLAN_ACTIVE
            save_student_journey(student_id, init_state)
            journey = get_student_journey(student_id)

        plan = get_active_study_plan(student_id)
        steps = get_study_plan_steps(plan["id"]) if plan else []
        if plan:
            plan["steps"] = steps

        state = journey.get("state", STATE_NEW) if journey else STATE_NEW
        next_act = compute_next_action(state, plan, steps, quiz_history_count=qc)
        steps_done = sum(1 for s in steps if str(s.get("status")).lower() in ("done", "skipped"))
        steps_total = len(steps)

        return {
            "student_id": student_id,
            "state": state,
            "plan": plan,
            "next_action": next_act,
            "progress": {
                "steps_done": steps_done,
                "steps_total": steps_total,
            },
            "last_run_id": journey.get("last_run_id") if journey else None,
        }

    def mark_ready(self, student_id: int) -> Dict[str, Any]:
        """
        3.4 Coordinator.mark_ready:
        Student action: 'I've studied this, re-evaluate me'.
        Lesson steps still 'pending' become 'skipped', steps 'in_progress' become 'done'.
        Returns next quiz step action and coverage warnings.
        """
        with self._get_student_lock(student_id):
            with pipeline_run(student_id, trigger="mark_ready") as run_id:
                plan = get_active_study_plan(student_id)
                if not plan:
                    return {"error": "No active study plan found", "next_action": None, "warnings": []}

                steps = get_study_plan_steps(plan["id"])
                for s in steps:
                    if is_lesson_step(s):
                        st = s.get("status", "pending")
                        if st == "in_progress":
                            update_study_plan_step_status(s["id"], "done")
                            s["status"] = "done"
                        elif st == "pending":
                            update_study_plan_step_status(s["id"], "skipped")
                            s["status"] = "skipped"

                plan["steps"] = steps
                analysis = self.pa.analyze_student(student_id)
                cov = check_coverage(plan, analysis)
                warnings = cov.get("violations", [])

                next_act = compute_next_action(
                    state=STATE_PLAN_ACTIVE,
                    plan=plan,
                    steps=steps,
                    quiz_history_count=self._quiz_count(student_id),
                )
                next_act["warnings"] = warnings

                emit("Coordinator", "state_change", f"Student marked ready. Pending lessons skipped. Next: {next_act.get('type')}",
                     output={"warnings_count": len(warnings), "next_action": next_act.get("type")})
                handoff("Coordinator", "Quiz Engine", f"Offered next action: {next_act.get('type')}", payload={"next_action": next_act})

                save_student_journey(
                    student_id=student_id,
                    state=STATE_PLAN_ACTIVE,
                    plan_id=plan["id"],
                    current_step_id=next_act.get("step_id"),
                    last_run_id=run_id,
                )

                return {
                    "next_action": next_act,
                    "warnings": warnings,
                    "plan_changed": True,
                }

    def on_step_done(self, student_id: int, step_id: int) -> Dict[str, Any]:
        """
        3.5 Coordinator.on_step_done:
        Called when a lesson step is completed: marks status done, refreshes coverage,
        returns new next_action, and triggers prefetch of the following lesson.
        """
        with self._get_student_lock(student_id):
            with pipeline_run(student_id, trigger="step_done") as run_id:
                update_study_plan_step_status(step_id, "done")
                plan = get_active_study_plan(student_id)
                steps = get_study_plan_steps(plan["id"]) if plan else []
                if plan:
                    plan["steps"] = steps

                analysis = self.pa.analyze_student(student_id)
                cov = check_coverage(plan, analysis) if plan else {"ok": True, "violations": []}
                emit("Adaptive Content", "coverage_check", "Coverage refreshed on step done", output={"ok": cov.get("ok", True)})

                next_act = compute_next_action(
                    state=STATE_PLAN_ACTIVE,
                    plan=plan,
                    steps=steps,
                    quiz_history_count=self._quiz_count(student_id),
                )

                if next_act.get("type") == "study_step":
                    self._schedule_prefetch(student_id, next_act, plan)

                save_student_journey(
                    student_id=student_id,
                    state=STATE_PLAN_ACTIVE,
                    plan_id=plan["id"] if plan else None,
                    current_step_id=next_act.get("step_id"),
                    last_run_id=run_id,
                )

                return {
                    "step_id": step_id,
                    "status": "done",
                    "next_action": next_act,
                }

    def _schedule_prefetch(self, student_id: int, next_action: Dict[str, Any], plan: Dict[str, Any]):
        """Schedule background prefetching of the next lesson step."""
        step_id = next_action.get("step_id")
        if not step_id or not plan:
            return

        step_obj = None
        for s in plan.get("steps", []):
            if s.get("id") == step_id:
                step_obj = s
                break
        if not step_obj:
            return

        try:
            from core.lesson_engine import build_cache_key
            from core.db_repo import get_cached_lesson
            from core.token_budget import check_daily_budget

            c = step_obj.get("concept", "")
            d = step_obj.get("difficulty", "Easy")
            st = step_obj.get("lesson_style", "detailed")
            focus = step_obj.get("focus") or {}
            focus_mis = focus.get("misconceptions") or []
            mids = [m.get("id") or m.get("misconception_id") for m in focus_mis if m.get("id") or m.get("misconception_id")]
            gap = focus.get("skill_gap")
            note = step_obj.get("user_note")
            sig = self.cc._get_index_signature() if hasattr(self.cc, "_get_index_signature") else ""
            ckey = build_cache_key(c, d, st, mids, gap, note, sig)

            cached = get_cached_lesson(ckey)
            if cached:
                return

            budget_ok, _ = check_daily_budget(2000)
            if not budget_ok:
                return
        except Exception:
            return

        def _do_prefetch():
            try:
                emit("Concept Clarifier", "prefetch_start", f"Prefetching lesson for '{c}' ({st}) in background",
                     level="info", student_id=student_id, input={"step_id": step_id, "concept": c, "style": st})
                t0 = time.time()
                res = self.cc.generate_step_lesson(step_obj, student_id=student_id, force_refresh=False)
                dur = int((time.time() - t0) * 1000)
                ver = res.get("verified", False)
                emit("Concept Clarifier", "prefetch_done", f"Prefetch complete for '{c}' in {dur}ms (verified={ver})",
                     level="success", student_id=student_id, output={"step_id": step_id, "verified": ver, "duration_ms": dur},
                     duration_ms=dur)
            except Exception as exc:
                emit("Concept Clarifier", "prefetch_done", f"Prefetch failed for '{c}': {exc}",
                     level="warn", student_id=student_id, output={"error": str(exc)})

        run_in_thread_with_context(_do_prefetch)


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
