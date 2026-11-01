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


def record_generated_questions(concept, difficulty, questions, model=None, source="llm_rag", origin="generated", pool_status="active"):
    """
    Upsert questions into the questions table (deduping by text_hash).
    Attaches 'question_id' to each question dictionary in-place.
    Stores verified status, origin ('generated'|'diagnostic'|'bank'), pool_status,
    difficulty_verified, and verifier labels for verified question pool serving.
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
            q_concept = q.get("concept") or concept
            q_diff = q.get("difficulty") or difficulty
            qtype = q.get("qtype") or classify_question_type(q_text)
            options_raw = q.get("options", [])
            options_clean = [opt["text"] if isinstance(opt, dict) else str(opt) for opt in options_raw]
            options_json = json.dumps(options_clean)
            correct_idx = int(q.get("correct") if q.get("correct") is not None else q.get("correct_index", 0))
            explanation = q.get("explanation", "")
            facet = q.get("facet")
            verified = 1 if q.get("verified") else 0
            verifier_model = q.get("verifier_model")
            q_origin = q.get("origin") or origin or "generated"
            q_pool_status = q.get("pool_status") or pool_status or "active"
            diff_ver = q.get("difficulty_verified")
            v_labels = q.get("verifier_labels")
            v_labels_json = json.dumps(v_labels) if v_labels is not None else None

            tags_data = {
                "tags": q.get("concept_tags", [q_concept]),
                "option_misconception_ids": q.get("option_misconception_ids", []),
                "facet": facet,
                "qtype": qtype,
                "reference_ids": q.get("reference_ids", []),
                "verified": verified,
                "verifier_model": verifier_model,
                "reject_reason": q.get("reject_reason"),
            }
            tags_json = json.dumps(tags_data)

            raw_emb = q.get("embedding")
            emb_blob = None
            if raw_emb:
                from core.quiz_engine import serialize_embedding
                emb_blob = serialize_embedding(raw_emb)

            row = cur.execute("SELECT id FROM questions WHERE text_hash = ?", (thash,)).fetchone()
            if row:
                qid = row["id"]
                cur.execute(
                    """UPDATE questions
                       SET verified = ?,
                           tags_json = ?,
                           embedding = COALESCE(embedding, ?),
                           origin = COALESCE(?, origin),
                           pool_status = COALESCE(?, pool_status),
                           difficulty_verified = COALESCE(?, difficulty_verified),
                           verifier_labels_json = COALESCE(?, verifier_labels_json)
                       WHERE id = ?""",
                    (verified, tags_json, emb_blob, q_origin, q_pool_status, diff_ver, v_labels_json, qid),
                )
            else:
                cur.execute(
                    """INSERT INTO questions
                       (concept, facet, difficulty, qtype, question_text, options_json,
                        correct_index, explanation, tags_json, source, model,
                        verified, text_hash, embedding, origin, pool_status,
                        difficulty_verified, verifier_labels_json, times_served, times_correct)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)""",
                    (q_concept, facet, q_diff, qtype, q_text, options_json,
                     correct_idx, explanation, tags_json, source, model, verified, thash, emb_blob,
                     q_origin, q_pool_status, diff_ver, v_labels_json),
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


def record_llm_call(student_id, agent, purpose, model, latency_ms, ok, error=None, prompt_tokens=None, completion_tokens=None, total_tokens=None):
    """
    Log external model execution telemetry to llm_calls table.
    Populates prompt, completion, and total tokens.
    """
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        try:
            total_tokens = int(prompt_tokens) + int(completion_tokens)
        except (ValueError, TypeError):
            total_tokens = None

    try:
        conn = get_db()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(llm_calls)").fetchall()}
        if "total_tokens" in cols:
            conn.execute(
                """INSERT INTO llm_calls
                   (student_id, agent, purpose, model, latency_ms, prompt_tokens,
                    completion_tokens, total_tokens, ok, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (student_id, agent, purpose, model, int(latency_ms or 0),
                 prompt_tokens, completion_tokens, total_tokens, 1 if ok else 0, error),
            )
        else:
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


def load_diagnostic_pool(diag_dir=None):
    """
    One-time idempotent loader that reads all question records from
    rag/corpus/diagnostic/*.json and stores them into the questions table
    with verified=1, origin='diagnostic', pool_status='active'.
    Returns number of questions loaded.
    """
    from pathlib import Path
    if diag_dir is None:
        diag_dir = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "diagnostic"
    else:
        diag_dir = Path(diag_dir)

    if not diag_dir.exists():
        return 0

    total_loaded = 0
    set_files = sorted(list(diag_dir.glob("set_*.json")))
    for sf in set_files:
        try:
            with open(sf, "r", encoding="utf-8") as f:
                data = json.load(f)
            qs = data.get("questions") or []
            if qs:
                saved = record_generated_questions(
                    "diagnostic",
                    "diagnostic",
                    qs,
                    model=data.get("model"),
                    source=data.get("generated_by", "diagnostic_prebuilt"),
                    origin="diagnostic",
                    pool_status="active",
                )
                total_loaded += len(saved)
        except Exception as exc:
            add_log("Database", f"load_diagnostic_pool error on {sf.name}: {exc}", "warning")

    return total_loaded


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


def quarantine_positional_explanation_questions(conn=None):
    """
    Step 0 (Phase 4D): Scan all questions in the database and quarantine any
    whose explanation violates the positional-wording rule (_OPTION_LABEL_RE).
    Sets pool_status='quarantined' so they are excluded from quiz pool selection.
    Returns the count of questions set to quarantined.
    """
    from core.quiz_engine import _OPTION_LABEL_RE

    should_close = False
    if conn is None:
        try:
            conn = get_db()
            should_close = True
        except Exception as exc:
            add_log("Database", f"quarantine_positional_explanation_questions conn error: {exc}", "warning")
            return 0

    count = 0
    try:
        rows = conn.execute("SELECT id, explanation, pool_status FROM questions").fetchall()
        to_quarantine = []
        for r in rows:
            exp = str(r["explanation"] or "")
            if _OPTION_LABEL_RE.search(exp):
                to_quarantine.append(r["id"])

        if to_quarantine:
            cur = conn.cursor()
            for qid in to_quarantine:
                cur.execute("UPDATE questions SET pool_status = 'quarantined' WHERE id = ?", (qid,))
            conn.commit()
            count = len(to_quarantine)
            add_log("Database", f"Quarantined {count} question(s) with positional explanation wording: {to_quarantine}", "info")
    except Exception as exc:
        add_log("Database", f"quarantine_positional_explanation_questions failed: {exc}", "warning")
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass
    return count


def list_quarantined(conn=None):
    """
    Return a list of question dicts currently marked with pool_status='quarantined'.
    """
    should_close = False
    if conn is None:
        try:
            conn = get_db()
            should_close = True
        except Exception as exc:
            add_log("Database", f"list_quarantined conn error: {exc}", "warning")
            return []

    results = []
    try:
        rows = conn.execute(
            """SELECT id, concept, difficulty, qtype, question_text, explanation, origin, pool_status, verified
               FROM questions
               WHERE pool_status = 'quarantined'
               ORDER BY id"""
        ).fetchall()
        for r in rows:
            results.append(dict(r))
    except Exception as exc:
        add_log("Database", f"list_quarantined query failed: {exc}", "warning")
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass
    return results
