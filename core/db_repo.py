"""
=============================================================================
EduGen - Database Repository Helpers
=============================================================================
Resilient data-access helpers for Phase 1 tables.
Every function is wrapped in try/except so a database anomaly can NEVER break
student learning sessions, quizzes, or agent pipelines.
=============================================================================
"""

import hashlib
import json
from datetime import datetime

from core.agent_log import add_log
from core.db import get_db


def compute_question_hash(question_text):
    """Normalized SHA-256 hash to deduplicate questions across generations."""
    norm = " ".join(str(question_text or "").strip().lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def classify_question_type(question_text):
    """Categorize question style: concept, code_output, or bug_find."""
    txt = str(question_text or "").lower()
    if "output" in txt or "print" in txt or "evaluate" in txt:
        return "code_output"
    if "bug" in txt or "error" in txt or "fix" in txt or "compile" in txt or "exception" in txt:
        return "bug_find"
    return "concept"


def record_generated_questions(concept, difficulty, questions, model=None, source="llm_rag"):
    """
    Upsert questions into the questions table (deduping by text_hash).
    Attaches 'question_id' to each question dictionary in-place.
    """
    if not questions:
        return []

    saved_ids = []
    try:
        conn = get_db()
        cur = conn.cursor()
        for q in questions:
            q_text = str(q.get("question", "")).strip()
            if not q_text:
                continue

            thash = compute_question_hash(q_text)
            qtype = q.get("qtype") or classify_question_type(q_text)
            options_raw = q.get("options", [])
            options_clean = [opt["text"] if isinstance(opt, dict) else str(opt) for opt in options_raw]
            options_json = json.dumps(options_clean)
            correct_idx = int(q.get("correct", 0))
            explanation = q.get("explanation", "")
            facet = q.get("facet")

            tags_data = {
                "tags": q.get("concept_tags", [concept]),
                "option_misconception_ids": q.get("option_misconception_ids", []),
                "facet": facet,
                "qtype": qtype,
                "reference_ids": q.get("reference_ids", []),
            }
            tags_json = json.dumps(tags_data)

            row = cur.execute("SELECT id FROM questions WHERE text_hash = ?", (thash,)).fetchone()
            if row:
                qid = row["id"]
            else:
                cur.execute(
                    """INSERT INTO questions
                       (concept, facet, difficulty, qtype, question_text, options_json,
                        correct_index, explanation, tags_json, source, model,
                        verified, text_hash, times_served, times_correct)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, 0)""",
                    (concept, facet, difficulty, qtype, q_text, options_json,
                     correct_idx, explanation, tags_json, source, model, thash),
                )
                qid = cur.lastrowid

            q["question_id"] = qid
            saved_ids.append(qid)

        conn.commit()
        conn.close()
    except Exception as exc:
        add_log("Database", f"record_generated_questions failed: {exc}", "warning")

    return saved_ids


def record_submission_history(student_id, quiz_result_id, questions, answers, timings):
    """
    Insert student_question_history rows and update questions.times_served / times_correct.
    """
    try:
        conn = get_db()
        cur = conn.cursor()

        for i, q in enumerate(questions):
            q_text = str(q.get("question", "")).strip()
            thash = compute_question_hash(q_text)

            qid = q.get("question_id")
            if not qid:
                row = cur.execute("SELECT id FROM questions WHERE text_hash = ?", (thash,)).fetchone()
                qid = row["id"] if row else None

            chosen = answers.get(str(i), answers.get(i, -1))
            try:
                chosen = int(chosen)
            except (TypeError, ValueError):
                chosen = -1

            correct_idx = q.get("correct")
            was_correct = 1 if (chosen == correct_idx and chosen != -1) else 0
            time_ms = int(timings.get(str(i), timings.get(i, 0)) or 0)

            misconception_id = None
            if not was_correct and chosen != -1:
                opt_mids = q.get("option_misconception_ids")
                if opt_mids and 0 <= chosen < len(opt_mids):
                    misconception_id = opt_mids[chosen]
                else:
                    options = q.get("options") or []
                    if isinstance(options, list) and 0 <= chosen < len(options):
                        opt_item = options[chosen]
                        if isinstance(opt_item, dict):
                            misconception_id = opt_item.get("misconception_id")

            if qid:
                cur.execute(
                    """INSERT INTO student_question_history
                       (student_id, question_id, quiz_result_id, was_correct, chosen_index, time_taken_ms, misconception_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (student_id, qid, quiz_result_id, was_correct, chosen, time_ms, misconception_id),
                )
                cur.execute(
                    """UPDATE questions
                       SET times_served = times_served + 1,
                           times_correct = times_correct + ?
                       WHERE id = ?""",
                    (was_correct, qid),
                )

        conn.commit()
        conn.close()
    except Exception as exc:
        add_log("Database", f"record_submission_history failed: {exc}", "warning")


def record_concept_mastery(student_id, concept_stats, quiz_result_id=None):
    """
    Upsert concept_mastery records and append snapshot rows into mastery_history.
    """
    if not student_id or not concept_stats:
        return

    try:
        conn = get_db()
        cur = conn.cursor()
        now_iso = datetime.now().isoformat()

        for concept, stat in concept_stats.items():
            mastery = float(stat.get("mastery", 0.0) or 0.0)
            attempts = int(stat.get("attempts", 0) or 0)
            correct = int(stat.get("correct", 0) or 0)
            trend = str(stat.get("trend", "stable") or "stable")
            last_seen = stat.get("last_seen")

            # Upsert concept_mastery
            cur.execute(
                """INSERT INTO concept_mastery
                   (student_id, concept, mastery, attempts, correct, trend, last_seen, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(student_id, concept) DO UPDATE SET
                     mastery = excluded.mastery,
                     attempts = excluded.attempts,
                     correct = excluded.correct,
                     trend = excluded.trend,
                     last_seen = excluded.last_seen,
                     updated_at = excluded.updated_at""",
                (student_id, concept, mastery, attempts, correct, trend, last_seen, now_iso),
            )

            # Record timeline entry in mastery_history
            cur.execute(
                """INSERT INTO mastery_history
                   (student_id, concept, mastery, quiz_result_id, recorded_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (student_id, concept, mastery, quiz_result_id, now_iso),
            )

        conn.commit()
        conn.close()
    except Exception as exc:
        add_log("Database", f"record_concept_mastery failed: {exc}", "warning")


def record_llm_call(student_id, agent, purpose, model, latency_ms, ok, error=None, prompt_tokens=None, completion_tokens=None):
    """
    Log external model execution telemetry to llm_calls table.
    """
    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO llm_calls
               (student_id, agent, purpose, model, latency_ms, prompt_tokens,
                completion_tokens, ok, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (student_id, agent, purpose, model, int(latency_ms or 0),
             prompt_tokens, completion_tokens, 1 if ok else 0, error),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        add_log("Database", f"record_llm_call failed: {exc}", "warning")


def record_user_login(user_id):
    """Update last_login_at timestamp for the user."""
    if not user_id:
        return
    try:
        conn = get_db()
        conn.execute(
            "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id,),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        add_log("Database", f"record_user_login failed: {exc}", "warning")


def record_rag_retrieval(run_id, student_id, concept, mode, query, embedder, results):
    """
    Audit retrieval operations. Stores chunk IDs and scores only, NEVER chunk text.
    results: list of passages/citations with {chunk_id, source, cosine, lexical, tag_score, final}
    """
    try:
        clean_results = []
        for r in results or []:
            clean_results.append({
                "chunk_id": r.get("chunk_id", r.get("id")),
                "source": r.get("source"),
                "cosine": round(float(r.get("cosine", 0.0)), 4) if r.get("cosine") is not None else None,
                "lexical": round(float(r.get("lexical", 0.0)), 4) if r.get("lexical") is not None else None,
                "tag_score": round(float(r.get("tag_score", 0.0)), 4) if r.get("tag_score") is not None else None,
                "final": round(float(r.get("score", r.get("final", 0.0))), 4) if (r.get("score") is not None or r.get("final") is not None) else None,
            })

        conn = get_db()
        conn.execute(
            """INSERT INTO rag_retrievals
               (run_id, student_id, concept, mode, query, embedder, results_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, student_id, concept, mode, str(query or ""), str(embedder or ""),
             json.dumps(clean_results)),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        add_log("Database", f"record_rag_retrieval failed: {exc}", "warning")
