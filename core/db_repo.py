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
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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

            # Phase 9B: Ensure live questions are admitted to active pool only if passing live bias gates
            if q_pool_status == "active" and (q_origin in ("live", "generated") or source == "llm_rag"):
                len_corr = len(str(options_clean[correct_idx]).strip()) if 0 <= correct_idx < len(options_clean) else 0
                wrong_lens = [len(str(options_clean[i]).strip()) for i in range(len(options_clean)) if i != correct_idx]
                max_w = max(wrong_lens) if wrong_lens else 0
                abs_pat = re.compile(r"\b(always|never|only|automatically|all|every|any)\b", re.IGNORECASE)
                wrong_abs = sum(1 for i in range(len(options_clean)) if i != correct_idx and abs_pat.search(str(options_clean[i])))
                corr_abs = bool(abs_pat.search(str(options_clean[correct_idx]))) if 0 <= correct_idx < len(options_clean) else False
                if (max_w > 0 and len_corr > 1.10 * max_w) or (wrong_abs >= 2 and not corr_abs):
                    q_pool_status = "quarantined"
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


def upsert_student_misconceptions(student_id, misconceptions):
    """
    Idempotently upsert tracked student misconceptions into student_misconceptions table.
    Accepts list of misconception dictionaries.
    """
    if not student_id or not misconceptions:
        return

    try:
        conn = get_db()
        cur = conn.cursor()
        now_iso = datetime.now().isoformat()

        for m in misconceptions:
            mid = m.get("misconception_id")
            if not mid:
                continue
            concept = m.get("concept") or ""
            facet = m.get("facet")
            chosen = int(m.get("chosen", 0) or 0)
            offered = int(m.get("offered", 0) or 0)
            avoided = int(m.get("avoided_streak", 0) or 0)
            status = str(m.get("status", "suspected") or "suspected")
            first_seen = m.get("first_seen")
            last_seen = m.get("last_seen")

            cur.execute(
                """INSERT INTO student_misconceptions
                   (student_id, misconception_id, concept, facet, chosen, offered,
                    avoided_streak, status, first_seen, last_seen, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(student_id, misconception_id) DO UPDATE SET
                     concept = excluded.concept,
                     facet = excluded.facet,
                     chosen = excluded.chosen,
                     offered = excluded.offered,
                     avoided_streak = excluded.avoided_streak,
                     status = excluded.status,
                     first_seen = COALESCE(student_misconceptions.first_seen, excluded.first_seen),
                     last_seen = excluded.last_seen,
                     updated_at = excluded.updated_at""",
                (student_id, mid, concept, facet, chosen, offered, avoided, status, first_seen, last_seen, now_iso),
            )

        conn.commit()
        conn.close()
    except Exception as exc:
        add_log("Database", f"upsert_student_misconceptions failed: {exc}", "warning")


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


# ─────────────────────────────────────────────────────────────────────────────
# STUDY PLAN PERSISTENCE (PHASE 6)
# ─────────────────────────────────────────────────────────────────────────────

def create_study_plan(student_id: int, plan_dict: Dict[str, Any], conn=None) -> Dict[str, Any]:
    """
    Persist a newly generated study plan.
    - Sets any existing 'active' plan for this student to 'superseded'.
    - Inserts the new plan and all its steps inside an explicit transaction.
    - Returns the saved plan dictionary with step IDs.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cur = conn.cursor()
        # Supersede previous active plan
        cur.execute(
            "UPDATE study_plans SET status = 'superseded' WHERE student_id = ? AND status = 'active'",
            (student_id,),
        )

        summary = plan_dict.get("summary", "")
        analysis_json = json.dumps(plan_dict.get("analysis", {}))
        coverage_json = json.dumps(plan_dict.get("coverage", {}))
        deferred_json = json.dumps(plan_dict.get("deferred", []))

        cur.execute(
            """INSERT INTO study_plans (student_id, status, summary, analysis_json, coverage_json, deferred_json)
               VALUES (?, 'active', ?, ?, ?, ?)""",
            (student_id, summary, analysis_json, coverage_json, deferred_json),
        )
        plan_id = cur.lastrowid

        saved_steps = []
        for pos, s in enumerate(plan_dict.get("steps", []), start=1):
            concept = s.get("concept", "")
            difficulty = s.get("difficulty", "Easy")
            kind = s.get("kind", "weak")
            status = s.get("status", "pending")
            reason = s.get("reason", "")
            prompt_text = s.get("prompt_text")
            user_note = s.get("user_note")
            step_cov = json.dumps(s.get("coverage_json", {})) if s.get("coverage_json") else None
            lesson_style = s.get("lesson_style")
            focus_json = json.dumps(s.get("focus", {}))
            priority = float(s.get("priority", 0.0))
            est_minutes = int(s.get("est_minutes", 10))

            cur.execute(
                """INSERT INTO study_plan_steps (
                    plan_id, position, concept, difficulty, kind, status, reason,
                    prompt_text, user_note, coverage_json, lesson_style, focus_json,
                    priority, est_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan_id, pos, concept, difficulty, kind, status, reason,
                    prompt_text, user_note, step_cov, lesson_style, focus_json,
                    priority, est_minutes,
                ),
            )
            step_id = cur.lastrowid
            saved_step = dict(s)
            saved_step["id"] = step_id
            saved_step["plan_id"] = plan_id
            saved_step["position"] = pos
            saved_steps.append(saved_step)

        conn.commit()

        out_plan = dict(plan_dict)
        out_plan["id"] = plan_id
        out_plan["student_id"] = student_id
        out_plan["status"] = "active"
        out_plan["steps"] = saved_steps
        return out_plan
    except Exception as exc:
        conn.rollback()
        add_log("Database", f"create_study_plan failed: {exc}", "error")
        raise
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def get_active_study_plan(student_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """
    Retrieve the active study plan for student_id, including all steps ordered by position.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        row = conn.execute(
            """SELECT * FROM study_plans
               WHERE student_id = ? AND status = 'active'
               ORDER BY id DESC LIMIT 1""",
            (student_id,),
        ).fetchone()

        if not row:
            return None

        plan_data = dict(row)
        plan_id = plan_data["id"]

        # Parse JSON fields
        for j_col in ("coverage_json", "deferred_json", "analysis_json"):
            if plan_data.get(j_col):
                try:
                    plan_data[j_col.replace("_json", "")] = json.loads(plan_data[j_col])
                except Exception:
                    plan_data[j_col.replace("_json", "")] = {}
            else:
                plan_data[j_col.replace("_json", "")] = {} if j_col != "deferred_json" else []

        step_rows = conn.execute(
            """SELECT * FROM study_plan_steps
               WHERE plan_id = ?
               ORDER BY position ASC""",
            (plan_id,),
        ).fetchall()

        steps = []
        for r in step_rows:
            sd = dict(r)
            if sd.get("focus_json"):
                try:
                    sd["focus"] = json.loads(sd["focus_json"])
                except Exception:
                    sd["focus"] = {}
            else:
                sd["focus"] = {}
            steps.append(sd)

        plan_data["steps"] = steps
        return plan_data
    except Exception as exc:
        add_log("Database", f"get_active_study_plan failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def get_study_plan_by_id(plan_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieve any study plan by its ID."""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        row = conn.execute(
            "SELECT * FROM study_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()

        if not row:
            return None

        plan_data = dict(row)
        for j_col in ("coverage_json", "deferred_json", "analysis_json"):
            if plan_data.get(j_col):
                try:
                    plan_data[j_col.replace("_json", "")] = json.loads(plan_data[j_col])
                except Exception:
                    plan_data[j_col.replace("_json", "")] = {}
            else:
                plan_data[j_col.replace("_json", "")] = {} if j_col != "deferred_json" else []

        step_rows = conn.execute(
            "SELECT * FROM study_plan_steps WHERE plan_id = ? ORDER BY position ASC",
            (plan_id,),
        ).fetchall()

        steps = []
        for r in step_rows:
            sd = dict(r)
            if sd.get("focus_json"):
                try:
                    sd["focus"] = json.loads(sd["focus_json"])
                except Exception:
                    sd["focus"] = {}
            else:
                sd["focus"] = {}
            steps.append(sd)

        plan_data["steps"] = steps
        return plan_data
    except Exception as exc:
        add_log("Database", f"get_study_plan_by_id failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def get_study_plan_step(step_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieve a single study plan step by ID."""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        row = conn.execute(
            "SELECT * FROM study_plan_steps WHERE id = ?",
            (step_id,),
        ).fetchone()

        if not row:
            return None

        sd = dict(row)
        if sd.get("focus_json"):
            try:
                sd["focus"] = json.loads(sd["focus_json"])
            except Exception:
                sd["focus"] = {}
        else:
            sd["focus"] = {}
        return sd
    except Exception as exc:
        add_log("Database", f"get_study_plan_step failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def get_study_plan_steps(plan_id: int, conn=None) -> List[Dict[str, Any]]:
    """Fetch all steps for a study plan ordered by position."""
    plan = get_study_plan_by_id(plan_id, conn=conn)
    return plan.get("steps", []) if plan else []


def update_study_plan_step_status(step_id: int, status: str, conn=None) -> Optional[Dict[str, Any]]:
    """Alias for update_study_plan_step(step_id, status=status)."""
    return update_study_plan_step(step_id=step_id, status=status, conn=conn)


def update_study_plan_step(
    step_id: int,
    status: Optional[str] = None,
    user_note: Optional[str] = None,
    prompt_text: Optional[str] = None,
    conn=None,
) -> Optional[Dict[str, Any]]:
    """
    Update step lifecycle status, user note, or prompt text.
    Maintains started_at and completed_at timestamps.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cur = conn.cursor()
        updates = []
        params = []

        if status:
            updates.append("status = ?")
            params.append(status)
            if status == "in_progress":
                updates.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
            elif status in ("done", "skipped"):
                updates.append("completed_at = CURRENT_TIMESTAMP")

        if user_note is not None:
            updates.append("user_note = ?")
            params.append(user_note)

        if prompt_text is not None:
            updates.append("prompt_text = ?")
            params.append(prompt_text)

        if not updates:
            return get_study_plan_step(step_id, conn=conn)

        params.append(step_id)
        sql = f"UPDATE study_plan_steps SET {', '.join(updates)} WHERE id = ?"
        cur.execute(sql, params)
        conn.commit()

        return get_study_plan_step(step_id, conn=conn)
    except Exception as exc:
        conn.rollback()
        add_log("Database", f"update_study_plan_step failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def update_study_plan_coverage(plan_id: int, coverage_dict: Dict[str, Any], conn=None):
    """Update the coverage_json field of a study plan."""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cov_str = json.dumps(coverage_dict)
        conn.execute(
            "UPDATE study_plans SET coverage_json = ? WHERE id = ?",
            (cov_str, plan_id),
        )
        conn.commit()
    except Exception as exc:
        add_log("Database", f"update_study_plan_coverage failed: {exc}", "error")
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════
# Lesson Cache & Feedback (Phase 7)
# ═════════════════════════════════════════════════════════════

def get_cached_lesson(cache_key: str, conn=None) -> Optional[Dict[str, Any]]:
    """
    Retrieve cached lesson by cache_key.
    Increments served_count and updates last_served_at timestamp.
    """
    if not cache_key:
        return None

    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM lesson_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

        if not row:
            return None

        # Update served_count and last_served_at
        cur.execute(
            """UPDATE lesson_cache
               SET served_count = served_count + 1,
                   last_served_at = CURRENT_TIMESTAMP
               WHERE cache_key = ?""",
            (cache_key,),
        )
        conn.commit()

        data = dict(row)
        # Reflect updated served_count in returned dict
        data["served_count"] = (data.get("served_count") or 0) + 1
        data["last_served_at"] = datetime.now().isoformat()
        try:
            data["lesson"] = json.loads(data["lesson_json"])
        except Exception:
            data["lesson"] = {}
        return data
    except Exception as exc:
        add_log("Database", f"get_cached_lesson failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def save_cached_lesson(
    cache_key: str,
    concept: str,
    difficulty: str,
    style: str,
    lesson_data: Dict[str, Any],
    model: str,
    index_signature: str,
    student_id: Optional[int] = None,
    plan_step_id: Optional[int] = None,
    tokens: int = 0,
    verified: int = 0,
    conn=None,
) -> Optional[int]:
    """
    Insert or update a generated lesson in the lesson_cache table.
    """
    if not cache_key or not lesson_data:
        return None

    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cur = conn.cursor()
        l_json = json.dumps(lesson_data)
        cur.execute(
            """INSERT INTO lesson_cache (
                   cache_key, student_id, concept, difficulty, style,
                   plan_step_id, lesson_json, model, index_signature,
                   tokens, verified, created_at, last_served_at, served_count
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
               ON CONFLICT(cache_key) DO UPDATE SET
                   lesson_json = excluded.lesson_json,
                   model = excluded.model,
                   index_signature = excluded.index_signature,
                   tokens = excluded.tokens,
                   verified = excluded.verified,
                   last_served_at = CURRENT_TIMESTAMP,
                   served_count = lesson_cache.served_count + 1""",
            (
                cache_key,
                student_id,
                concept,
                difficulty,
                style,
                plan_step_id,
                l_json,
                model,
                index_signature,
                tokens,
                verified,
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as exc:
        conn.rollback()
        add_log("Database", f"save_cached_lesson failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def cleanup_old_lesson_cache(days: int = 30, conn=None) -> int:
    """
    Delete lesson cache entries older than `days` days.
    Returns the count of deleted entries.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM lesson_cache WHERE last_served_at < datetime('now', '-' || ? || ' days')",
            (int(days),),
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception as exc:
        conn.rollback()
        add_log("Database", f"cleanup_old_lesson_cache failed: {exc}", "error")
        return 0
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def count_step_regenerations_today(step_id: int, conn=None) -> int:
    """
    Count how many times a step's lesson has been regenerated today (within the last 24h).
    Enforces the maximum 3 regenerations per step per day limit.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cur = conn.cursor()
        purpose = f"step_regen_{step_id}"
        row = cur.execute(
            """SELECT COUNT(*) as cnt FROM llm_calls
               WHERE purpose = ?
                 AND (created_at >= date('now', 'start of day')
                      OR datetime(created_at) >= datetime('now', '-24 hours'))""",
            (purpose,),
        ).fetchone()
        return row["cnt"] if row else 0
    except Exception as exc:
        add_log("Database", f"count_step_regenerations_today failed: {exc}", "error")
        return 0
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def record_feedback(
    student_id: int,
    target_type: str,
    target_ref: str,
    rating: int,
    comment: Optional[str] = None,
    conn=None,
) -> Optional[int]:
    """
    Record student feedback (rating: 1 or -1, comment <= 300) in the feedback table.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True

    try:
        cur = conn.cursor()
        clean_comment = str(comment or "")[:300] if comment else None
        cur.execute(
            """INSERT INTO feedback (student_id, target_type, target_ref, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (student_id, str(target_type), str(target_ref), int(rating), clean_comment),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as exc:
        conn.rollback()
        add_log("Database", f"record_feedback failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Phase 8: Coordinator Journey, Pipeline Runs, and Agent Events Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_student_journey(student_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch student journey state machine row from student_journey table."""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM student_journey WHERE student_id = ?", (student_id,)).fetchone()
        if not row:
            return None
        return {
            "student_id": row["student_id"],
            "state": row["state"],
            "plan_id": row["plan_id"],
            "current_step_id": row["current_step_id"],
            "last_run_id": row["last_run_id"],
            "last_result_id": row["last_result_id"],
            "context": json.loads(row["context_json"]) if row["context_json"] else {},
            "updated_at": row["updated_at"],
        }
    except Exception as exc:
        add_log("Database", f"get_student_journey failed: {exc}", "error")
        return None
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def save_student_journey(
    student_id: int,
    state: str,
    plan_id: Optional[int] = None,
    current_step_id: Optional[int] = None,
    last_run_id: Optional[int] = None,
    last_result_id: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
    conn=None,
) -> bool:
    """Upsert student journey state."""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True
    try:
        cur = conn.cursor()
        c_json = json.dumps(context) if context is not None else None
        cur.execute(
            """INSERT INTO student_journey (
                student_id, state, plan_id, current_step_id, last_run_id, last_result_id, context_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id) DO UPDATE SET
                state = excluded.state,
                plan_id = COALESCE(excluded.plan_id, student_journey.plan_id),
                current_step_id = COALESCE(excluded.current_step_id, student_journey.current_step_id),
                last_run_id = COALESCE(excluded.last_run_id, student_journey.last_run_id),
                last_result_id = COALESCE(excluded.last_result_id, student_journey.last_result_id),
                context_json = COALESCE(excluded.context_json, student_journey.context_json),
                updated_at = CURRENT_TIMESTAMP""",
            (student_id, state, plan_id, current_step_id, last_run_id, last_result_id, c_json),
        )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        add_log("Database", f"save_student_journey failed: {exc}", "error")
        return False
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def get_recent_pipeline_runs(student_id: int, limit: int = 20, conn=None) -> List[Dict[str, Any]]:
    """Fetch recent pipeline runs with associated event counts."""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """SELECT r.id, r.student_id, r.trigger, r.status, r.started_at, r.finished_at, r.duration_ms,
                      COUNT(e.id) as event_count
               FROM pipeline_runs r
               LEFT JOIN agent_events e ON e.run_id = r.id
               WHERE r.student_id = ?
               GROUP BY r.id
               ORDER BY r.id DESC
               LIMIT ?""",
            (student_id, limit),
        ).fetchall()
        runs = []
        for row in rows:
            runs.append({
                "id": row["id"],
                "student_id": row["student_id"],
                "trigger": row["trigger"],
                "status": row["status"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "duration_ms": row["duration_ms"] or 0,
                "event_count": row["event_count"] or 0,
            })
        return runs
    except Exception as exc:
        add_log("Database", f"get_recent_pipeline_runs failed: {exc}", "error")
        return []
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def get_pipeline_run_events(run_id: int, student_id: Optional[int] = None, conn=None) -> List[Dict[str, Any]]:
    """Fetch all agent events associated with a pipeline run."""
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True
    try:
        cur = conn.cursor()
        if student_id is not None:
            rows = cur.execute(
                """SELECT * FROM agent_events WHERE run_id = ? AND student_id = ? ORDER BY id ASC""",
                (run_id, student_id),
            ).fetchall()
        else:
            rows = cur.execute(
                """SELECT * FROM agent_events WHERE run_id = ? ORDER BY id ASC""",
                (run_id,),
            ).fetchall()
        events = []
        for r in rows:
            events.append({
                "id": r["id"],
                "run_id": r["run_id"],
                "student_id": r["student_id"],
                "agent": r["agent"],
                "action": r["action"],
                "level": r["level"],
                "message": r["message"],
                "input": json.loads(r["input_json"]) if r["input_json"] else None,
                "output": json.loads(r["output_json"]) if r["output_json"] else None,
                "duration_ms": r["duration_ms"],
                "created_at": r["created_at"],
            })
        return events
    except Exception as exc:
        add_log("Database", f"get_pipeline_run_events failed: {exc}", "error")
        return []
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def get_student_events(student_id: int, since_id: int = 0, limit: int = 200, conn=None) -> Dict[str, Any]:
    """
    Fetch paginated agent events for live Activity window polling.
    Limits to <= 200 items in ascending order.
    """
    should_close = False
    if conn is None:
        conn = get_db()
        should_close = True
    try:
        cur = conn.cursor()
        capped_limit = min(max(1, int(limit)), 200)
        rows = cur.execute(
            """SELECT * FROM agent_events
               WHERE student_id = ? AND id > ?
               ORDER BY id ASC
               LIMIT ?""",
            (student_id, int(since_id), capped_limit),
        ).fetchall()
        events = []
        max_id = int(since_id)
        for r in rows:
            eid = r["id"]
            if eid > max_id:
                max_id = eid
            events.append({
                "id": eid,
                "run_id": r["run_id"],
                "student_id": r["student_id"],
                "agent": r["agent"],
                "action": r["action"],
                "level": r["level"],
                "message": r["message"],
                "input": json.loads(r["input_json"]) if r["input_json"] else None,
                "output": json.loads(r["output_json"]) if r["output_json"] else None,
                "duration_ms": r["duration_ms"],
                "created_at": r["created_at"],
            })
        return {"events": events, "last_id": max_id}
    except Exception as exc:
        add_log("Database", f"get_student_events failed: {exc}", "error")
        return {"events": [], "last_id": int(since_id)}
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass
