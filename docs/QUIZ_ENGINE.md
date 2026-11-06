# Quiz Engine & Misconception-First Generation Architecture (Phase 4A)

## Overview
In EduGen Phase 4A, quiz generation shifts from arbitrary topic/difficulty sampling to **misconception-first, blueprint-driven generation**. Quizzes are structured around authentic Java misconceptions cataloged in `core/misconceptions.py`, targeted dynamically based on the student's prior attempt history, grounded in the hybrid RAG index, validated through a strict canonical schema, and graded server-side with distractor misconception capture.

---

## 1. Blueprint Engine (`core/quiz_engine.py`)

A blueprint is a deterministic list of question slots:
```python
{
    "concept": str,                  # One of 44 canonical tags
    "difficulty": "Easy"|"Medium"|"Hard",
    "qtype": "concept"|"code_output"|"bug_find",
    "target_misconceptions": [id1, id2, id3]
}
```

### Blueprint Kinds
1. **`practice`** (default):
   - Targets a specific concept (defaults to `ENTRY_CONCEPT` = `'class-definition'`).
   - Slot count defaults to 5.
   - Question type mix: ~60% `concept`, ~25% `code_output`, ~15% `bug_find` (`Easy` difficulty is strictly `concept` only).
   - Difficulty defaults from the student's mastery in `concept_mastery` (<0.40: Easy, 0.40–0.70: Medium, >0.70: Hard; unknown: Easy).

2. **`diagnostic`**:
   - Designed for initial onboarding or curriculum-wide diagnostic checks.
   - 12 slots covering 1–2 foundational concepts across all 8 OOP modules (selected by fewest prerequisites in the prerequisite graph).
   - Balanced difficulty: **6 Easy + 6 Medium**.

3. **`reevaluation`**:
   - Targets specified concepts (or the student's 3 lowest-mastery concepts).
   - 2 slots per target concept at recommended difficulty.
   - Includes up to 2 retention slots for concepts mastered ($\ge 0.70$) within the last 14 days.

4. **`probe`** (Phase 5C):
   - Concept-focused misconception sweep designed for high exposure and diagnostic precision.
   - Targets a single concept: supplied concept, or the student's lowest-mastery concept with $\ge 2$ attempts that is not yet fully probed (all catalog misconceptions offered $\ge 2$ times), or lowest-mastery concept overall.
   - Defaults to 8 slots.
   - Question type mix: mostly `concept` (~75%) with at most 2 code-based slots (`code_output` / `bug_find`). Easy difficulty slots remain strictly `concept`.
   - Relaxed difficulty enabled (`slot["relax_difficulty"] = True`) to prioritize misconception coverage over exact difficulty fit.
   - Target distribution: all catalog misconceptions for the concept are ordered by priority (chosen before > never offered > fewest offers) and distributed across slots in chunks of up to 3 without repeating until all are assigned.

---

## 2. Misconception Prioritization

For each slot, `prioritize_misconceptions(student_id, concept, k=3)` ranks candidate misconceptions from `core.misconceptions` using a 3-tier pedagogical priority:
1. **Tier (a) - Chose Before**: Misconception IDs previously chosen by the student (from `question_attempts` and `student_question_history`), ordered by frequency descending.
2. **Tier (b) - Never Offered**: Misconception IDs never before included in options presented to the student (derived from `questions.tags_json["option_misconception_ids"]` joined with `student_question_history`).
3. **Tier (c) - Remainder**: Catalog misconceptions already tested but not recently failed, with a deterministic alphabetical tie-break.

---

## 3. Batched Generation & Clarifier Agent (`agents/concept_clarifier_agent.py`)

### Slot Grouping
To minimize external LLM roundtrips and latency, `group_slots(slots)` aggregates contiguous or matching slots by `(concept, difficulty)`. One LLM prompt generates all questions for that group.

### Grounding & Few-Shot Prompt Assembly
For each group, the Concept Clarifier retrieves:
1. **Lesson Passages (max 3)**: High-relevance textbook and note excerpts from the RAG index.
2. **Reference Questions ($k=3$)**: Exemplary bank MCQs matching concept and difficulty, supplied as style and difficulty examples only with strict instructions not to copy them.
3. **Target Misconceptions**: Formatted with their canonical `id`, `wrong_belief`, and `correct_idea`.
4. **Style Guidance & Rules**:
   - Exactly one correct answer.
   - Distractors crafted to match specific target misconception beliefs.
   - Valid compile-ready Java snippets in ` ```java ` blocks (unless `bug_find`).
   - Explanation focused on content, strictly forbidden from referring to option letters/numbers.
   - Spread correct option positions.

### Threshold Enforcement & Shortfall Retry
- Generated questions are passed through `normalize_question`.
- If accepted questions are $< 60\%$ of requested, a single retry targeting the shortfall is executed.
- If final accepted questions remain $< 60\%$, the quiz is rejected with an informative error rather than serving flawed content.
- A `build_report` telemetry block tracks requested, accepted, rejected reasons, latency, and models used.

---

## 4. Normalization & Validation (`normalize_question`)

Raw questions from the model are normalized to a canonical schema:
- **Reject conditions**:
  - Duplicate option texts.
  - Correct answer index out of $[0, 3]$.
  - Invalid `qtype`.
  - Unbalanced code fences (` ``` ` count odd).
  - Missing ` ```java ` fence for `code_output` or `bug_find`.
  - Explanations referencing option labels (e.g., "Option B", "(A)", "Choice 2").
- **Misconception Tag Validation**:
  - Non-existent misconception IDs or those belonging to a different concept are coerced to `None` and counted in `meta.invalid_misconceptions`.
  - Correct option's misconception ID is strictly `None`.
- **Deterministic Shuffling**:
  - Options and their corresponding misconception IDs are shuffled using a PRNG seeded by `sha1(question_text)`.
  - The correct answer index is updated to match the new position.

---

## 5. API & Persistence Wiring

### Starting a Quiz (`POST /api/quiz/start`)
- Accepts optional `kind` (`'practice'`, `'diagnostic'`, `'reevaluation'`), `concept`, `concepts`, and `difficulty`.
- Builds the blueprint, invokes `generate_quiz_from_blueprint`.
- Persists the complete internal representation (with correct answer index and misconception IDs) in `quiz_sessions.payload_json`.
- Returns sanitized question objects to the browser:
  ```json
  {"index": 0, "question": "...", "options": ["text0", "text1", "text2", "text3"]}
  ```
- Includes `kind` and `build_report_summary`.

### Submitting a Quiz (`POST /api/quiz/submit`)
- Evaluates chosen option against internal record.
- Maps wrong student choices to `option_misconception_ids[chosen]`.
- Persists misconception IDs in `question_attempts` and `student_question_history`.
- Returns an aggregated summary of diagnosed misconceptions:
  ```json
  "misconceptions_detected": [
    {
      "id": "concept/slug",
      "title": "Title",
      "wrong_belief": "...",
      "correct_idea": "...",
      "count": 1
    }
  ]
  ```

---

## 6. RAG Hardening (Part 0)

1. **Embedding Cache (`rag/embedding_cache.py`)**:
   - SQLite cache under `data/rag_cache/embedding_cache.db`.
   - Keys: `(embedder_signature, sha1(chunk_text))`.
   - Reused across ingestion runs, eliminating redundant embeddings.
2. **Degraded Lexical Fallback (`rag/retriever.py`)**:
   - 10-second timeout on runtime query embedding via thread executor.
   - Guard against embedder signature mismatch: never embed queries if the active model differs from the index model.
   - Automatic fallback to pure lexical scoring (`trace["degraded"] = "lexical_only"`).
   - Warning rate-limited to at most once per minute.

---

## 7. Quality Gates & Verification Architecture (Phase 4B)

To ensure academic rigor and prevent observed defects (compile errors in stems, conflicting distractors, unbalanced option lengths), Phase 4B introduces a multi-stage quality pipeline:

### 1. Generation Prompt Constraints
- Distractors must express realistic wrong answers matching target misconceptions.
- Stems for `bug_find` must contain exactly one compilation error.
- Options must be similar in length and complexity; the correct option must not be the longest.
- Difficulty levels strictly enforced (Easy: single fact, <=8 line snippet; Medium: one rule + one trap; Hard: interacting rules).

### 2. Deterministic Gates (`normalize_question`)
- **Length-Ratio Gate**: Reject if `len(correct option) > 1.5 * len(longest wrong option)`.
- **Null-Tag Gate**: Reject if wrong options with null misconception ID exceed 2.

### 3. Java Verification Gate (`core/java_check.py`)
- Automatically enabled when `javac` is detected on `PATH` or `JAVA_HOME`.
- Strips `public` from auxiliary classes in multi-class snippets to allow single-file compilation.
- `code_output`: Executes with a 10s timeout and validates stdout against normalized correct option text.
- `bug_find`: Validates that `javac` fails with exactly ONE error, and requires an error keyword to appear in the explanation.
- `concept`: Validates that code snippets compile without errors.
- Graceful degradation: Without a JDK, counts `java_unverified` without failing quizzes.

### 4. Independent Verifier (`verify_group`)
- Model differs from generator model (defaults to `qwen/qwen3.8-27b`, fallback `openai/gpt-oss-20b`).
- Evaluates stem and options without answer key or tags, alongside concept misconception catalog.
- Accepts question only if `answer == key` and `not ambiguous`.
- Misconception tag alignment: Retains a distractor tag only when the verifier's assigned misconception matches the generator's tag.
- If verifier service is unreachable, flags `verified=0` with a warning in `build_report` without blocking quiz delivery.

### 5. Novelty & Deduplication
- Embeds stem + correct option with active embedder and SQLite cache.
- Rejects near-duplicates with cosine >= 0.88 against current quiz session or student attempt history.
- Rejects copycat questions with cosine >= 0.93 against bank reference questions.
- Degrades to exact hash and token-Jaccard >= 0.80 if embedding backends are offline.

### 6. Parallel Execution & Telemetry
- Group generation utilizes `ThreadPoolExecutor` (max 4 workers).
- LLM calls honour HTTP 429 rate limits with `Retry-After` sleep (capped at 20s) and up to 2 retries.
- `build_report` exposes granular `stage_timings_ms` across retrieval, generation, verification, java compilation, and deduplication.

---

## 8. Prebuilt Diagnostic Sets (`rag/corpus/diagnostic/`)

Diagnostic sets are pregenerated via `scripts/build_diagnostic_sets.py --sets 3` and stored as `set_A.json`, `set_B.json`, and `set_C.json`.

### Why the First-Visit Quiz is Prebuilt:
1. **Standardized Pedagogical Baseline**: Every new learner encounters a benchmarked diagnostic covering 1-2 foundational concepts across all 8 OOP modules (6 Easy + 6 Medium). This guarantees fair and comparable initial mastery estimates across students.
2. **Instant Onboarding**: Eliminates external LLM generation latency on a student's very first interaction, providing an immediate response.
3. **Curriculum Reviewability**: Statically persisted diagnostic sets allow instructors and examiners to audit questions, verified error messages, and misconception alignments in advance.
4. **Seamless System Integration**: Prebuilt questions are ingested into `questions` through `record_generated_questions` upon serving, preserving standard server-side grading, adaptivity updates, and misconception tracking.

---

## 9. Verified Question Pool & Hybrid Serving (Phase 4C)

To minimize runtime LLM token consumption, avoid provider rate limits, and provide instant sub-second quiz start times, Phase 4C introduces the **Verified Question Pool**:

1. **Schema & Migration 4**:
   - `questions` table extended additively with:
     - `origin` (`TEXT`): `'generated'`, `'bank'`, or `'diagnostic'`.
     - `pool_status` (`TEXT`): `'active'`, `'deprecated'`, or `'quarantined'`.
     - `difficulty_verified` (`INTEGER`): Normalized numeric difficulty estimate (0=Easy, 1=Medium, 2=Hard) from the verifier.
     - `verifier_labels_json` (`TEXT`): Misconception tags assigned by the independent verifier.
     - `verified` (`INTEGER`): `1` if all gates (Java check, verifier, dedupe) passed, `0` otherwise.
   - Composite index `idx_questions_pool` on `(concept, difficulty, qtype, pool_status, verified)`.
   - `llm_calls` extended with `total_tokens` column.

2. **Pool Selection Strategy (`select_from_pool`)**:
   - **Candidate Filtering**: Only active, verified questions matching requested concept and exact difficulty.
   - **Student Isolation**: Questions previously answered by the student (`student_question_history`) are strictly excluded.
   - **Pedagogical Target Scoring**: Candidates covering the student's targeted misconceptions (`option_misconception_ids`) are scored higher and prioritized.
   - **Load Balancing**: Tie-breaking favors lowest `times_served` followed by deterministic seeded random shuffling.
   - **Within-Quiz Deduplication**: Rejects candidates with embedding cosine similarity >= 0.88 (or token-Jaccard >= 0.80) against other questions selected for the same quiz.

3. **Hybrid Serving Pipeline (`/api/quiz/start`)**:
   - Quizzes query the verified pool first.
   - Live generation is triggered **only for unfilled slots**.
   - Questions generated live that satisfy all quality gates automatically join the verified active pool.
   - Telemetry in `build_report` exposes `served_from_pool`, `generated_live`, and `pool_hit_rate`.

---

## 10. Token Budgeting & Provider Efficiency (Phase 4C)

1. **Prompt Compaction**:
   - Context passages capped at top 2 passages (<=1200 characters each).
   - Reference questions capped at top 2 items.
   - Misconception list strictly truncated to catalog ID and core `wrong_belief`.
   - Completion token limits enforced: 3000 tokens for generation, 1500 tokens for verification.

2. **Reasoning Effort Optimization**:
   - `reasoning_effort="low"` passed for quiz generation and independent verification.
   - `reasoning_effort="medium"` reserved for lesson clarification.
   - Automatic HTTP 400 fallback: If a provider returns 400 (unsupported parameter), the call retries immediately without `reasoning_effort` and remembers the model in memory to bypass the parameter on all subsequent requests.

3. **Daily Token Budget Manager (`core/token_budget.py`)**:
   - Tracks daily token usage per model from `llm_calls`.
   - Primary model cap: `EDUGEN_DAILY_TOKEN_BUDGET` (default 160,000 tokens).
   - Fallback model cap: `EDUGEN_FALLBACK_DAILY_TOKEN_BUDGET` (default 160,000 tokens).
   - **Graceful Switching**: When primary budget is reached, switches to fallback model. When both are exhausted, live generation is disabled, serving purely from the verified pool, or returning HTTP 503 `"Daily LLM budget reached"` if the pool cannot fill required slots.
   - **TPD Rate Limit Interception**: HTTP 429 errors indicating daily quota exhaustion (e.g., "TPD limit reached") or `Retry-After > 60s` mark the model exhausted immediately without sleeping.

---

## 11. Verifier Difficulty Check & Gate Hardening (Phase 4C)

1. **Verifier Difficulty Estimate**:
   - Independent verifier outputs `"difficulty_estimate": "Easy" | "Medium" | "Hard"`.
   - If estimated difficulty differs from blueprint difficulty by 2 levels (e.g. Easy vs Hard), the question is rejected with `verifier_difficulty_mismatch`.
   - Single-level differences (e.g. Easy vs Medium) are tolerated and stored as `difficulty_verified`.

2. **Positional Explanation Gate**:
   - Regex gate expanded to catch positional wording that leaks option order: `"the first/second/third/fourth/last option"`, `"option (a)"`, `"the former"`, `"the latter"`, `"the one above/below"`.

---

## 12. Probe Quiz Kind & Coverage-Greedy Selection (Phase 5C)

To eliminate exposure bottlenecks in misconception detection, Phase 5C introduces the **Probe Quiz Kind** and **Coverage-Greedy Pool Selection (`select_probe_set`)**:

### 1. Target Concept & Fully-Probed Rule
- If `concept` is explicitly provided, it is targeted directly.
- Otherwise, the engine selects the student's lowest-mastery concept that has $\ge 2$ prior question attempts and is **not yet fully probed**.
- A concept is considered **fully probed** when *every* catalog misconception associated with that concept in `core/misconceptions.py` has been presented to the student $\ge 2$ times (verified via `student_question_history` joined with `questions.tags_json["option_misconception_ids"]`).
- If all concepts with $\ge 2$ attempts are fully probed, the engine falls back to the lowest-mastery concept overall.

### 2. Misconception Prioritization & Slot Chunking
- Catalog misconceptions for the chosen concept are ordered by pedagogical priority:
  1. **Chosen Before**: Misconceptions previously chosen by the student (frequency descending).
  2. **Never Offered**: Catalog misconceptions never offered to the student.
  3. **Fewest Offers**: Catalog misconceptions with the lowest exposure counts.
  4. Deterministic alphabetical tie-break on misconception ID.
- Misconceptions are chunked into groups of up to 3 and distributed across $n$ blueprint slots (default 8).
- If the concept has more misconceptions than slots can cover in one pass, remaining targets wrap into successive slots. No target is repeated until all catalog misconceptions have been assigned to at least one slot.

### 3. Relaxed Difficulty & Question Mix
- `slot["relax_difficulty"] = True` is attached to every probe slot.
- Slot difficulty defaults from student mastery (<40: Easy, 40–70: Medium, >70: Hard).
- Question type distribution prioritizes diagnostic clarity: ~75% `concept` questions and at most 2 code-based questions (`code_output` / `bug_find`). Easy slots are strictly `concept`.

### 4. Coverage-Greedy Selection Algorithm (`select_probe_set`)
- **Strict Filters**:
  - Pool status must be `'active'` and `verified = 1`.
  - Concept must match the slot's target concept.
  - Strict student isolation: question IDs previously answered by the student are excluded.
- **Coverage-Greedy Scoring**:
  - Questions are scored by how many *uncovered* target misconceptions in the slot's target list they carry.
  - Misconception matches are weighted by priority: chosen before (weight 3.0), never offered (2.0), fewest offers (1.0).
- **Relaxed Difficulty Tie-Breaking**:
  - Candidate questions are bucketed by distance from slot difficulty:
    - Distance 0: Exact match.
    - Distance 1: Adjacent difficulty (e.g. Medium when Easy/Hard requested, or Easy/Hard when Medium requested).
    - Distance 2: Opposite difficulty (e.g. Hard when Easy requested).
  - Candidates with higher target coverage are selected first; within identical coverage, candidates with lower difficulty distance are preferred.
  - Secondary tie-breaks: lowest `times_served` followed by deterministic seeded random shuffling.
- **Deduplication & Unfilled Fallback**:
  - Rejects within-quiz duplicates (embedding cosine $\ge 0.88$ or token Jaccard $\ge 0.80$).
  - Unfilled slots are returned with their still-uncovered targets preserved, allowing the hybrid generation pipeline in `routes/api.py` to prompt the LLM specifically for the missing misconceptions.

---

## 13. Quiz Bias Guard & Heuristic Vulnerability Audit (Phase 9)

### 1. Motivation & Surface-Heuristic Vulnerability
Analysis of the question bank and LLM generations revealed test-wise gaming vulnerabilities:
- Correct options tend to be longer than distractors as authors inadvertently add qualifiers to ensure accuracy.
- Distractors disproportionately contain absolute words (`always`, `never`, `only`, `automatically`, `all`, `every`, `any`).

### 2. Live Generation Quality Gates (`normalize_question`)
In Phase 9 (tightened in Phase 9C), `core/quiz_engine.py` enforces two deterministic heuristic-bias gates during live generation:
1. **Length Disparity Gate**:
   - Rejects the question with `correct_option_too_long` if correct is strictly longest and:
     $$\text{len}(\text{correct option}) > 1.03 \times \max_{w \in \text{distractors}}(\text{len}(w))$$
2. **Absolute Word Asymmetry Gate**:
   - Rejects the question with `absolute_word_bias` if $\ge 2$ distractors contain absolute terms while the correct option does not:
     $$\sum_{w \in \text{distractors}} \mathbf{1}[\text{has\_abs}(w)] \ge 2 \quad \text{and} \quad \neg \text{has\_abs}(\text{correct})$$

### 3. Empirical Audit Numbers (`scripts/bias_audit.py`)

Baseline chance accuracy for random guessing across 4 options is **25.0%**.

#### A. Active Verified Pool (466 Questions)
| Difficulty | Total Questions | Strategy 1 (Pick Longest) | Strategy 2 (Drop Absolute Words + Longest) |
|---|---|---|---|
| **Easy** | 214 | 86 / 214 (**40.2%**) | 81 / 214 (**37.9%**) |
| **Medium** | 180 | 63 / 180 (**35.0%**) | 57 / 180 (**31.7%**) |
| **Hard** | 72 | 11 / 72 (**15.3%**) | 10 / 72 (**13.9%**) |
| **Overall** | **466** | **160 / 466 (34.3%)** | **148 / 466 (31.8%)** |

*Key finding*: Easy questions in the historical bank had the highest length bias (40.2%), while Hard questions inverted the bias (15.3%), actively penalizing length-based heuristics.

#### B. Live Generated Questions (Before Phase 9 Gate) (36 Questions)
| Difficulty | Total Questions | Strategy 1 (Pick Longest) | Strategy 2 (Drop Absolute Words + Longest) |
|---|---|---|---|
| **Easy** | 1 | 1 / 1 (**100.0%**) | 1 / 1 (**100.0%**) |
| **Medium** | 35 | 28 / 35 (**80.0%**) | 26 / 35 (**74.3%**) |
| **Overall** | **36** | **29 / 36 (80.6%)** | **27 / 36 (75.0%)** |

*Key finding*: Without bias gating, live LLM generation is severely biased toward over-explaining the correct option (80.6% gameability), proving the necessity of the Phase 9 length and absolute-word gates.

#### C. Top Biased Question IDs
The 20 most heuristic-vulnerable pool questions identified by `scripts/bias_audit.py` are:
`416, 152, 117, 178, 71, 332, 155, 31, 462, 61, 52, 44, 297, 112, 214, 443, 213, 118, 58, 261`.

#### D. Easy Pool Capacity
The active pool holds **214 Easy questions** distributed across canonical concepts, providing an average capacity of **~1.6 quizzes (3 questions/quiz)** per concept before exhaustion.


