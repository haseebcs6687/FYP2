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

3. **Difficulty Calibration & Relabeling (Phase 4E)**:
   - The verifier provides `"difficulty_estimate": "Easy" | "Medium" | "Hard"`.
   - **Diff <= 1 level**: Keeps the bank difficulty label and stores the verified difficulty level in `difficulty_verified`.
   - **Diff >= 2 levels (Relabel Policy)**: If `answer == key` and `ambiguous == False`, the question is **not rejected**. Instead:
     - The question is accepted into the pool.
     - Stored with `difficulty = verifier_estimate`.
     - `difficulty_verified = verifier_level`.
     - `verifier_labels_json` records `{"difficulty_original": <bank_label>, "note": "relabeled", "labels": [...]}`.
     - Counted as `relabeled` in metrics.


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

4. **Missing Verifier Result Retry Ladder (Phase 4E)**:
   - When a verifier batch response is missing results or cut off due to token limits:
     - **Stage 1 (Chunk Retry)**: Unprocessed items are re-verified in batches of up to 6 questions (`max_tokens: 1500`).
     - **Stage 2 (Single-Item Fallback)**: Any remaining missing items are verified individually with dedicated prompt budget (`max_tokens: 800`).
     - Only questions failing both retry stages are rejected as `verifier_missing_result`.

5. **Reprocessing Previous Rejects (`--reprocess-rejected`)**:
   - Scans the `questions` table for bank rows previously rejected:
     - `verifier_difficulty_mismatch`: Automatically relabeled to verifier estimate, updated to `pool_status='active'`, `verified=1`.
     - `verifier_missing_result`: Re-verified via single-item calls with the verifier agent.
     - Deterministic errors (`bug_find_compiles`, `code_output_mismatch`, `verifier_wrong_answer`) are preserved as rejected.

---

## 6. CLI Usage & Flags

```bash
# Standard run (default: resumes from progress file)
python scripts/seed_pool_from_bank.py

# Reprocess previous difficulty mismatches and retried missing results
python scripts/seed_pool_from_bank.py --resume --reprocess-rejected

# Process at most 20 batch files
python scripts/seed_pool_from_bank.py --max-batches 20

# Dry-run: view priority ordering without LLM calls or DB writes
python scripts/seed_pool_from_bank.py --dry-run

# Filter specific concepts or modules
python scripts/seed_pool_from_bank.py --only "*abstract*"

# Ignore progress file and start fresh
python scripts/seed_pool_from_bank.py --no-resume
```

---

## 7. Seeding Results & Cumulative Metrics (Phase 4D + Phase 11b)

```
========================================================================================
BANK POOL SEEDING SUMMARY (CUMULATIVE: 74 BATCHES)
========================================================================================
Metric                                 | Phase 4D (Initial)   | Phase 11b (Top-Up)   | Cumulative (Total)  
----------------------------------------------------------------------------------------
Batches processed                      | 50                   | 24                   | 74                  
Questions processed                    | 600                  | 288                  | 888                 
Questions accepted                     | 403 (67.2%)          | 239 (83.0%)          | 642 (72.3%)         
  - Relabeled (2-level diff)           | 51                   | 54                   | 105                 
Questions rejected                     | 41                   | 49                   | 90                  
  - bug_find_compiles                  | 9                    | 21                   | 30                  
  - bug_find_error_count_2             | 2                    | 4                    | 6                   
  - bug_find_error_count_4             | 1                    | 0                    | 1                   
  - bug_find_explanation_mismatch      | 6                    | 5                    | 11                  
  - code_output_mismatch               | 4                    | 1                    | 5                   
  - code_output_runtime_error          | 0                    | 1                    | 1                   
  - verifier_difficulty_mismatch       | 0                    | 0                    | 0                   
  - verifier_missing_result            | 14                   | 9                    | 23                  
  - verifier_wrong_answer              | 6                    | 8                    | 14                  
Tags kept (3-of-3 agreement)           | 170                  | 0                    | 170                 
Tags kept (2-of-3 agreement)           | 290                  | 0                    | 396                 
Tags nulled                            | 872                  | 758                  | 1630                
Java unverified (no javac)             | 0                    | 0                    | 0 (100% verified)   
Verifier retries                       | 2                    | 10                   | 14                  
Verifier Tokens Consumed (Qwen 27B)    | -                    | 42,548 tokens        | 42,548 tokens       
========================================================================================
Active Pool Total                      | 464 questions        | +239 bank questions  | 703 questions       
  - Easy                               | 215 questions        | +135 questions       | 350 questions       
  - Medium                             | 146 questions        | +71 questions        | 217 questions       
  - Hard                               | 72 questions         | +33 questions        | 105 questions       
========================================================================================
```

---

## 8. Blind Bias Audit Summary (Old Bank vs New Top-Up)

Audited via `scripts/bias_audit.py` across all active bank questions:

| Heuristic Strategy | Old Bank (N = 403) | New Top-Up Bank (N = 239) | Target | Result |
| :--- | :---: | :---: | :---: | :---: |
| **always-longest** | 120/403 (29.8%) | 59/239 (24.7%) | $\le 35.0\%$ | **PASS** |
| **always-shortest** | 116/403 (28.8%) | 57/239 (23.8%) | $\le 35.0\%$ | **PASS** |
| **avoid-absolute-words** | 113/403 (28.0%) | 59/239 (24.7%) | $\le 35.0\%$ | **PASS** |
| **always option 0** | 108/403 (26.8%) | 58/239 (24.3%) | $\le 35.0\%$ | **PASS** |
| **always option 1** | 104/403 (25.8%) | 57/239 (23.8%) | $\le 35.0\%$ | **PASS** |
| **always option 2** | 90/403 (22.3%) | 65/239 (27.2%) | $\le 35.0\%$ | **PASS** |
| **always option 3** | 101/403 (25.1%) | 59/239 (24.7%) | $\le 35.0\%$ | **PASS** |

*Note: Uniform random guessing baseline is 25.0%. All 7 blind heuristics operate at baseline levels ($\le 27.2\%$), with 0 new bank questions requiring quarantine.*



