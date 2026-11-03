"""
=============================================================================
EduGen - JSON API
=============================================================================
Every endpoint that touches student data derives the student id from the
session, never from the request body. There is no way to read another
student's record by changing a number.

Groups
------
  /api/auth/*         signup, login, logout, me
  /api/session        Coordinator Agent: run the full pipeline
  /api/analysis       Performance Analysis Agent report
  /api/recommendation Adaptive Content Agent decision (+ accept / override)
  /api/lesson/*       Concept Clarifier: generate a lesson
  /api/quiz/*         start, submit, result, history
  /api/rag/*          knowledge base status and search
  /api/logs           agent activity log polling
  /api/concepts       the 44-concept ontology for the UI
=============================================================================
"""

import json

from flask import Blueprint, current_app, jsonify, request, session

from core import auth
from core.agent_log import add_log, clear_logs, get_logs
from core.auth import AuthError, api_login_required, current_student_id, current_user
from core.concepts import (
    CONCEPTS,
    DIFFICULTIES,
    MODULE_TO_LEGACY_TOPIC,
    concept_title,
    module_of,
    module_summary,
)
from core.db import get_db
from core.db_repo import (
    record_concept_mastery,
    record_generated_questions,
    record_submission_history,
)

bp = Blueprint("api", __name__, url_prefix="/api")


def agents():
    return current_app.extensions["edugen"]


# ═════════════════════════════════════════════════════════════
# Auth
# ═════════════════════════════════════════════════════════════
@bp.post("/auth/signup")
def api_signup():
    data = request.get_json(silent=True) or {}
    try:
        user = auth.signup(data.get("name"), data.get("email"), data.get("password"))
    except AuthError as err:
        return jsonify({"error": err.message}), err.status
    return jsonify(user), 201


@bp.post("/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    try:
        user = auth.login(data.get("email"), data.get("password"))
    except AuthError as err:
        return jsonify({"error": err.message}), err.status
    return jsonify(user), 200


@bp.post("/auth/logout")
def api_logout():
    auth.logout()
    return jsonify({"status": "signed out"})


@bp.get("/auth/me")
def api_me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False}), 200
    return jsonify({"authenticated": True, "user": user})


# ═════════════════════════════════════════════════════════════
# Coordinator: the one endpoint that runs the whole pipeline
# ═════════════════════════════════════════════════════════════
@bp.get("/session")
@api_login_required
def api_session():
    student_id = current_student_id()
    mode = request.args.get("mode", "lesson")
    generate = request.args.get("generate", "1") != "0"
    result = agents()["coordinator"].handle_student_visit(
        student_id, mode=mode, generate=generate)

    if result.get("rule") and result.get("focus_concept"):
        _record_recommendation(student_id, result)
    return jsonify(result)


def _record_recommendation(student_id, result):
    conn = get_db()
    conn.execute(
        """INSERT INTO recommendations
           (student_id, focus_concept, difficulty, action, reasoning, accepted)
           VALUES (?, ?, ?, ?, ?, NULL)""",
        (student_id, result["focus_concept"], result["recommended_difficulty"],
         result["action"], result["reasoning"]),
    )
    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════
# Performance Analysis Agent
# ═════════════════════════════════════════════════════════════
@bp.get("/analysis")
@api_login_required
def api_analysis():
    student_id = current_student_id()
    add_log("Coordinator", "Analysis requested for student {}".format(student_id))
    report = agents()["pa"].analyze_student(student_id)
    report["model_info"] = agents()["pa"].get_model_info()
    return jsonify(report)


# ═════════════════════════════════════════════════════════════
# Adaptive Content Agent
# ═════════════════════════════════════════════════════════════
@bp.get("/recommendation")
@api_login_required
def api_recommendation():
    student_id = current_student_id()
    mode = request.args.get("mode", "lesson")
    report = agents()["pa"].analyze_student(student_id)
    decision = agents()["ac"].decide(report, mode=mode)
    decision["analysis_summary"] = {
        "overall_performance": report["overall_performance"],
        "weak_count": len(report["weak_topics"]),
        "quizzes": report["total_quizzes_taken"],
    }
    return jsonify(decision)


@bp.post("/recommendation/respond")
@api_login_required
def api_recommendation_respond():
    """Record whether the student accepted the agent's suggestion or overrode it."""
    student_id = current_student_id()
    data = request.get_json(silent=True) or {}
    accepted = bool(data.get("accepted"))
    final_concept = data.get("concept")
    final_difficulty = data.get("difficulty")

    if final_concept and final_concept not in CONCEPTS:
        return jsonify({"error": "Unknown concept"}), 400
    if final_difficulty and final_difficulty not in DIFFICULTIES:
        return jsonify({"error": "Unknown difficulty"}), 400

    conn = get_db()
    row = conn.execute(
        """SELECT id FROM recommendations WHERE student_id = ?
           ORDER BY id DESC LIMIT 1""", (student_id,)).fetchone()
    if row:
        conn.execute(
            """UPDATE recommendations
               SET accepted = ?, final_concept = ?, final_difficulty = ?
               WHERE id = ?""",
            (1 if accepted else 0, final_concept, final_difficulty, row["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO recommendations
               (student_id, focus_concept, difficulty, action, reasoning,
                accepted, final_concept, final_difficulty)
               VALUES (?, ?, ?, 'manual', 'Student chose directly', ?, ?, ?)""",
            (student_id, final_concept, final_difficulty,
             1 if accepted else 0, final_concept, final_difficulty),
        )
    conn.commit()
    conn.close()

    add_log("Coordinator",
            "Student {} the recommendation -> {} ({})".format(
                "accepted" if accepted else "overrode",
                concept_title(final_concept) if final_concept else "-", final_difficulty),
            "success" if accepted else "warning")

    return jsonify({"status": "recorded", "accepted": accepted,
                    "concept": final_concept, "difficulty": final_difficulty})


@bp.get("/recommendation/stats")
@api_login_required
def api_recommendation_stats():
    """How often does this student trust the agent? Useful for FYP evaluation."""
    student_id = current_student_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT accepted FROM recommendations WHERE student_id = ? AND accepted IS NOT NULL",
        (student_id,)).fetchall()
    conn.close()
    total = len(rows)
    accepted = sum(1 for r in rows if r["accepted"])
    return jsonify({
        "total_decisions": total,
        "accepted": accepted,
        "overridden": total - accepted,
        "acceptance_rate": round(100.0 * accepted / total, 1) if total else None,
    })


# ═════════════════════════════════════════════════════════════
# Concept Clarifier: lessons
# ═════════════════════════════════════════════════════════════
@bp.get("/lesson/<concept>/<difficulty>")
@api_login_required
def api_lesson(concept, difficulty):
    if concept not in CONCEPTS:
        return jsonify({"error": "Unknown concept '{}'".format(concept)}), 400
    if difficulty not in DIFFICULTIES:
        difficulty = "Easy"

    student_id = current_student_id()
    focus_notes = _focus_notes_for(student_id, concept)
    lesson = agents()["coordinator"].request_lesson(
        concept, difficulty, student_id=student_id, focus_notes=focus_notes)

    conn = get_db()
    conn.execute(
        "INSERT INTO lesson_views (student_id, concept, difficulty, source) VALUES (?, ?, ?, ?)",
        (student_id, concept, difficulty, lesson.get("generated_by")),
    )
    conn.commit()
    conn.close()
    return jsonify(lesson)


def _focus_notes_for(student_id, concept):
    """Personalise the brief with this student's recorded misconceptions."""
    try:
        report = agents()["pa"].analyze_student(student_id)
        stat = report["concept_stats"].get(concept)
        if not stat:
            return []
        notes = []
        for miss in (stat.get("misconceptions") or [])[:2]:
            notes.append('The student repeatedly chose: "{}" - correct that directly.'.format(
                miss["answer"]))
        if stat.get("trend") == "declining":
            notes.append("The student's results on this concept are slipping - rebuild it from first principles.")
        return notes
    except Exception:                                              # noqa: BLE001
        return []


# ═════════════════════════════════════════════════════════════
# Quiz
# ═════════════════════════════════════════════════════════════
@bp.post("/quiz/start")
@api_login_required
def api_quiz_start():
    """
    Create a quiz and store it server-side.
    Accepts optional kind ('practice' default|'diagnostic'|'reevaluation') and concepts.
    Builds the blueprint, calls the Clarifier, stores the full question records in
    quiz_sessions.payload_json, and returns questions (index, question, options).
    If kind == 'diagnostic', serves a prebuilt diagnostic set unseen by the student if available.
    """
    from pathlib import Path
    from core.db_repo import compute_question_hash

    student_id = current_student_id()
    data = request.get_json(silent=True) or {}
    kind = data.get("kind", "practice")
    concept = data.get("concept")
    concepts = data.get("concepts")
    difficulty = data.get("difficulty")
    raw_n = data.get("n") if data.get("n") is not None else data.get("count")
    default_n = 8 if kind == "probe" else 5
    count = max(1, min(int(raw_n if raw_n is not None else default_n), 12))

    payload = None
    main_concept = concept
    main_diff = difficulty

    # Prebuilt diagnostic set check (Phase 4B)
    if kind == "diagnostic":
        diag_dir = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "diagnostic"
        set_files = sorted(list(diag_dir.glob("set_*.json")))
        if set_files:
            conn = get_db()
            seen_hashes = {
                r["text_hash"]
                for r in conn.execute(
                    """SELECT q.text_hash FROM questions q
                       JOIN student_question_history sqh ON q.id = sqh.question_id
                       WHERE sqh.student_id = ?""",
                    (student_id,),
                ).fetchall()
            }
            conn.close()

            chosen_payload = None
            best_overlap = float("inf")
            for sf in set_files:
                try:
                    with open(sf, "r", encoding="utf-8") as f:
                        s_data = json.load(f)
                    s_questions = s_data.get("questions") or []
                    if not s_questions:
                        continue
                    overlap = sum(
                        1
                        for q in s_questions
                        if compute_question_hash(q.get("question", "")) in seen_hashes
                    )
                    if overlap == 0:
                        chosen_payload = s_data
                        break
                    elif overlap < best_overlap:
                        best_overlap = overlap
                        chosen_payload = s_data
                except Exception:
                    continue

            if chosen_payload and chosen_payload.get("questions"):
                payload = dict(chosen_payload)
                payload["generated_by"] = "prebuilt_diagnostic"
                main_concept = payload.get("concept") or "class-definition"
                main_diff = payload.get("difficulty") or "Medium"
                add_log("Coordinator", f"Serving prebuilt diagnostic quiz ({payload.get('set_name', 'diagnostic')})")
                br = payload.get("build_report") or {}
                br["served_from_pool"] = len(payload["questions"])
                br["generated_live"] = 0
                br["pool_hit_rate"] = 1.0
                payload["build_report"] = br

    # Verified Pool & Live Fallback (Phase 4C)
    if payload is None:
        from core.quiz_engine import build_blueprint, select_from_pool, select_probe_set
        from core.token_budget import are_all_models_exhausted

        slots = build_blueprint(
            kind=kind,
            student_id=student_id,
            concepts=concepts or ([concept] if concept else None),
            concept=concept,
            n=count,
            difficulty=difficulty,
        )

        main_concept = concept or (slots[0]["concept"] if slots else "class-definition")
        main_diff = difficulty or (slots[0]["difficulty"] if slots else "Easy")

        add_log("Coordinator", "Quiz requested: kind='{}', concept='{}' ({})".format(
            kind, main_concept, main_diff))

        # 1. Serve from verified active pool first
        if kind == "probe":
            pool_served, unfilled_slots = select_probe_set(slots, student_id=student_id)
        else:
            pool_served, unfilled_slots = select_from_pool(slots, student_id=student_id)

        live_questions = []
        live_payload = {}
        clarifier = agents()["cc"]

        if unfilled_slots:
            if are_all_models_exhausted(clarifier.model, clarifier.fallback_model):
                add_log("Coordinator", "Daily LLM budget reached and pool cannot fill all slots", "warning")
                return jsonify({
                    "error": "Daily LLM budget reached",
                    "code": "budget_exhausted",
                }), 503

            # 2. Live generation ONLY for unfilled slots
            live_payload = clarifier.generate_quiz_from_blueprint(
                unfilled_slots,
                student_id=student_id,
                focus_notes=_focus_notes_for(student_id, main_concept) if main_concept else [],
                prior_questions=pool_served,
                allow_partial=True,
            )
            live_questions = live_payload.get("questions") or []

            # Stash verified live questions into pool
            if live_questions:
                record_generated_questions(
                    main_concept,
                    main_diff,
                    live_questions,
                    model=live_payload.get("model"),
                    source=live_payload.get("generated_by", "llm_rag"),
                    origin="generated",
                    pool_status="active",
                )

        combined_questions = pool_served + live_questions
        if not combined_questions:
            return jsonify({
                "error": live_payload.get("error") or "No questions could be generated for that quiz.",
                "code": "generation_unavailable",
            }), 503

        # Merge build reports
        live_br = live_payload.get("build_report") or {}
        served_pool_count = len(pool_served)
        gen_live_count = len(live_questions)
        hit_rate = round(served_pool_count / len(slots), 2) if slots else 1.0

        merged_br = {
            "requested": len(slots),
            "accepted": len(combined_questions),
            "served_from_pool": served_pool_count,
            "generated_live": gen_live_count,
            "pool_hit_rate": hit_rate,
            "rejected_by_reason": dict(live_br.get("rejected_by_reason") or {}),
            "groups": live_br.get("groups", 0),
            "latency_ms": live_br.get("latency_ms", 0.0),
            "models": live_br.get("models", []),
            "java_check": live_br.get("java_check", "available"),
            "dedupe": live_br.get("dedupe", "vector"),
            "verifier_tags_removed": live_br.get("verifier_tags_removed", 0),
            "stage_timings_ms": live_br.get("stage_timings_ms", {}),
            "warnings": live_br.get("warnings", []),
        }

        if kind == "probe":
            targets_requested = sorted(list({t for s in slots for t in s.get("target_misconceptions", [])}))
            targets_covered = sorted(list({
                m for q in combined_questions
                for m in (q.get("option_misconception_ids") or [])
                if m and m in targets_requested
            }))
            merged_br["probe"] = {
                "concept": main_concept,
                "targets_requested": len(targets_requested),
                "targets_covered": len(targets_covered),
                "served_from_pool": served_pool_count,
                "generated_live": gen_live_count,
            }

        gen_source = "pool" if not gen_live_count else ("pool+llm" if served_pool_count else live_payload.get("generated_by", "llm"))
        payload = {
            "concept": main_concept,
            "concept_title": concept_title(main_concept) if main_concept else "",
            "difficulty": main_diff,
            "questions": combined_questions,
            "total_generated": len(combined_questions),
            "grounded": live_payload.get("grounded", False),
            "sources": live_payload.get("sources", []),
            "generated_by": gen_source,
            "model": live_payload.get("model"),
            "build_report": merged_br,
        }

    questions = payload.get("questions") or []
    if not questions:
        return jsonify({
            "error": payload.get("error") or "No questions could be generated for that quiz.",
            "code": "generation_unavailable",
        }), 503

    # Phase 1 & 4B: Upsert generated questions into repository
    record_generated_questions(
        main_concept, main_diff, questions,
        model=payload.get("model"),
        source=payload.get("generated_by", "llm_rag"),
    )

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_sessions (student_id, concept, topic, difficulty, source, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (student_id, main_concept, MODULE_TO_LEGACY_TOPIC.get(module_of(main_concept)),
         main_diff, payload.get("generated_by", "llm"), json.dumps(payload)),
    )
    quiz_session_id = cur.lastrowid
    conn.commit()
    conn.close()

    resp = {
        "quiz_session_id": quiz_session_id,
        "concept": main_concept,
        "concept_title": concept_title(main_concept) if main_concept else "",
        "difficulty": main_diff,
        "generated_by": payload.get("generated_by"),
        "grounded": payload.get("grounded", False),
        "sources": payload.get("sources", []),
        "offline_reason": payload.get("offline_reason"),
        "questions": [
            {"index": i, "question": q["question"], "options": q["options"]}
            for i, q in enumerate(questions)
        ],
        "kind": kind,
    }
    br = payload.get("build_report")
    if br:
        rej = sum(br.get("rejected_by_reason", {}).values()) if isinstance(br.get("rejected_by_reason"), dict) else 0
        summary = {
            "requested": br.get("requested", len(questions)),
            "accepted": br.get("accepted", len(questions)),
            "rejected": rej,
        }
        if br.get("probe"):
            summary["probe"] = br["probe"]
        resp["build_report_summary"] = summary
    return jsonify(resp)


@bp.post("/quiz/submit")
@api_login_required
def api_quiz_submit():
    import collections
    from core.misconceptions import MISCONCEPTIONS

    student_id = current_student_id()
    data = request.get_json(silent=True) or {}
    quiz_session_id = data.get("quiz_session_id")
    answers = data.get("answers") or {}
    timings = data.get("timings") or {}
    duration_ms = int(data.get("duration_ms") or 0)

    conn = get_db()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM quiz_sessions WHERE id = ? AND student_id = ?",
        (quiz_session_id, student_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "That quiz session was not found."}), 404

    payload = json.loads(row["payload_json"])
    questions = payload.get("questions", [])
    concept = row["concept"]
    difficulty = row["difficulty"]
    topic = row["topic"] or MODULE_TO_LEGACY_TOPIC.get(module_of(concept)) or "General"

    score = 0
    review = []
    detected_mids = collections.defaultdict(int)

    for i, q in enumerate(questions):
        chosen = answers.get(str(i), answers.get(i, -1))
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            chosen = -1
        is_correct = (chosen == q["correct"] and chosen != -1)
        if is_correct:
            score += 1

        misconception_id = None
        if not is_correct and chosen != -1:
            opt_mids = q.get("option_misconception_ids")
            if opt_mids and 0 <= chosen < len(opt_mids):
                misconception_id = opt_mids[chosen]
            else:
                q_opts = q.get("options") or []
                if 0 <= chosen < len(q_opts) and isinstance(q_opts[chosen], dict):
                    misconception_id = q_opts[chosen].get("misconception_id")

            if misconception_id:
                detected_mids[misconception_id] += 1

        # Phase 5: Collect non-null offered misconceptions, qtype, facet, difficulty
        offered = []
        if q.get("option_misconception_ids"):
            for mid in q.get("option_misconception_ids"):
                if mid and mid not in offered:
                    offered.append(mid)
        elif q.get("options"):
            for opt in q.get("options"):
                if isinstance(opt, dict) and opt.get("misconception_id"):
                    mid = opt.get("misconception_id")
                    if mid and mid not in offered:
                        offered.append(mid)
        offered_json = json.dumps(offered) if offered else json.dumps([])
        q_qtype = q.get("qtype")
        q_facet = q.get("facet")
        q_diff = q.get("difficulty") or difficulty

        review.append({
            "index": i,
            "question": q["question"],
            "options": q["options"],
            "correct_answer": q["correct"],
            "student_answer": chosen,
            "is_correct": is_correct,
            "explanation": q.get("explanation", ""),
            "concept_tags": q.get("concept_tags", [concept]),
            "time_taken_ms": int(timings.get(str(i), 0) or 0),
            "misconception_id": misconception_id,
            "offered_misconceptions": offered_json,
            "qtype": q_qtype,
            "facet": q_facet,
            "difficulty": q_diff,
        })

    attempt_no = cur.execute(
        "SELECT COUNT(*) AS n FROM quiz_results WHERE student_id = ? AND concept = ?",
        (student_id, concept)).fetchone()["n"] + 1

    cur.execute(
        """INSERT INTO quiz_results
           (student_id, topic, concept, difficulty, score, total_questions,
            attempt_number, source, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (student_id, topic, concept, difficulty, score, len(questions),
         attempt_no, row["source"], duration_ms),
    )
    quiz_result_id = cur.lastrowid

    for item in review:
        q_idx = item["index"]
        chosen_idx = item["student_answer"]
        chosen_text = (item["options"][chosen_idx]
                       if 0 <= chosen_idx < len(item["options"]) else None)

        cur.execute(
            """INSERT INTO question_attempts
               (quiz_result_id, question_index, concept_tags, is_correct,
                student_answer, correct_answer, time_taken_ms, question_text, chosen_option_text, misconception_id,
                offered_misconceptions, qtype, facet, difficulty)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (quiz_result_id, q_idx, json.dumps(item["concept_tags"]),
             int(item["is_correct"]), chosen_idx, item["correct_answer"],
             item["time_taken_ms"], item["question"][:500], chosen_text, item.get("misconception_id"),
             item.get("offered_misconceptions"), item.get("qtype"), item.get("facet"), item.get("difficulty")),
        )

    cur.execute("UPDATE quiz_sessions SET consumed = 1 WHERE id = ?", (quiz_session_id,))
    conn.commit()
    conn.close()

    # Phase 1: Record per-question student history and update question counters
    record_submission_history(student_id, quiz_result_id, questions, answers, timings)

    # Phase 1: Upsert concept mastery and append mastery history
    try:
        pa_report = agents()["pa"].analyze_student(student_id)
        if pa_report and "concept_stats" in pa_report:
            record_concept_mastery(student_id, pa_report["concept_stats"], quiz_result_id=quiz_result_id)
    except Exception as exc:
        add_log("Database", f"Concept mastery update failed: {exc}", "warning")

    pct = round(100.0 * score / len(questions), 1) if questions else 0.0
    add_log("Coordinator", "Quiz marked: {}/{} ({}%) on {}".format(
        score, len(questions), pct, concept_title(concept)), "success")
    add_log("Performance Analysis",
            "New evidence recorded for '{}' - mastery will be recomputed".format(
                concept_title(concept)))

    misconceptions_detected = []
    for mid, count in sorted(detected_mids.items(), key=lambda x: (-x[1], x[0])):
        m_item = MISCONCEPTIONS.get(mid, {})
        misconceptions_detected.append({
            "id": mid,
            "title": m_item.get("title", mid),
            "wrong_belief": m_item.get("wrong_belief", ""),
            "correct_idea": m_item.get("correct_idea", ""),
            "count": count,
        })

    return jsonify({
        "quiz_result_id": quiz_result_id,
        "score": score,
        "total": len(questions),
        "percentage": pct,
        "attempt_number": attempt_no,
        "concept": concept,
        "concept_title": concept_title(concept) if concept else "",
        "difficulty": difficulty,
        "review": review,
        "misconceptions_detected": misconceptions_detected,
    })


@bp.get("/quiz/result/<int:result_id>")
@api_login_required
def api_quiz_result(result_id):
    student_id = current_student_id()
    conn = get_db()
    result = conn.execute(
        "SELECT * FROM quiz_results WHERE id = ? AND student_id = ?",
        (result_id, student_id)).fetchone()
    if not result:
        conn.close()
        return jsonify({"error": "Result not found"}), 404

    attempts = conn.execute(
        "SELECT * FROM question_attempts WHERE quiz_result_id = ? ORDER BY question_index",
        (result_id,)).fetchall()
    session_row = conn.execute(
        """SELECT payload_json FROM quiz_sessions
           WHERE student_id = ? AND concept = ? AND consumed = 1
           ORDER BY id DESC LIMIT 1""",
        (student_id, result["concept"])).fetchone()
    conn.close()

    questions = []
    if session_row:
        try:
            questions = json.loads(session_row["payload_json"]).get("questions", [])
        except ValueError:
            questions = []

    review = []
    for att in attempts:
        idx = att["question_index"]
        q = questions[idx] if idx < len(questions) else {}
        review.append({
            "index": idx,
            "question": att["question_text"] or q.get("question", ""),
            "options": q.get("options", []),
            "correct_answer": att["correct_answer"],
            "student_answer": att["student_answer"],
            "is_correct": bool(att["is_correct"]),
            "explanation": q.get("explanation", ""),
            "concept_tags": json.loads(att["concept_tags"] or "[]"),
            "time_taken_ms": att["time_taken_ms"] or 0,
        })

    return jsonify({
        "quiz_result_id": result["id"],
        "score": result["score"],
        "total": result["total_questions"],
        "percentage": round(100.0 * result["score"] / result["total_questions"], 1)
        if result["total_questions"] else 0.0,
        "attempt_number": result["attempt_number"],
        "concept": result["concept"],
        "concept_title": concept_title(result["concept"]),
        "difficulty": result["difficulty"],
        "timestamp": result["timestamp"],
        "review": review,
    })


@bp.get("/history")
@api_login_required
def api_history():
    student_id = current_student_id()
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM quiz_results WHERE student_id = ?
           ORDER BY timestamp DESC, id DESC""", (student_id,)).fetchall()
    conn.close()

    history = []
    for row in rows:
        history.append({
            "id": row["id"],
            "concept": row["concept"],
            "concept_title": concept_title(row["concept"]) if row["concept"] else row["topic"],
            "topic": row["topic"],
            "difficulty": row["difficulty"],
            "score": row["score"],
            "total_questions": row["total_questions"],
            "percentage": round(100.0 * row["score"] / row["total_questions"], 1)
            if row["total_questions"] else 0.0,
            "attempt_number": row["attempt_number"],
            "source": row["source"],
            "timestamp": row["timestamp"],
        })
    return jsonify({"history": history, "total": len(history)})


# ═════════════════════════════════════════════════════════════
# RAG
# ═════════════════════════════════════════════════════════════
@bp.get("/rag/status")
def api_rag_status():
    return jsonify(agents()["retriever"].status())


@bp.get("/rag/search")
@api_login_required
def api_rag_search():
    query = (request.args.get("q") or "").strip()
    concept = request.args.get("concept") or None
    if not query and not concept:
        return jsonify({"error": "Type something to search for."}), 400
    if not query:
        query = concept.replace("-", " ")

    add_log("Retriever", "Knowledge-base search: '{}'".format(query[:60]))
    result = agents()["retriever"].search_raw(
        query, top_k=int(request.args.get("k", 8)),
        concept_tags=[concept] if concept in CONCEPTS else None)
    return jsonify(result)


@bp.get("/rag/brief/<concept>/<difficulty>")
@api_login_required
def api_rag_brief(concept, difficulty):
    """Show the exact retrieval brief and what it pulls back - used by /pipeline."""
    from rag.retriever import Retriever
    if concept not in CONCEPTS:
        return jsonify({"error": "Unknown concept"}), 400
    brief = Retriever.build_brief(concept, difficulty, mode=request.args.get("mode", "lesson"))
    result = agents()["retriever"].retrieve(brief)
    return jsonify({"brief": brief, "retrieval": result})


# ═════════════════════════════════════════════════════════════
# Meta
# ═════════════════════════════════════════════════════════════
@bp.get("/concepts")
def api_concepts():
    return jsonify({
        "modules": module_summary(),
        "difficulties": DIFFICULTIES,
        "total_concepts": len(CONCEPTS),
    })


@bp.get("/status")
def api_status():
    cc = agents()["cc"]
    rag = agents()["retriever"].status()
    return jsonify({
        "agents": {
            "coordinator": {"state": "active", "role": "Routing and orchestration"},
            "performance_analysis": {"state": "active",
                                     "role": "Concept mastery and root-cause analysis"},
            "adaptive_content": {"state": "active",
                                 "role": "Decides the next concept and difficulty"},
            "concept_clarifier": {
                "state": "active" if cc.llm_available else "offline",
                "role": "RAG-grounded lesson and quiz generation",
                "detail": cc.status(),
            },
        },
        "rag": {
            "ready": rag.get("ready"),
            "chunks": rag.get("chunk_count"),
            "embedder": rag.get("embedder"),
            "sources": len(rag.get("sources", {})),
            "covered_concepts": rag.get("covered_concepts"),
            "error": rag.get("error"),
        },
    })


@bp.get("/logs")
def api_logs():
    after = request.args.get("after", 0, type=int)
    return jsonify({"logs": get_logs(after)})


@bp.post("/logs/clear")
def api_logs_clear():
    clear_logs()
    return jsonify({"status": "cleared"})


# ═════════════════════════════════════════════════════════════
# Study Plan (Phase 6)
# ═════════════════════════════════════════════════════════════
@bp.get("/plan")
@api_login_required
def api_get_plan():
    """Retrieve active study plan, coverage check, and deferred items."""
    student_id = current_student_id()
    plan = agents()["ac"].get_active_plan(student_id)
    if not plan:
        return jsonify({"plan": None, "coverage": {}, "deferred": [], "message": "No active study plan found."})
    return jsonify({
        "plan": plan,
        "coverage": plan.get("coverage", {}),
        "deferred": plan.get("deferred", []),
    })


@bp.post("/plan/build")
@api_login_required
def api_build_plan():
    """Generate or replan the active study plan for current student."""
    student_id = current_student_id()
    plan = agents()["ac"].build_plan(student_id)
    return jsonify({
        "plan": plan,
        "coverage": plan.get("coverage", {}),
        "deferred": plan.get("deferred", []),
    })


@bp.post("/plan/step/<int:step_id>/status")
@api_login_required
def api_update_step_status(step_id):
    """
    Update step lifecycle status (pending -> in_progress -> done | skipped).
    Student may only modify steps in their own active plan.
    """
    student_id = current_student_id()
    from core.db_repo import get_study_plan_step, get_study_plan_by_id

    step = get_study_plan_step(step_id)
    if not step:
        return jsonify({"error": f"Step {step_id} not found"}), 404

    plan = get_study_plan_by_id(step["plan_id"])
    if not plan or plan["student_id"] != student_id:
        return jsonify({"error": "Forbidden: You do not own this study plan step"}), 403

    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if not new_status or new_status not in ("pending", "in_progress", "done", "skipped"):
        return jsonify({"error": "Invalid status. Must be pending, in_progress, done, or skipped"}), 400

    result = agents()["ac"].update_step(step_id, status=new_status)
    return jsonify(result)


@bp.post("/plan/step/<int:step_id>/note")
@api_login_required
def api_update_step_note(step_id):
    """
    Update student note on a study plan step and rebuild prompt_text.
    Student may only modify steps in their own active plan.
    """
    student_id = current_student_id()
    from core.db_repo import get_study_plan_step, get_study_plan_by_id

    step = get_study_plan_step(step_id)
    if not step:
        return jsonify({"error": f"Step {step_id} not found"}), 404

    plan = get_study_plan_by_id(step["plan_id"])
    if not plan or plan["student_id"] != student_id:
        return jsonify({"error": "Forbidden: You do not own this study plan step"}), 403

    data = request.get_json(silent=True) or {}
    note = data.get("note", "")
    result = agents()["ac"].update_step(step_id, user_note=note)
    return jsonify(result)


# ═════════════════════════════════════════════════════════════
# Plan-Driven Lessons (Phase 7)
# ═════════════════════════════════════════════════════════════

@bp.get("/plan/step/<int:step_id>/lesson")
@api_login_required
def api_get_step_lesson(step_id):
    """
    Generate or retrieve cached plan-driven lesson for a study plan step.
    Ownership enforced. First view sets step status to 'in_progress'.
    """
    student_id = current_student_id()
    from core.db_repo import get_study_plan_by_id, get_study_plan_step, update_study_plan_step

    step = get_study_plan_step(step_id)
    if not step:
        return jsonify({"error": f"Step {step_id} not found"}), 404

    plan = get_study_plan_by_id(step["plan_id"])
    if not plan or plan["student_id"] != student_id:
        return jsonify({"error": "Forbidden: You do not own this study plan step"}), 403

    # First successful view sets step status to in_progress
    if step.get("status") == "pending":
        update_study_plan_step(step_id, status="in_progress")
        step["status"] = "in_progress"

    res = agents()["cc"].generate_step_lesson(step, student_id=student_id)
    return jsonify({
        "lesson": res.get("lesson"),
        "cached": res.get("cached", False),
        "verified": res.get("verified", False),
        "cache_key": res.get("cache_key"),
        "sources": res.get("sources", []),
        "step": step,
    })


@bp.post("/plan/step/<int:step_id>/lesson/feedback")
@api_login_required
def api_step_lesson_feedback(step_id):
    """
    Record student rating and optional comment on a step lesson.
    Stores feedback row with target_type='lesson', target_ref=cache_key.
    """
    student_id = current_student_id()
    from core.db_repo import get_db, get_study_plan_by_id, get_study_plan_step, record_feedback

    step = get_study_plan_step(step_id)
    if not step:
        return jsonify({"error": f"Step {step_id} not found"}), 404

    plan = get_study_plan_by_id(step["plan_id"])
    if not plan or plan["student_id"] != student_id:
        return jsonify({"error": "Forbidden: You do not own this study plan step"}), 403

    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    if rating not in (1, -1):
        return jsonify({"error": "Rating must be 1 or -1"}), 400

    comment = str(data.get("comment", ""))[:300] if data.get("comment") else None
    cache_key = data.get("cache_key")
    if not cache_key:
        conn = get_db()
        row = conn.execute(
            "SELECT cache_key FROM lesson_cache WHERE plan_step_id = ? ORDER BY id DESC LIMIT 1",
            (step_id,),
        ).fetchone()
        cache_key = row["cache_key"] if row else f"step_{step_id}"

    record_feedback(
        student_id=student_id,
        target_type="lesson",
        target_ref=cache_key,
        rating=rating,
        comment=comment,
    )
    return jsonify({"ok": True, "message": "Feedback recorded."})


@bp.post("/plan/step/<int:step_id>/lesson/regenerate")
@api_login_required
def api_step_lesson_regenerate(step_id):
    """
    Regenerate step lesson, bypassing cache once (max 3 regenerations per step per day).
    Replaces cached entry and returns fresh lesson.
    """
    student_id = current_student_id()
    from core.db_repo import (
        count_step_regenerations_today,
        get_study_plan_by_id,
        get_study_plan_step,
        record_llm_call,
    )

    step = get_study_plan_step(step_id)
    if not step:
        return jsonify({"error": f"Step {step_id} not found"}), 404

    plan = get_study_plan_by_id(step["plan_id"])
    if not plan or plan["student_id"] != student_id:
        return jsonify({"error": "Forbidden: You do not own this study plan step"}), 403

    # Enforce limit: max 3 regenerations per step per day
    regen_count = count_step_regenerations_today(step_id)
    if regen_count >= 3:
        return jsonify({"error": "Maximum of 3 lesson regenerations per step per day reached."}), 429

    record_llm_call(
        student_id=student_id,
        agent="Concept Clarifier",
        purpose=f"step_regen_{step_id}",
        model=agents()["cc"].model,
        latency_ms=0,
        ok=True,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
    )

    res = agents()["cc"].generate_step_lesson(step, student_id=student_id, force_refresh=True)
    return jsonify({
        "lesson": res.get("lesson"),
        "cached": res.get("cached", False),
        "verified": res.get("verified", False),
        "cache_key": res.get("cache_key"),
        "sources": res.get("sources", []),
        "step": step,
    })

