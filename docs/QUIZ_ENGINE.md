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
