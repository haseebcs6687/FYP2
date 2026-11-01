# EduGen Question Pool Seeding Architecture (Phase 4D)

## 1. Overview & Purpose

Phase 4D seeds the **Verified Question Pool** directly from the curated 600-question raw bank (`rag/corpus/questions/raw/`). The bank has already undergone structural and Java compilation checks; the seeding pipeline deploys the **independent verifier** to confirm question keys, assess ambiguity, calibrate difficulty levels, and conduct **3-way consensus voting** on misconception distractor tags.

---

## 2. Pipeline Architecture

```
  rag/corpus/questions/raw/<file>.jsonl (12 questions)
                          │
  data/bank_work/raw_before_2Ec/<file>.jsonl (Snapshot)
                          │
                          ▼
            [ Concept Clarifier Agent ]
                          │
             verify_bank_batch (1 call / batch)
             Model: EDUGEN_VERIFIER_MODEL (qwen/qwen3.8-27b)
             max_tokens: 1500, reasoning_effort: "low"
                          │
                          ▼
        ┌──────────────────────────────────┐
        │ Verification & Decision Gates    │
        │ - Answer matches bank key        │
        │ - Ambiguous == False             │
        │ - Difficulty estimate diff <= 1  │
        │ - Java check (if JDK available)  │
        │ - Deduplication (cosine < 0.88)  │
        └─────────────────┬────────────────┘
                          │
                          ▼
            [ 3-Way Tag Voting Consensus ]
             Labeler 1: Generator snapshot
             Labeler 2: Audited raw bank
             Labeler 3: Verifier label
                          │
                          ▼
             [ SQLite Database: questions ]
             - Accepted: origin='bank', verified=1, pool_status='active'
             - Rejected: origin='bank', verified=0, pool_status='rejected'
```

---

## 3. Decision Gates per Question

Each bank question must satisfy four quality gates:

1. **Answer Key Concordance**:
   - The verifier determines the single correct option index without knowing the bank answer key.
   - Requirement: `verifier_answer == bank_correct_index`.

2. **Unambiguity Check**:
   - The verifier checks whether multiple options could arguably be correct or if the stem is unanswerable.
   - Requirement: `ambiguous == False`.

3. **Difficulty Estimate Calibration**:
   - The verifier provides `"difficulty_estimate": "Easy" | "Medium" | "Hard"`.
   - Requirement: `abs(verifier_level - bank_level) <= 1`. A discrepancy of 2 levels (e.g. Easy vs Hard) rejects the question with `verifier_difficulty_mismatch`.

4. **Deterministic Java Execution (`core/java_check.py`)**:
   - When `javac` is detected on the system:
     - `code_output`: Compiles and executes; standard output must match the normalized correct option text.
     - `bug_find`: Must fail compilation with exactly one error; compiler keyword must appear in the explanation.
     - `concept`: Java snippets must compile cleanly without errors.
   - When `javac` is unavailable: Skipped gracefully and tracked as `java_unverified` without failing question ingestion.

5. **Novelty & Deduplication**:
   - Embeds stem + correct option using the configured embedder and cache (`data/rag_cache/embedding_cache.db`).
   - Deduplicated against all active verified questions in the pool and previous questions in the same batch.
   - Rejection threshold: Cosine similarity >= 0.88 (or token-Jaccard >= 0.80).

Failed questions are preserved in `questions` with `pool_status='rejected'` and `verified=0` alongside their failure reason (e.g. `verifier_wrong_answer`, `verifier_ambiguous`, `verifier_difficulty_mismatch`), ensuring transparency while preventing them from being served.

---

## 4. 3-Way Misconception Tag Voting

Distractor tags must be trustworthy. Tag voting requires agreement between up to three independent labelers:

- **Labeler 1 (Snapshot)**: The original generation tag from `data/bank_work/raw_before_2Ec/` matched by exact file name, line position, and stem text.
- **Labeler 2 (Current Raw)**: The current tag in `rag/corpus/questions/raw/` (post-blind audit).
- **Labeler 3 (Independent Verifier)**: The label assigned by the verifier during `verify_bank_batch`.

### Voting Rules (per wrong option):
1. **3-of-3 Consensus**: If all three labelers select the same non-null catalog ID belonging to the question's concept, the tag is kept (`tags_kept_3_of_3`).
2. **2-of-3 Consensus**: If any two labelers agree on a valid non-null catalog ID for this concept, the tag is kept (`tags_kept_2_of_3`).
3. **Labeler 1 Absent**: If snapshot history is missing or stem text differs, Labeler 1 is absent. The tag is kept only if Labeler 3 and Labeler 2 agree on a non-null catalog ID (`labeler_3 == labeler_2`).
4. **All Differ or Nulled**: If no two labelers agree, or if votes belong to a foreign concept, the distractor tag is nulled (`tags_nulled`).
5. **Correct Option**: The correct option always receives `misconception_id = None`.

---

## 5. Resumability & Token Budget Safety

1. **Cell-Prioritized Processing Order**:
   - Raw bank files are dynamically sorted before execution.
   - Files targeting the emptiest `(concept, difficulty)` pool cells (cells with count 0) are placed at the top of the queue.

2. **Persistent Progress (`data/bank_work/pool_seed_progress.json`)**:
   - Records all completed batch files in `done_batches`.
   - Tracks per-batch metrics and cumulative counters.
   - Resuming automatically skips previously completed batches.

3. **Token Budget Enforcement (`core/token_budget.py`)**:
   - The script tracks daily token consumption for `EDUGEN_VERIFIER_MODEL`.
   - If the model's daily budget is reached or a provider 429 indicates tokens-per-day exhaustion, the script cleanly saves progress and exits with code 0:
     ```bash
     Resume tomorrow with: python scripts/seed_pool_from_bank.py
     ```

---

## 6. CLI Usage & Flags

```bash
# Standard run (default: resumes from progress file)
python scripts/seed_pool_from_bank.py

# Process at most 20 batch files
python scripts/seed_pool_from_bank.py --max-batches 20

# Dry-run: view priority ordering without LLM calls or DB writes
python scripts/seed_pool_from_bank.py --dry-run

# Filter specific concepts or modules
python scripts/seed_pool_from_bank.py --only "*abstract*"

# Ignore progress file and start fresh
python scripts/seed_pool_from_bank.py --no-resume
```

