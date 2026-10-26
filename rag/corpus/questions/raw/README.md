# Raw MCQ Ingestion Directory (`rag/corpus/questions/raw/`)

This directory is the staging area for raw LLM-generated and extracted Multiple Choice Question (MCQ) JSON Lines (`.jsonl`) files.

## File Naming Convention

All raw batch files dropped into this directory must follow the canonical naming format:

```
<pdfshort>__<concept-tag>__b<NN>.jsonl
```

### Format Breakdown:
- `<pdfshort>`: Short mnemonic of the source textbook or material (e.g., `thinkjava`, `corejava`, `liang`, `deitel`).
- `__`: Double underscore separator.
- `<concept-tag>`: One of the 44 canonical concept tags from `core/concepts.py` (e.g., `method-overriding`, `classes-objects`, `try-catch`).
- `__`: Double underscore separator.
- `b<NN>`: Two-digit batch number (e.g., `b01`, `b02`, `b03`).

### Examples:
- `thinkjava__method-overriding__b01.jsonl`
- `corejava__dynamic-method-dispatch__b01.jsonl`
- `liang__constructor-chaining__b02.jsonl`

## Validation & Workflow

1. Drop new raw batch `.jsonl` files into `rag/corpus/questions/raw/`.
2. Validate using the validation CLI:
   ```bash
   python scripts/validate_questions.py rag/corpus/questions/raw --out rag/corpus/questions_validated
   ```
3. Inspect random samples of accepted questions:
   ```bash
   python scripts/sample_questions.py rag/corpus/questions_validated/accepted.jsonl --n 10
   ```
4. Note: Question files in this directory are tracked by Git and must be committed.
