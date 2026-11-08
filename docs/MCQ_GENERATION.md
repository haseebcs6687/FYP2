# MCQ Generation Workflow

## Commands
1. **Plan batches:** `python tools/question_bank/gen_plan.py` (creates `data/bank_work/gen_plan.json` with 50 batches).
2. **Read next brief:** `python tools/question_bank/gen_next.py [--n 1]` (outputs misconceptions, rules, and pack text).
3. **Save & validate:** `python tools/question_bank/gen_save.py <plan_id> <candidate.jsonl>` (hardened gates 1-8 + deterministic option shuffle, installs to `rag/corpus/questions/raw/`).
4. **Diffcheck pilot/audit:** `python tools/question_bank/gen_diffcheck.py <orig_dir> <new_dir> [--allow-changed <file>]` (verifies invariants).
5. **Review progress:** `python tools/question_bank/gen_review.py` (generates `data/bank_work/pilot_review.md` and stats).
6. **Tag Audit:** `python tools/question_bank/gen_tagaudit.py [export|merge]` (blind tag audit generation and merge).

## Hardened Validation Gates (Phase 2E-b)
- **Gate 1 (Option References):** Explanations cannot refer to options by letter or number ("Option B", "choice C", "answer A", etc.).
- **Gate 2 (Prohibited Phrases):** Questions/options cannot contain "all of the above", "none of the above", or "both A and B".
- **Gate 3 (Code Fences):** `qtype` of `code_output` or `bug_find` strictly requires a ```` ```java ```` fence inside `question`.
- **Gate 4 (Option Length Bias):** The correct option cannot be strictly the longest in more than 5 of the 12 questions in a batch.
- **Gate 5 (Cross-Batch Deduplication):** Normalized word-set Jaccard similarity must be `< 0.70` against all other installed questions across the bank.
- **Gate 6 (Page Diversity):** Source pages cannot all be identical if the pack covers multiple pages.
- **Gate 7 (Deterministic Option Shuffle):** Shuffles options deterministically (SHA-1 seed from question text + attempt counter) and adjusts `correct_index` until post-shuffle answer position counts are balanced in `[2, 4]`.
- **Gate 8 (Audit Logging):** Rejections are appended to `data/bank_work/gen_log.jsonl`.

## Phase 2E-c Hardening & Quality Audit
- **Defect Fixes:** Repaired specific defects across 16 questions (added no-arg constructor to superclasses to preserve single intended error; rewrote hedged options into definite javac errors; converted code_output to concept for GC questions and bug_find for constructor compilation error; fixed package declarations and access modifier explanation).
- **ID Normalization:** Every question across all 50 batches adheres strictly to the canonical format `<pdfshort>__<concept>__b<NN>_q<NN>` (all 600 unique).
- **Blind Tag Audit:** Independent relabeling performed via `gen_tagaudit.py` without seeing existing tags. Options matching the independent label preserved their catalog misconception; non-agreed tags set to `null`.
- **Relaxed Null Misconception Rule:** Wrong options may have `misconception_id: null` (0 to 3 per question), denoting "no verified catalog match". Non-null tags must strictly belong to the concept's catalog.
- **Validator Traversal Fix:** Fixed double-traversal bug in `scripts/validate_questions.py` by resolving input file paths into a unique set.

## Phase 11a Gap Generation & Pool Top-up
- **Gap-Driven Generation:** Created `tools/question_bank/gen_gap_plan.py` which inspects `data/edugen.db` (read-only mode) to compute active question deficits per `(concept, difficulty)` cell against targets (Easy >= 4, Medium >= 3, Hard >= 3).
- **Dynamic Difficulty Mix:** Extended `tools/question_bank/gen_save.py` and `gen_next.py` with `--plan` support to enforce batch-specific mixes `{"Easy": a, "Medium": b, "Hard": c}` summing to 12 rather than rigid 4/4/4 splits.
- **Top-up Execution:** Generated 24 new batches (G01 through G24) across the highest-deficit concepts (`default-constructor`, `access-modifiers`, `checked-vs-unchecked`, `default-values`, `constructor-basics`, `inheritance-hierarchy`, `dynamic-method-dispatch`, `abstraction-basics`, `null-pointer-exception`, `object-instantiation`, `data-hiding`, `reference-semantics`, `constructor-overloading`, `copy-constructor`, `getters-setters`, `javabeans`).
- **Catalog Misconception Targeting:** Addressed missing misconceptions in distractors, notably covering `null-pointer-exception/calling-static-on-null-throws-npe`, `null-pointer-exception/null-string-concatenation-throws`, and `null-pointer-exception/null-instanceof-check-throws`.
- **Quality Gates:** All 16 validation gates enforced (zero syntax errors, Jaccard token overlap < 0.70 against all installed questions, option length balance, code fences with valid Java snippets, deterministic option shuffle).

## Generation Status
- **Batches Completed:** 74 of 74 (P01 through P50 + G01 through G24)
- **Total Installed Questions:** 888 MCQs in `rag/corpus/questions/raw/`
  - Pilot Batches (P01–P50): 600 MCQs (Easy=200, Medium=200, Hard=200)
  - Top-up Batches (G01–G24): 288 MCQs (Easy=85, Medium=86, Hard=117)
  - Overall Bank: 888 MCQs (Easy=285, Medium=286, Hard=317)
  - PDF Distribution: JavaNotesForProfessionals=420, javanotes9=276, thinkjava2=192
- **Validation Status:** 888 of 888 accepted (0 rejected)


