"""
=============================================================================
EduGen - Phase 4D Question Pool Seeding from Bank
=============================================================================
Seeds the verified question pool from the 600-question raw bank:
  - Batching: 1 file (12 questions) = 1 verifier LLM call
  - Verifier model: EDUGEN_VERIFIER_MODEL (reasoning_effort low, max_tokens 1500)
  - Decision per question:
      * verifier answer == bank correct_index
      * not ambiguous
      * difficulty_estimate within 1 level of label
      * java_check passes if javac available (else counts java_unverified)
      * dedupe against pool (cosine >= 0.88 or exact hash) and batch
  - 3-Way Tag Voting per wrong option (2-of-3 consensus):
      * Labeler 1: snapshot (data/bank_work/raw_before_2Ec/)
      * Labeler 2: current raw (rag/corpus/questions/raw/)
      * Labeler 3: independent verifier
  - Resumable: progress saved to data/bank_work/pool_seed_progress.json
  - Budget-safe: stops cleanly when token budget is exhausted or 429 TPD occurs
=============================================================================
"""

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    import dotenv
    dotenv.load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from agents.concept_clarifier_agent import ConceptClarifierAgent
from core.db import get_db, init_db
from core.db_repo import record_generated_questions
from core.java_check import JavaChecker
from core.misconceptions import is_valid_misconception
from core.quiz_engine import (
    cosine_similarity,
    deserialize_embedding,
    token_jaccard,
)
from core.token_budget import (
    get_today_token_usage,
    is_model_exhausted,
)

RAW_BANK_DIR = BASE_DIR / "rag" / "corpus" / "questions" / "raw"
SNAPSHOT_DIR = BASE_DIR / "data" / "bank_work" / "raw_before_2Ec"
PROGRESS_FILE = BASE_DIR / "data" / "bank_work" / "pool_seed_progress.json"

DIFF_LEVELS = {"Easy": 0, "Medium": 1, "Hard": 2}


def vote_tag(l1_present, l1, l2, l3, concept):
    """
    3-way tag voting per wrong option:
      - Labeler 1: snapshot tag
      - Labeler 2: current audited bank tag
      - Labeler 3: verifier label
    Rule:
      - Final tag is a catalog ID that at least 2 labelers chose for that option
        (must belong to the concept's catalog).
      - If labeler 1 is absent / unavailable, require labeler 3 == labeler 2 (non-null).
      - Otherwise null.
    Returns:
      (final_tag, agreement_type) where agreement_type in ('3_of_3', '2_of_3', 'nulled')
    """
    if not l1_present:
        if l2 and l3 and l2 == l3 and is_valid_misconception(l2, concept=concept):
            return l2, "2_of_3"
        return None, "nulled"

    # All 3 labelers available
    # Check 3 of 3 agreement on a valid non-null catalog id
    if l1 and l2 and l3 and l1 == l2 == l3 and is_valid_misconception(l1, concept=concept):
        return l1, "3_of_3"

    # Check 2 of 3 agreement on a valid non-null catalog id
    votes = [tag for tag in (l1, l2, l3) if tag and is_valid_misconception(tag, concept=concept)]
    counts = {}
    for tag in votes:
        counts[tag] = counts.get(tag, 0) + 1

    for tag, count in counts.items():
        if count >= 2:
            return tag, "2_of_3"

    return None, "nulled"


def load_pool_questions_for_dedupe(conn):
    """
    Load stem, correct option text, hash, and deserialized embeddings
    for all active/verified questions in the pool to deduplicate against.
    """
    try:
        rows = conn.execute(
            """SELECT question_text, options_json, correct_index, embedding, text_hash
               FROM questions
               WHERE pool_status = 'active' AND verified = 1"""
        ).fetchall()
        pool_list = []
        for r in rows:
            q_text = str(r["question_text"] or "").strip()
            opts = []
            try:
                opts = json.loads(r["options_json"] or "[]")
            except Exception:
                pass
            c_idx = int(r["correct_index"] or 0)
            c_opt = opts[c_idx] if 0 <= c_idx < len(opts) else ""
            if isinstance(c_opt, dict):
                c_opt = c_opt.get("text", "")
            stem_ans = f"{q_text}\n{str(c_opt).strip()}".strip()
            thash = r["text_hash"] or hashlib.sha256(" ".join(stem_ans.lower().split()).encode("utf-8")).hexdigest()
            emb = deserialize_embedding(r["embedding"])
            pool_list.append((thash, stem_ans, emb))
        return pool_list
    except Exception:
        return []


def get_cell_counts(conn):
    """
    Return a dict (concept, difficulty) -> active verified question count.
    """
    counts = {}
    try:
        rows = conn.execute(
            """SELECT concept, difficulty, COUNT(*) as cnt
               FROM questions
               WHERE pool_status = 'active' AND verified = 1
               GROUP BY concept, difficulty"""
        ).fetchall()
        for r in rows:
            counts[(r["concept"], r["difficulty"])] = int(r["cnt"])
    except Exception:
        pass
    return counts


def order_bank_files(files, cell_counts):
    """
    Order bank files to prioritize filling the emptiest concept/difficulty cells.
    Files targeting cells with the lowest verified count are processed first.
    """
    scored = []
    for f in files:
        concept = None
        file_diffs = set()
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    q = json.loads(line)
                    concept = q.get("concept")
                    file_diffs.add(q.get("difficulty", "Easy"))
        except Exception:
            pass

        if not concept:
            scored.append((999999, 999999, f.name, f))
            continue

        min_cnt = min(cell_counts.get((concept, d), 0) for d in file_diffs) if file_diffs else 0
        sum_cnt = sum(cell_counts.get((concept, d), 0) for d in file_diffs)
        scored.append((min_cnt, sum_cnt, f.name, f))

    # Sort by min count asc, sum count asc, file name asc
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [item[3] for item in scored]


def load_progress(progress_path=None):
    """Load seeding progress from JSON file."""
    path = progress_path or PROGRESS_FILE
    if not path.exists():
        return {
            "done_batches": [],
            "batch_stats": {},
            "cumulative_stats": {
                "batches_processed": 0,
                "questions_processed": 0,
                "accepted": 0,
                "rejected": 0,
                "rejection_reasons": {},
                "tags_kept_3_of_3": 0,
                "tags_kept_2_of_3": 0,
                "tags_nulled": 0,
                "java_unverified": 0,
            },
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "done_batches": [],
            "batch_stats": {},
            "cumulative_stats": {
                "batches_processed": 0,
                "questions_processed": 0,
                "accepted": 0,
                "rejected": 0,
                "rejection_reasons": {},
                "tags_kept_3_of_3": 0,
                "tags_kept_2_of_3": 0,
                "tags_nulled": 0,
                "java_unverified": 0,
            },
        }


def save_progress(data, progress_path=None):
    """Save seeding progress to JSON file."""
    path = progress_path or PROGRESS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def process_bank_file(
    bank_file,
    clarifier,
    java_checker,
    embedder,
    cache,
    pool_dedupe_list,
    dry_run=False,
    conn=None,
):
    """
    Process one bank file (batch of 12 questions):
      1. Load questions from raw bank file.
      2. Load snapshot from raw_before_2Ec for Labeler 1.
      3. Call clarifier.verify_bank_batch for verification and Labeler 3.
      4. For each question:
           - verify correctness, ambiguity, and difficulty
           - verify Java code snippet (if javac available)
           - dedupe against pool and current batch
           - vote on misconception tags (3-way)
      5. Insert accepted and rejected questions to questions table.
    Returns: (batch_stats, should_stop, stop_reason)
    """
    stats = {
        "processed": 0,
        "accepted": 0,
        "rejected": 0,
        "rejection_reasons": {},
        "tags_kept_3_of_3": 0,
        "tags_kept_2_of_3": 0,
        "tags_nulled": 0,
        "java_unverified": 0,
    }

    questions = []
    with open(bank_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))

    if not questions:
        return stats, False, None

    concept = questions[0].get("concept")
    stats["processed"] = len(questions)

    # 1. Load snapshot questions for Labeler 1
    snap_file = SNAPSHOT_DIR / bank_file.name
    snap_questions = []
    if snap_file.exists():
        try:
            with open(snap_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        snap_questions.append(json.loads(line))
        except Exception:
            snap_questions = []

    if dry_run:
        return stats, False, None

    # 2. Call Verifier Agent
    v_map, v_model, v_err = clarifier.verify_bank_batch(questions, concept)
    if v_err:
        is_budget = "budget_exhausted" in str(v_err).lower() or "daily llm budget reached" in str(v_err).lower()
        return stats, is_budget, v_err

    # 3. Evaluate each question
    accepted_in_batch = []
    batch_records_to_insert = []

    for idx, q in enumerate(questions):
        bank_correct = int(q.get("correct_index", q.get("correct", 0)))
        bank_diff = str(q.get("difficulty", "Easy")).capitalize()
        bank_diff_lvl = DIFF_LEVELS.get(bank_diff, 0)
        qtype = q.get("qtype", "concept")

        # Snapshot match for Labeler 1
        l1_present = False
        l1_options = []
        if idx < len(snap_questions):
            sq = snap_questions[idx]
            q_stem_norm = " ".join(str(q.get("question") or "").strip().lower().split())
            sq_stem_norm = " ".join(str(sq.get("question") or "").strip().lower().split())
            if q_stem_norm == sq_stem_norm:
                l1_present = True
                l1_options = sq.get("options", [])

        # Verifier decision check
        v_data = (v_map or {}).get(idx)
        reject_reason = None

        if not v_data:
            reject_reason = "verifier_missing_result"
        else:
            v_ans = v_data.get("answer")
            if v_ans is None and "correct" in v_data:
                v_ans = v_data.get("correct")
            try:
                v_ans = int(v_ans)
            except (TypeError, ValueError):
                v_ans = None

            if v_ans != bank_correct:
                reject_reason = "verifier_wrong_answer"
            elif bool(v_data.get("ambiguous", False)):
                reject_reason = "verifier_ambiguous"
            else:
                v_diff_str = str(v_data.get("difficulty_estimate") or "").strip().capitalize()
                v_diff_lvl = DIFF_LEVELS.get(v_diff_str)
                if v_diff_lvl is not None and abs(v_diff_lvl - bank_diff_lvl) >= 2:
                    reject_reason = "verifier_difficulty_mismatch"

        # Java check
        if not reject_reason:
            if java_checker and java_checker.available:
                ok, j_reason = java_checker.check_question({
                    "question": q.get("question"),
                    "qtype": qtype,
                    "options": q.get("options", []),
                    "correct": bank_correct,
                    "explanation": q.get("explanation", ""),
                })
                if not ok:
                    reject_reason = j_reason
            else:
                stats["java_unverified"] += 1

        # Embedding & Deduplication
        stem = str(q.get("question") or "").strip()
        opts = q.get("options", [])
        c_opt = opts[bank_correct] if 0 <= bank_correct < len(opts) else ""
        c_text = str(c_opt.get("text") if isinstance(c_opt, dict) else c_opt).strip()
        stem_and_answer = f"{stem}\n{c_text}".strip()
        norm_hash = hashlib.sha256(" ".join(stem_and_answer.lower().split()).encode("utf-8")).hexdigest()

        current_emb = None
        if embedder:
            try:
                sig = embedder.signature()
                sha1 = hashlib.sha1(stem_and_answer.encode("utf-8")).hexdigest()
                hit = cache.get_many(sig, [sha1]) if cache else {}
                if sha1 in hit:
                    current_emb = hit[sha1]
                else:
                    current_emb = embedder.embed(stem_and_answer)
                    if cache and current_emb:
                        cache.put_many(sig, {sha1: current_emb})
            except Exception:
                current_emb = None

        if not reject_reason:
            # Check dedupe in batch
            for b_thash, b_text, b_emb in accepted_in_batch:
                if norm_hash == b_thash:
                    reject_reason = "duplicate_in_batch"
                    break
                if embedder and b_emb and current_emb:
                    if cosine_similarity(current_emb, b_emb) >= 0.88:
                        reject_reason = "duplicate_in_batch"
                        break
                elif token_jaccard(stem_and_answer, b_text) >= 0.80:
                    reject_reason = "duplicate_in_batch"
                    break

        if not reject_reason:
            # Check dedupe against pool
            for p_thash, p_text, p_emb in pool_dedupe_list:
                if norm_hash == p_thash:
                    reject_reason = "duplicate_in_pool"
                    break
                if embedder and p_emb and current_emb:
                    if cosine_similarity(current_emb, p_emb) >= 0.88:
                        reject_reason = "duplicate_in_pool"
                        break
                elif token_jaccard(stem_and_answer, p_text) >= 0.80:
                    reject_reason = "duplicate_in_pool"
                    break

        # Tag voting per option
        v_labels = (v_data.get("labels") if v_data else None) or [None] * 4
        while len(v_labels) < 4:
            v_labels.append(None)

        final_mids = [None] * 4
        for oi in range(4):
            if oi == bank_correct:
                final_mids[oi] = None
                continue

            l2 = opts[oi].get("misconception_id") if (oi < len(opts) and isinstance(opts[oi], dict)) else None
            l1 = None
            if l1_present and oi < len(l1_options):
                l1 = l1_options[oi].get("misconception_id") if isinstance(l1_options[oi], dict) else None
            l3 = v_labels[oi]

            tag, agree_type = vote_tag(l1_present, l1, l2, l3, concept=concept)
            final_mids[oi] = tag
            if agree_type == "3_of_3":
                stats["tags_kept_3_of_3"] += 1
            elif agree_type == "2_of_3":
                stats["tags_kept_2_of_3"] += 1
            else:
                stats["tags_nulled"] += 1

        v_diff_str = str(v_data.get("difficulty_estimate") or "").strip().capitalize() if v_data else None
        v_diff_lvl = DIFF_LEVELS.get(v_diff_str) if v_diff_str else bank_diff_lvl

        if not reject_reason:
            stats["accepted"] += 1
            accepted_in_batch.append((norm_hash, stem_and_answer, current_emb))
            pool_dedupe_list.append((norm_hash, stem_and_answer, current_emb))

            rec = {
                "question": q["question"],
                "options": [opt["text"] if isinstance(opt, dict) else str(opt) for opt in q.get("options", [])],
                "correct": bank_correct,
                "explanation": q.get("explanation", ""),
                "concept": concept,
                "concept_tags": [concept],
                "difficulty": bank_diff,
                "qtype": qtype,
                "option_misconception_ids": final_mids,
                "facet": q.get("facet"),
                "verified": 1,
                "origin": "bank",
                "pool_status": "active",
                "difficulty_verified": v_diff_lvl,
                "verifier_labels": v_labels,
                "embedding": current_emb,
            }
            batch_records_to_insert.append(rec)
        else:
            stats["rejected"] += 1
            stats["rejection_reasons"][reject_reason] = stats["rejection_reasons"].get(reject_reason, 0) + 1

            rec = {
                "question": q["question"],
                "options": [opt["text"] if isinstance(opt, dict) else str(opt) for opt in q.get("options", [])],
                "correct": bank_correct,
                "explanation": q.get("explanation", ""),
                "concept": concept,
                "concept_tags": [concept],
                "difficulty": bank_diff,
                "qtype": qtype,
                "option_misconception_ids": final_mids,
                "facet": q.get("facet"),
                "verified": 0,
                "origin": "bank",
                "pool_status": "rejected",
                "difficulty_verified": v_diff_lvl,
                "verifier_labels": v_labels,
                "embedding": current_emb,
            }
            batch_records_to_insert.append(rec)

    # Persist all questions into DB
    if batch_records_to_insert:
        for rec in batch_records_to_insert:
            record_generated_questions(
                rec["concept"],
                rec["difficulty"],
                [rec],
                model=v_model,
                source="bank",
                origin="bank",
                pool_status=rec["pool_status"],
            )

    return stats, False, None


def main():
    parser = argparse.ArgumentParser(description="EduGen Phase 4D - Seed Question Pool from Bank")
    parser.add_argument("--max-batches", type=int, default=None, help="Maximum number of batch files to process")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from progress file (default: True)")
    parser.add_argument("--no-resume", action="store_false", dest="resume", help="Ignore progress file and start over")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without calling LLM or writing DB")
    parser.add_argument("--only", type=str, default=None, help="Glob pattern to filter files (e.g. '*abstract*')")
    parser.add_argument("--db-path", type=str, default=None, help="Custom database path")
    args = parser.parse_args()

    if args.db_path:
        os.environ["EDUGEN_DB_PATH"] = args.db_path
        init_db(args.db_path)
    else:
        init_db()

    conn = get_db(args.db_path)

    # Setup clarifier agent, embedder, and java checker
    clarifier = ConceptClarifierAgent()
    java_checker = JavaChecker()

    active_embedder = None
    active_cache = None
    try:
        from rag.embedder import get_embedder
        from rag.embedding_cache import EmbeddingCache
        active_embedder = get_embedder(quiet=True)
        active_cache = EmbeddingCache()
    except Exception:
        active_embedder = None
        active_cache = None

    # Load all raw bank files
    raw_files = sorted(list(RAW_BANK_DIR.glob("*.jsonl")))
    if args.only:
        raw_files = [f for f in raw_files if fnmatch.fnmatch(f.name, args.only)]

    # Load progress
    progress = load_progress() if args.resume else {
        "done_batches": [],
        "batch_stats": {},
        "cumulative_stats": {
            "batches_processed": 0,
            "questions_processed": 0,
            "accepted": 0,
            "rejected": 0,
            "rejection_reasons": {},
            "tags_kept_3_of_3": 0,
            "tags_kept_2_of_3": 0,
            "tags_nulled": 0,
            "java_unverified": 0,
        },
    }

    done_batches = set(progress.get("done_batches", []))
    remaining_files = [f for f in raw_files if f.name not in done_batches]

    # Order files by emptiest pool cells first
    cell_counts = get_cell_counts(conn)
    ordered_files = order_bank_files(remaining_files, cell_counts)

    print("========================================================================================")
    print("EDUGEN PHASE 4D: SEED QUESTION POOL FROM 600-QUESTION BANK")
    print("========================================================================================")
    print(f"Total raw bank files     : {len(raw_files)}")
    print(f"Batches already completed: {len(done_batches)}")
    print(f"Batches to process       : {len(ordered_files)}")
    if args.max_batches:
        print(f"Batch limit for this run : {args.max_batches}")
    print(f"Verifier model           : {clarifier.verifier_model}")
    print(f"Java checker available   : {java_checker.available}")
    print(f"Embedder available       : {active_embedder is not None}")
    print(f"Dry run                  : {args.dry_run}")
    print("========================================================================================")

    if args.dry_run:
        print("\nDry run plan (First 10 files in queue):")
        for i, f in enumerate(ordered_files[:10]):
            print(f"  {i + 1:2d}. {f.name}")
        return

    # Load existing pool questions for deduplication
    pool_dedupe_list = load_pool_questions_for_dedupe(conn)
    conn.close()

    run_stats = {
        "batches_processed": 0,
        "questions_processed": 0,
        "accepted": 0,
        "rejected": 0,
        "rejection_reasons": {},
        "tags_kept_3_of_3": 0,
        "tags_kept_2_of_3": 0,
        "tags_nulled": 0,
        "java_unverified": 0,
    }

    v_model = clarifier.verifier_model
    stopped_cleanly = False
    stop_reason = None

    for b_idx, f in enumerate(ordered_files):
        if args.max_batches and (len(progress.get("done_batches", [])) >= args.max_batches or run_stats["batches_processed"] >= args.max_batches):
            break

        # Check token budget before batch
        if is_model_exhausted(v_model, clarifier.model, clarifier.fallback_model):
            stopped_cleanly = True
            stop_reason = "Token budget exhausted for verifier model"
            break

        print(f"\nProcessing batch {b_idx + 1}/{len(ordered_files)}: {f.name}...")
        b_stats, should_stop, err = process_bank_file(
            f,
            clarifier,
            java_checker,
            active_embedder,
            active_cache,
            pool_dedupe_list,
            dry_run=args.dry_run,
        )

        if should_stop:
            stopped_cleanly = True
            stop_reason = err
            print(f"  Stopped: {err}")
            break

        if err:
            print(f"  Warning on batch {f.name}: {err}")

        # Update run stats
        run_stats["batches_processed"] += 1
        run_stats["questions_processed"] += b_stats["processed"]
        run_stats["accepted"] += b_stats["accepted"]
        run_stats["rejected"] += b_stats["rejected"]
        for r, cnt in b_stats["rejection_reasons"].items():
            run_stats["rejection_reasons"][r] = run_stats["rejection_reasons"].get(r, 0) + cnt
        run_stats["tags_kept_3_of_3"] += b_stats["tags_kept_3_of_3"]
        run_stats["tags_kept_2_of_3"] += b_stats["tags_kept_2_of_3"]
        run_stats["tags_nulled"] += b_stats["tags_nulled"]
        run_stats["java_unverified"] += b_stats["java_unverified"]

        print(
            f"  Result: {b_stats['accepted']}/{b_stats['processed']} accepted, "
            f"{b_stats['rejected']} rejected, "
            f"tags kept: {b_stats['tags_kept_3_of_3']} (3/3), {b_stats['tags_kept_2_of_3']} (2/3)"
        )

        # Update cumulative progress
        progress["done_batches"].append(f.name)
        progress["batch_stats"][f.name] = b_stats
        c_stats = progress["cumulative_stats"]
        c_stats["batches_processed"] += 1
        c_stats["questions_processed"] += b_stats["processed"]
        c_stats["accepted"] += b_stats["accepted"]
        c_stats["rejected"] += b_stats["rejected"]
        for r, cnt in b_stats["rejection_reasons"].items():
            c_stats["rejection_reasons"][r] = c_stats["rejection_reasons"].get(r, 0) + cnt
        c_stats["tags_kept_3_of_3"] += b_stats["tags_kept_3_of_3"]
        c_stats["tags_kept_2_of_3"] += b_stats["tags_kept_2_of_3"]
        c_stats["tags_nulled"] += b_stats["tags_nulled"]
        c_stats["java_unverified"] += b_stats["java_unverified"]

        save_progress(progress)

    # Print summary table
    cum = progress["cumulative_stats"]
    v_today_tokens = get_today_token_usage(v_model)

    print("\n" + "=" * 88)
    print("BANK POOL SEEDING SUMMARY")
    print("=" * 88)
    print(f"{'Metric':<38} | {'This Run':<20} | {'Cumulative':<20}")
    print("-" * 88)
    print(f"{'Batches processed':<38} | {run_stats['batches_processed']:<20} | {cum['batches_processed']:<20}")
    print(f"{'Questions processed':<38} | {run_stats['questions_processed']:<20} | {cum['questions_processed']:<20}")
    print(f"{'Questions accepted':<38} | {run_stats['accepted']:<20} | {cum['accepted']:<20}")
    print(f"{'Questions rejected':<38} | {run_stats['rejected']:<20} | {cum['rejected']:<20}")

    all_reasons = set(run_stats["rejection_reasons"].keys()) | set(cum.get("rejection_reasons", {}).keys())
    for r in sorted(all_reasons):
        r_run = run_stats["rejection_reasons"].get(r, 0)
        r_cum = cum.get("rejection_reasons", {}).get(r, 0)
        print(f"  - {r:<34} | {r_run:<20} | {r_cum:<20}")

    print(f"{'Tags kept (3-of-3 agreement)':<38} | {run_stats['tags_kept_3_of_3']:<20} | {cum['tags_kept_3_of_3']:<20}")
    print(f"{'Tags kept (2-of-3 agreement)':<38} | {run_stats['tags_kept_2_of_3']:<20} | {cum['tags_kept_2_of_3']:<20}")
    print(f"{'Tags nulled':<38} | {run_stats['tags_nulled']:<20} | {cum['tags_nulled']:<20}")
    print(f"{'Java unverified (no javac)':<38} | {run_stats['java_unverified']:<20} | {cum['java_unverified']:<20}")
    print(f"{'Tokens consumed today (' + v_model + ')':<38} | {v_today_tokens:<20} | {v_today_tokens:<20}")
    print("=" * 88)

    if stopped_cleanly:
        print("\nStopping cleanly due to token budget:")
        print("  Resume tomorrow with: python scripts/seed_pool_from_bank.py")
        print(f"  Tokens used so far today: {v_today_tokens}")

    # Re-run scripts/pool_status.py
    print("\nRefreshing pool status...")
    try:
        import subprocess
        subprocess.run([sys.executable, str(BASE_DIR / "scripts" / "pool_status.py")], check=True)
    except Exception as exc:
        print(f"Failed to refresh pool status: {exc}")


if __name__ == "__main__":
    main()
