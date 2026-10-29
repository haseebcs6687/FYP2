# Question Bank Preparation Tools

Offline dataset-construction tools. The running app never imports these.

## Tools in this directory

- `bank_prepare.py`: Extracts per-page text from PDFs in `rag/corpus/books/`, cleans running headers/footers, validates OCR quality, chunks content with page preservation, and builds BM25 index.
- `bank_pack.py`: Constructs relevant source chunk packs for any given concept tag and batch index.
- `bank_coverage.py`: Measures concept coverage per textbook, allocates question generation quotas, and generates `docs/bank_coverage.md` and `data/bank_work/quotas.json`.
- `test_bank_tools.py`: Unit and integration tests for chunking, header/footer cleaning, BM25 indexing, pack rotation, and quota allocation.
