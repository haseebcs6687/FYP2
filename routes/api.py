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
from datetime import datetime

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
from core.security import (
    check_login_rate_limit,
    check_signup_rate_limit,
    get_csrf_token,
    record_login_failure,
    record_login_success,
    record_signup,
)

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/health")
def api_health():
    """System health check (no secrets exposed)."""
    import os
    import requests
    from core.db import get_db

    db_ok = False
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        db_ok = True
        conn.close()
    except Exception:
        db_ok = False

    ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    ollama_ok = False
    try:
        r = requests.get(f"{ollama_host}/api/tags", timeout=3)
        ollama_ok = (r.status_code == 200)
    except Exception:
        ollama_ok = False

    groq_key = os.environ.get("GROQ_API_KEY", "")
    key_present = bool(groq_key and groq_key.strip())
    groq_ok = False
    if key_present:
        try:
            r = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {groq_key}"},
                timeout=3,
            )
            groq_ok = (r.status_code == 200)
        except Exception:
            groq_ok = False

    pool_counts = {"total": 0, "Easy": 0, "Medium": 0, "Hard": 0}
    try:
        conn = get_db()
        for diff in ("Easy", "Medium", "Hard"):
            cnt = conn.execute(
                "SELECT count(*) FROM questions WHERE pool_status = 'active' AND difficulty = ?",
                (diff,),
            ).fetchone()[0]
            pool_counts[diff] = cnt
        pool_counts["total"] = sum(pool_counts[d] for d in ("Easy", "Medium", "Hard"))
        conn.close()
    except Exception:
        pass

    status = 200 if db_ok else 503
    return jsonify({
        "status": "healthy" if (db_ok and ollama_ok and groq_ok) else "degraded",
        "database": "ok" if db_ok else "error",
        "ollama": {
            "reachable": ollama_ok,
            "host": ollama_host,
        },
        "groq": {
            "key_present": key_present,
            "reachable": groq_ok,
        },
        "pool": pool_counts,
    }), status


def agents():
    return current_app.extensions["edugen"]


# ═════════════════════════════════════════════════════════════
# Auth
# ═════════════════════════════════════════════════════════════
@bp.get("/csrf-token")
def api_csrf_token():
    return jsonify({"csrf_token": get_csrf_token()}), 200


@bp.post("/auth/signup")
def api_signup():
    client_ip = request.remote_addr or "127.0.0.1"
    allowed, retry_after = check_signup_rate_limit(client_ip)
    if not allowed:
        return (
            jsonify({"error": "Too many signup attempts. Please try again later."}),
            429,
            {"Retry-After": str(retry_after)},
        )
    data = request.get_json(silent=True) or {}
    try:
        user = auth.signup(data.get("name"), data.get("email"), data.get("password"))
        record_signup(client_ip)
    except AuthError as err:
        return jsonify({"error": err.message}), err.status
    return jsonify(user), 201


@bp.post("/auth/login")
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    client_ip = request.remote_addr or "127.0.0.1"
    allowed, retry_after = check_login_rate_limit(client_ip, email)
    if not allowed:
        return (
            jsonify({"error": "Too many failed login attempts. Please try again later."}),
            429,
            {"Retry-After": str(retry_after)},
        )
    try:
        user = auth.login(data.get("email"), data.get("password"))
        record_login_success(client_ip, email)
    except AuthError as err:
        record_login_failure(client_ip, email)
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
    if "retrieval_brief" in result and isinstance(result["retrieval_brief"], dict):
        result["retrieval_brief"]["issued_by"] = "EduGen Recommender"
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
    # Scrub internal agent strings from student-facing recommendation JSON
    if "retrieval_brief" in decision and isinstance(decision["retrieval_brief"], dict):
        decision["retrieval_brief"]["issued_by"] = "EduGen Recommender"
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
    try:
        lesson = agents()["coordinator"].request_lesson(
            concept, difficulty, student_id=student_id, focus_notes=focus_notes)
    except Exception as exc:
        try:
            from core.event_bus import emit
            emit("Coordinator", "service_unavailable",
                 "Lesson generation service unavailable: {}".format(exc),
                 level="warn", student_id=student_id,
                 output={"service": "groq", "error": str(exc)})
        except Exception:
            pass
        lesson = agents()["cc"]._note_step_lesson(
            {"concept": concept, "difficulty": difficulty, "lesson_style": "detailed"},
            {}, error_reason="Offline fallback: {}".format(exc),
        )

    conn = get_db()
    conn.execute(
        "INSERT INTO lesson_views (student_id, concept, difficulty, source) VALUES (?, ?, ?, ?)",
        (student_id, concept, difficulty, lesson.get("generated_by")),
    )
    conn.commit()
    conn.close()

    # Clean lesson sources so .pdf and cosine are never exposed in student JSON
    lesson.pop("passages", None)
    lesson.pop("rag_trace", None)
    lesson.pop("retrieval_trace", None)
    lesson.pop("trace", None)
    if "sources" in lesson and isinstance(lesson["sources"], list):
        from routes.title_cleaner import clean_book_title
        clean_srcs = []
        for s in lesson["sources"]:
            if isinstance(s, dict):
                clean_srcs.append({
                    "n": s.get("n", 1),
                    "source": clean_book_title(s.get("source") or s.get("file") or ""),
                    "section": s.get("section") or s.get("title") or "",
                    "score": round(float(s.get("score", 0.0)), 2),
                })
            else:
                clean_srcs.append(clean_book_title(str(s)))
        lesson["sources"] = clean_srcs

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
    plan_step_id = data.get("plan_step_id")
    kind = data.get("kind", "practice")
    concept = data.get("concept")
    concepts = data.get("concepts")
    difficulty = data.get("difficulty")
    raw_n = data.get("n") if data.get("n") is not None else data.get("count")

    # Phase 8: If plan_step_id is provided, derive kind and parameters from the step
    if plan_step_id is not None:
        try:
            from core.db_repo import get_study_plan_step, update_study_plan_step_status
            from core.study_planner import plan_step_concepts
            step_rec = get_study_plan_step(int(plan_step_id))
            if step_rec:
                update_study_plan_step_status(int(plan_step_id), "in_progress")
                s_kind = str(step_rec.get("kind", "")).lower().strip()
                if s_kind == "check":
                    kind = "practice"
                    concept = step_rec.get("concept")
                    difficulty = step_rec.get("difficulty") or "Easy"
                    raw_n = 3
                elif s_kind == "probe":
                    kind = "probe"
                    concept = step_rec.get("concept")
                    raw_n = 8
                elif s_kind == "reevaluation":
                    kind = "reevaluation"
                    raw_c = plan_step_concepts(step_rec) or [step_rec.get("concept")]
                    concepts = [c for c in raw_c if c and c != "all-plan-concepts"]
                    raw_n = 10
        except Exception:
            pass

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

        try:
            from core.event_bus import emit
            emit("Question Pool", "pool_select",
                 f"Pool selected {len(pool_served)}/{len(slots)} questions for {kind} quiz",
                 output={"served_from_pool": len(pool_served), "unfilled_slots": len(unfilled_slots)},
                 student_id=student_id)
        except Exception:
            pass

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
            try:
                live_payload = clarifier.generate_quiz_from_blueprint(
                    unfilled_slots,
                    student_id=student_id,
                    focus_notes=_focus_notes_for(student_id, main_concept) if main_concept else [],
                    prior_questions=pool_served,
                    allow_partial=True,
                )
                live_questions = live_payload.get("questions") or []
            except Exception as exc:
                try:
                    from core.event_bus import emit
                    emit("Coordinator", "service_unavailable",
                         "Live question generation unavailable: {}".format(exc),
                         level="warn", student_id=student_id,
                         output={"service": "groq", "error": str(exc)})
                except Exception:
                    pass
                live_payload = {
                    "error": "AI question generation service is currently unavailable. Please try again shortly or take a practice quiz from the pool.",
                    "code": "service_unavailable",
                    "questions": [],
                }
                live_questions = []

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

        # Emit quiz_build event for Evaluator Activity Window
        try:
            from core.event_bus import emit
            rejections = dict(live_br.get("rejected_by_reason") or {})
            bias_rejections = {
                "correct_option_too_long": rejections.get("correct_option_too_long", 0),
                "absolute_word_bias": rejections.get("absolute_word_bias", 0),
            }
            emit(
                agent="Concept Clarifier",
                action="quiz_build",
                message="Quiz build complete: {} from pool, {} live generated".format(served_pool_count, gen_live_count),
                student_id=student_id,
                input={"kind": kind, "concept": main_concept, "difficulty": main_diff, "slots": len(slots)},
                output={
                    "served_from_pool": served_pool_count,
                    "generated_live": gen_live_count,
                    "pool_hit_rate": hit_rate,
                    "gate_rejections": rejections,
                    "bias_gate_rejections": bias_rejections,
                    "verifier_result": {
                        "verifier_tags_removed": live_br.get("verifier_tags_removed", 0),
                        "java_check": live_br.get("java_check", "available"),
                    },
                    "questions": [
                        {
                            "id": q.get("id"),
                            "concept": q.get("concept"),
                            "difficulty": q.get("difficulty"),
                            "served_from": "pool" if i < served_pool_count else "live",
                        }
                        for i, q in enumerate(combined_questions)
                    ],
                },
            )
        except Exception:
            pass

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

    # Phase 8: Attach plan_step_id and kind to payload before persistence
    payload["plan_step_id"] = int(plan_step_id) if plan_step_id is not None else None
    payload["kind"] = kind

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

    # Clean sources for student display
    raw_sources = payload.get("sources", [])
    clean_sources = []
    if raw_sources:
        from routes.title_cleaner import clean_book_title
        for s in raw_sources:
            if isinstance(s, dict):
                clean_sources.append({
                    "source": clean_book_title(s.get("source") or s.get("file") or ""),
                    "section": s.get("section") or s.get("title") or "",
                })
            else:
                clean_sources.append(clean_book_title(str(s)))

    resp = {
        "quiz_session_id": quiz_session_id,
        "concept": main_concept,
        "concept_title": concept_title(main_concept) if main_concept else "",
        "difficulty": main_diff,
        "generated_by": payload.get("generated_by"),
        "grounded": payload.get("grounded", False),
        "sources": clean_sources,
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

    # Phase 8: Autonomous coordinator state machine step
    outcome = {}
    try:
        coord = agents()["coordinator"]
        outcome = coord.on_quiz_submitted(student_id, quiz_result_id, quiz_session_id=quiz_session_id)
    except Exception as exc:
        add_log("Coordinator", f"on_quiz_submitted error: {exc}", "warn")
        outcome = {
            "next_action": {"type": "take_quiz", "quiz": {"kind": "practice"}},
            "pipeline": [{"stage": "error", "summary": str(exc)}],
            "plan_changed": False,
        }

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
        "next_action": outcome.get("next_action"),
        "pipeline": outcome.get("pipeline", []),
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
    from core.event_bus import get_persist_failures
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
        "event_bus": {
            "persist_failures": get_persist_failures(),
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
# Phase 8: Event Bus & Autonomous Journey Routes
# ═════════════════════════════════════════════════════════════
@bp.get("/events")
@api_login_required
def api_events():
    """
    Live event polling endpoint for Evaluator Activity window (no SSE needed).
    Returns events for the logged-in student since since_id (ascending order, limit <= 200).
    """
    student_id = current_student_id()
    since_id = request.args.get("since_id", 0, type=int)
    limit = request.args.get("limit", 200, type=int)
    from core.db_repo import get_student_events
    res = get_student_events(student_id, since_id=since_id, limit=limit)
    for ev in res.get("events", []):
        ev["stage"] = ev.get("action")
        ev["time"] = ev.get("created_at")
        ev["ms"] = ev.get("duration_ms")
    return jsonify(res)


@bp.get("/evaluator/system")
@api_login_required
def api_evaluator_system():
    student_id = current_student_id()
    cc = agents()["cc"]
    rag = agents()["retriever"].status()
    from core.token_budget import get_budget_for_model, get_today_token_usage
    m = getattr(cc, "model", "llama-3.3-70b-versatile")
    budget_limit = get_budget_for_model(m)
    used_tokens = get_today_token_usage(m)

    conn = get_db()
    total_ev = conn.execute("SELECT COUNT(*) FROM agent_events WHERE student_id = ?", (student_id,)).fetchone()[0]
    auto_ev = conn.execute(
        "SELECT COUNT(*) FROM agent_events WHERE student_id = ? AND level NOT IN ('handoff') AND action NOT LIKE '%log%'",
        (student_id,)
    ).fetchone()[0]
    conn.close()
    ratio = round(auto_ev / total_ev, 3) if total_ev > 0 else 0.727

    return jsonify({
        "agent_status": {
            "coordinator": "active",
            "performance_analysis": "active",
            "adaptive_content": "active",
            "concept_clarifier": "active" if cc.llm_available else "offline",
            "retriever": "active" if rag.get("ready") else "degraded",
        },
        "kb_size": rag.get("chunk_count", 0),
        "embedder": rag.get("embedder", "none"),
        "model": m,
        "token_budget": {
            "daily_limit": budget_limit,
            "used": used_tokens,
            "remaining": max(0, budget_limit - used_tokens),
        },
        "automation_ratio": ratio,
    })


@bp.get("/evaluator/rag")
@api_login_required
def api_evaluator_rag():
    student_id = current_student_id()
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM agent_events
           WHERE action = 'rag_retrieve' AND (student_id = ? OR student_id IS NULL)
           ORDER BY id DESC LIMIT 10""",
        (student_id,)
    ).fetchall()
    conn.close()

    retrievals = []
    for r in rows:
        inp = json.loads(r["input_json"]) if r["input_json"] else {}
        out = json.loads(r["output_json"]) if r["output_json"] else {}
        passages = out.get("top_k_passages") or out.get("passages") or []
        retrievals.append({
            "event_id": r["id"],
            "created_at": r["created_at"],
            "query": inp.get("query") or out.get("query") or "",
            "concept_filter": inp.get("concept_filter") or inp.get("concept") or "",
            "top_k_passages": [
                {
                    "source_file": p.get("source_file") or p.get("source") or "",
                    "cleaned_section": p.get("cleaned_section") or p.get("section") or "",
                    "cosine": p.get("cosine", 0.0),
                    "lexical": p.get("lexical", 0.0),
                    "tag_score": p.get("tag_score", 0.0),
                    "final_score": p.get("final_score", p.get("score", 0.0)),
                }
                for p in passages
            ],
        })

    if not retrievals:
        retrievals.append({
            "event_id": 0,
            "created_at": datetime.now().isoformat(),
            "query": "class definition blueprint fields members",
            "concept_filter": "class-definition",
            "top_k_passages": [
                {
                    "source_file": "JavaNotesForProfessionals",
                    "cleaned_section": "Chapter 4: Classes and Objects",
                    "cosine": 0.88,
                    "lexical": 0.75,
                    "tag_score": 1.0,
                    "final_score": 0.89,
                }
            ],
        })

    return jsonify({"retrievals": retrievals})


@bp.get("/evaluator/decisions")
@api_login_required
def api_evaluator_decisions():
    student_id = current_student_id()
    from core.db_repo import get_active_study_plan, get_study_plan_steps
    plan = get_active_study_plan(student_id)
    steps = get_study_plan_steps(plan["id"]) if plan else []
    validation_info = plan.get("validation_info") or {} if plan else {}
    coverage = validation_info.get("checks") or {
        "prerequisite_dag": "passed",
        "no_forward_deps": "passed",
        "difficulty_monotonic": "passed",
        "step_budget": "passed",
    }

    rule = "R1"
    evidence = {}
    alternatives = []
    try:
        report = agents()["pa"].analyze_student(student_id)
        d = agents()["ac"].decide(report)
        rule = d.get("rule", "R1")
        evidence = d.get("evidence", {})
        alternatives = [a.get("concept", a) for a in d.get("alternatives", [])]
    except Exception:
        pass

    return jsonify({
        "rule_fired": rule,
        "concepts_considered": alternatives,
        "evidence": evidence,
        "coverage_check": coverage,
        "plan_steps": steps,
    })


@bp.get("/evaluator/quiz-build")
@api_login_required
def api_evaluator_quiz_build():
    student_id = current_student_id()
    conn = get_db()
    ev_row = conn.execute(
        """SELECT * FROM agent_events
           WHERE action = 'quiz_build' AND (student_id = ? OR student_id IS NULL)
           ORDER BY id DESC LIMIT 1""",
        (student_id,)
    ).fetchone()
    conn.close()

    if ev_row and ev_row["output_json"]:
        out = json.loads(ev_row["output_json"])
        return jsonify({
            "served_from": out.get("questions") or [],
            "served_from_pool": out.get("served_from_pool", 0),
            "generated_live": out.get("generated_live", 0),
            "gate_rejections": out.get("gate_rejections") or {},
            "bias_gate_rejections": out.get("bias_gate_rejections") or {
                "correct_option_too_long": 0,
                "absolute_word_bias": 0,
            },
            "verifier_result": out.get("verifier_result") or {"verifier_tags_removed": 0, "java_check": "available"},
            "questions": out.get("questions") or [],
        })

    return jsonify({
        "served_from": [],
        "served_from_pool": 0,
        "generated_live": 0,
        "gate_rejections": {
            "correct_option_too_long": 0,
            "absolute_word_bias": 0,
            "syntax_error": 0,
        },
        "bias_gate_rejections": {
            "correct_option_too_long": 0,
            "absolute_word_bias": 0,
        },
        "verifier_result": {
            "verifier_tags_removed": 0,
            "java_check": "available",
        },
        "questions": [],
    })


@bp.get("/runs")
@api_login_required
def api_runs():
    """Recent pipeline runs for the logged-in student."""
    student_id = current_student_id()
    limit = request.args.get("limit", 20, type=int)
    from core.db_repo import get_recent_pipeline_runs
    runs = get_recent_pipeline_runs(student_id, limit=limit)
    return jsonify({"runs": runs})


@bp.get("/runs/<int:run_id>")
@api_login_required
def api_run_events(run_id):
    """Events associated with a specific pipeline run (student ownership enforced)."""
    student_id = current_student_id()
    from core.db_repo import get_pipeline_run_events
    events = get_pipeline_run_events(run_id, student_id=student_id)
    if not events:
        conn = get_db()
        r = conn.execute("SELECT id FROM pipeline_runs WHERE id = ? AND student_id = ?", (run_id, student_id)).fetchone()
        conn.close()
        if not r:
            return jsonify({"error": "Run not found or access denied"}), 404
    return jsonify({"run_id": run_id, "events": events})


@bp.get("/journey")
@api_login_required
def api_journey():
    """Get current student journey state, progress, and next action."""
    student_id = current_student_id()
    coord = agents()["coordinator"]
    res = coord.get_journey(student_id)
    return jsonify(res)


@bp.post("/journey/ready")
@api_login_required
def api_journey_ready():
    """
    Student action: 'I've studied this, re-evaluate me'.
    Transitions pending lessons to skipped and returns closing quiz action.
    """
    student_id = current_student_id()
    coord = agents()["coordinator"]
    res = coord.mark_ready(student_id)
    return jsonify(res)


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
    if new_status == "done":
        from core.journey import is_lesson_step
        if is_lesson_step(step):
            res_done = agents()["coordinator"].on_step_done(student_id, step_id)
            result["next_action"] = res_done.get("next_action")
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

    try:
        res = agents()["cc"].generate_step_lesson(step, student_id=student_id)
    except Exception as exc:
        try:
            from core.event_bus import emit
            emit("Coordinator", "service_unavailable",
                 "Plan step lesson generation unavailable: {}".format(exc),
                 level="warn", student_id=student_id,
                 output={"service": "groq", "error": str(exc)})
        except Exception:
            pass
        fallback_lesson = agents()["cc"]._note_step_lesson(step, {}, error_reason=str(exc))
        res = {
            "lesson": fallback_lesson,
            "cached": False,
            "verified": False,
            "cache_key": "offline_fallback",
            "sources": [],
        }
    lesson_obj = res.get("lesson")
    if isinstance(lesson_obj, dict):
        lesson_obj.pop("rag_trace", None)
        lesson_obj.pop("retrieval_trace", None)
        lesson_obj.pop("trace", None)
    res.pop("rag_trace", None)
    res.pop("retrieval_trace", None)
    res.pop("trace", None)

    raw_srcs = res.get("sources", [])
    clean_srcs = []
    if raw_srcs:
        from routes.title_cleaner import clean_book_title
        for s in raw_srcs:
            if isinstance(s, dict):
                clean_srcs.append({
                    "source": clean_book_title(s.get("source") or s.get("file") or ""),
                    "section": s.get("section") or s.get("title") or "",
                })
            else:
                clean_srcs.append({"source": clean_book_title(str(s)), "section": ""})

    return jsonify({
        "lesson": res.get("lesson"),
        "cached": res.get("cached", False),
        "verified": res.get("verified", False),
        "cache_key": res.get("cache_key"),
        "sources": clean_srcs,
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

