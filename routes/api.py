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

    The browser only ever receives the questions and the options. Correct
    answers stay in quiz_sessions until the quiz is submitted - which is how
    an LLM-generated quiz can be graded at all (FYP-1 could not do this).
    """
    student_id = current_student_id()
    data = request.get_json(silent=True) or {}
    concept = data.get("concept")
    difficulty = data.get("difficulty", "Easy")
    count = max(3, min(int(data.get("count", 5)), 10))

    if concept not in CONCEPTS:
        return jsonify({"error": "Pick a concept from the list."}), 400
    if difficulty not in DIFFICULTIES:
        return jsonify({"error": "Pick Easy, Medium or Hard."}), 400

    add_log("Coordinator", "Quiz requested: {} ({})".format(
        concept_title(concept), difficulty))

    payload = agents()["coordinator"].request_quiz(
        concept, difficulty, num_questions=count,
        focus_notes=_focus_notes_for(student_id, concept))

    questions = payload.get("questions") or []
    if not questions:
        return jsonify({
            "error": payload.get("error") or "No questions could be generated for that concept.",
            "code": "generation_unavailable",
        }), 503

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_sessions (student_id, concept, topic, difficulty, source, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (student_id, concept, MODULE_TO_LEGACY_TOPIC.get(module_of(concept)),
         difficulty, payload.get("generated_by", "llm"), json.dumps(payload)),
    )
    quiz_session_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "quiz_session_id": quiz_session_id,
        "concept": concept,
        "concept_title": concept_title(concept),
        "difficulty": difficulty,
        "generated_by": payload.get("generated_by"),
        "grounded": payload.get("grounded", False),
        "sources": payload.get("sources", []),
        "offline_reason": payload.get("offline_reason"),
        "questions": [
            {"index": i, "question": q["question"], "options": q["options"]}
            for i, q in enumerate(questions)
        ],
    })


@bp.post("/quiz/submit")
@api_login_required
def api_quiz_submit():
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
    for i, q in enumerate(questions):
        chosen = answers.get(str(i), answers.get(i, -1))
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            chosen = -1
        is_correct = chosen == q["correct"]
        if is_correct:
            score += 1
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
        chosen_text = (item["options"][item["student_answer"]]
                       if 0 <= item["student_answer"] < len(item["options"]) else None)
        cur.execute(
            """INSERT INTO question_attempts
               (quiz_result_id, question_index, concept_tags, is_correct,
                student_answer, correct_answer, time_taken_ms, question_text, chosen_option_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (quiz_result_id, item["index"], json.dumps(item["concept_tags"]),
             int(item["is_correct"]), item["student_answer"], item["correct_answer"],
             item["time_taken_ms"], item["question"][:500], chosen_text),
        )

    cur.execute("UPDATE quiz_sessions SET consumed = 1 WHERE id = ?", (quiz_session_id,))
    conn.commit()
    conn.close()

    pct = round(100.0 * score / len(questions), 1) if questions else 0.0
    add_log("Coordinator", "Quiz marked: {}/{} ({}%) on {}".format(
        score, len(questions), pct, concept_title(concept)), "success")
    add_log("Performance Analysis",
            "New evidence recorded for '{}' - mastery will be recomputed".format(
                concept_title(concept)))

    return jsonify({
        "quiz_result_id": quiz_result_id,
        "score": score,
        "total": len(questions),
        "percentage": pct,
        "attempt_number": attempt_no,
        "concept": concept,
        "concept_title": concept_title(concept),
        "difficulty": difficulty,
        "review": review,
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
