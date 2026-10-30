# MCQ Generation Workflow

## Commands
1. **Plan batches:** `python tools/question_bank/gen_plan.py` (creates `data/bank_work/gen_plan.json` with 50 batches).
2. **Read next brief:** `python tools/question_bank/gen_next.py [--n 1]` (outputs misconceptions, rules, and pack text).
3. **Save & validate:** `python tools/question_bank/gen_save.py <plan_id> <candidate.jsonl>` (hardened gates 1-8 + deterministic option shuffle, installs to `rag/corpus/questions/raw/`).
4. **Diffcheck pilot:** `python tools/question_bank/gen_diffcheck.py <orig_dir> <new_dir>` (verifies invariants).
5. **Review progress:** `python tools/question_bank/gen_review.py` (generates `data/bank_work/pilot_review.md` and stats).

## Hardened Validation Gates (Phase 2E-b)
- **Gate 1 (Option References):** Explanations cannot refer to options by letter or number ("Option B", "choice C", "answer A", etc.).
- **Gate 2 (Prohibited Phrases):** Questions/options cannot contain "all of the above", "none of the above", or "both A and B".
- **Gate 3 (Code Fences):** `qtype` of `code_output` or `bug_find` strictly requires a ```` ```java ```` fence inside `question`.
- **Gate 4 (Option Length Bias):** The correct option cannot be strictly the longest in more than 5 of the 12 questions in a batch.
- **Gate 5 (Cross-Batch Deduplication):** Normalized word-set Jaccard similarity must be `< 0.70` against all other installed questions across the bank.
- **Gate 6 (Page Diversity):** Source pages cannot all be identical if the pack covers multiple pages.
- **Gate 7 (Deterministic Option Shuffle):** Shuffles options deterministically (SHA-1 seed from question text + attempt counter) and adjusts `correct_index` until post-shuffle answer position counts are balanced in `[2, 4]`.
- **Gate 8 (Audit Logging):** Rejections are appended to `data/bank_work/gen_log.jsonl`.

## Generation Status
- **Batches Completed:** 50 of 50 (P01 through P50)
- **Total Installed Questions:** 600 MCQs in `rag/corpus/questions/raw/`
- **Misconception Catalog Coverage:** 187 of 187 (100.0%)
