# Question Bank Repository

This directory contains curated and verified Multiple Choice Question (MCQ) datasets for EduGen in JSON Lines format (`.jsonl`).

## Directory Structure & Usage

- `raw/`: Staging area where raw LLM outputs are placed. Files follow the naming convention `<pdfshort>__<concept-tag>__b<NN>.jsonl`.
- Validated records are generated into `rag/corpus/questions_validated/accepted.jsonl`.
- Question records must adhere to the canonical schema defined in [docs/QUESTION_FORMAT.md](../../docs/QUESTION_FORMAT.md).

## Validation

Before questions are ingested into the database or active bank, validate them using the question validator:

```bash
# Validate all files in the raw staging directory
python scripts/validate_questions.py rag/corpus/questions/raw --out rag/corpus/questions_validated

# Or validate a single batch file
python scripts/validate_questions.py rag/corpus/questions/raw/corejava__method-overriding__b01.jsonl --out rag/corpus/questions_validated
```

The validation tool filters out invalid schemas, malformed Java code fences, unknown concepts, invalid misconception IDs, duplicate questions, and near-duplicates (Jaccard $\ge 0.85$). Validated questions are placed in `rag/corpus/questions_validated/accepted.jsonl` alongside a rejection audit log in `rejected.jsonl`.

## Sampling & Inspection

Use the sampling tool to inspect human-readable formatting with misconception tags:

```bash
python scripts/sample_questions.py rag/corpus/questions_validated/accepted.jsonl --n 10
```
