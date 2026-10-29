# MCQ Generation Workflow

## Commands
1. **Plan batches:** `python tools/question_bank/gen_plan.py` (creates `data/bank_work/gen_plan.json` with 50 batches).
2. **Read next brief:** `python tools/question_bank/gen_next.py [--n 1]` (outputs misconceptions, rules, and pack text).
3. **Save & validate:** `python tools/question_bank/gen_save.py <plan_id> <candidate.jsonl>` (installs to `rag/corpus/questions/raw/`).
4. **Review progress:** `python tools/question_bank/gen_review.py` (generates `data/bank_work/pilot_review.md` and stats).

## Batch Rules
- **Quantity & Difficulty:** Exactly 12 MCQs per batch: 4 Easy, 4 Medium, 4 Hard.
- **Answer Positions:** Count per position (0, 1, 2, 3) must be `<= 5`.
- **Question Types:** At least 2 `code_output` or `bug_find` questions per batch (unless exempt concept).
- **Misconception Catalog:** Every distractor must reference a valid catalog misconception ID for that concept (max 1 null).
- **Self-Contained Java:** Snippets must be complete in ```` ```java ```` fences with `Main.main` and compile deterministically.
- **Independence:** Author original questions; never copy book sentences or cite "the text/book/passage/figure/chapter".

## How to Continue
Run `python tools/question_bank/gen_next.py --n 1`, write candidate JSONL to `data/bank_work/`, and run `gen_save.py`.
