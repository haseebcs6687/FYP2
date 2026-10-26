# Question Bank Repository

This directory contains curated and verified Multiple Choice Question (MCQ) datasets for EduGen in JSON Lines format (`.jsonl`).

## Directory Structure & Usage

- Place raw or generated question files (e.g., `chapter1_questions.jsonl`, `curated_oop.jsonl`) into this directory.
- Question records must adhere to the canonical schema defined in [docs/QUESTION_FORMAT.md](../../docs/QUESTION_FORMAT.md).

## Validation

Before questions are ingested into the database or active bank, validate them using the question validator:

```bash
# Validate all files in this directory
python scripts/validate_questions.py rag/corpus/questions --out rag/corpus/questions_validated

# Or validate a single file
python scripts/validate_questions.py rag/corpus/questions/sample.jsonl --out rag/corpus/questions_validated
```

The validation tool filters out invalid schemas, malformed Java code fences, unknown concepts, invalid misconception IDs, duplicate questions, and near-duplicates (Jaccard $\ge 0.85$). Validated questions are placed in `rag/corpus/questions_validated/accepted.jsonl` alongside a rejection audit log in `rejected.jsonl`.
