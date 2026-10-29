"""
=============================================================================
EduGen - Question Bank Source Pack Builder
=============================================================================
Builds a focused "source pack" of textbook chunks for a given concept tag
and batch index. Grounded in textbook page numbers and concept misconceptions.

Usage (CLI):
    python tools/question_bank/bank_pack.py --pdf javanotes9 --concept method-overriding --batch 0
=============================================================================
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.concepts import CONCEPTS, search_text_for
from core.misconceptions import misconceptions_for
from tools.question_bank.bank_prepare import BM25Index

# In-memory caches to speed up batch runs
_INDEX_CACHE = {}
_CHUNKS_CACHE = {}


def _get_index_and_chunks(pdfshort: str, work_dir: Path = None):
    if work_dir is None:
        work_dir = BASE_DIR / "data" / "bank_work"
    else:
        work_dir = Path(work_dir)

    pdf_dir = work_dir / pdfshort
    if not pdf_dir.exists():
        raise FileNotFoundError(f"Bank work directory not found for PDF '{pdfshort}': {pdf_dir}")

    if pdfshort not in _INDEX_CACHE:
        index_file = pdf_dir / "bm25.pkl"
        if not index_file.exists():
            raise FileNotFoundError(f"BM25 index not found: {index_file}. Run bank_prepare.py first.")
        _INDEX_CACHE[pdfshort] = BM25Index.load(index_file)

    if pdfshort not in _CHUNKS_CACHE:
        chunks_file = pdf_dir / "chunks.jsonl"
        if not chunks_file.exists():
            raise FileNotFoundError(f"Chunks file not found: {chunks_file}. Run bank_prepare.py first.")
        chunks_map = {}
        with open(chunks_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    chunks_map[item["chunk_id"]] = item
        _CHUNKS_CACHE[pdfshort] = chunks_map

    return _INDEX_CACHE[pdfshort], _CHUNKS_CACHE[pdfshort]


def build_concept_query(concept_tag: str) -> str:
    """
    Build rich retrieval query from concept title, keywords, summary,
    and misconception titles and wrong_belief texts.
    """
    parts = []
    base_text = search_text_for(concept_tag)
    if base_text:
        parts.append(base_text)

    misconceptions = misconceptions_for(concept_tag)
    for m in misconceptions:
        t = m.get("title")
        wb = m.get("wrong_belief")
        if t:
            parts.append(t)
        if wb:
            parts.append(wb)

    return " ".join(parts)


def build_pack(
    pdfshort: str,
    concept_tag: str,
    batch_idx: int = 0,
    max_words: int = 2200,
    work_dir: Path = None,
) -> list[dict]:
    """
    Builds a source pack of textbook chunks:
      - Query constructed from concept ontology + misconception catalog.
      - Ranked via BM25 index.
      - batch_idx rotates through ranking: starts at rank batch_idx * 4.
      - Chunks accumulated until max_words is reached.

    Returns:
      list of {
        "chunk_id": str,
        "text": str,
        "page_start": int,
        "page_end": int,
        "score": float,
        "words": int
      }
    """
    index, chunks_map = _get_index_and_chunks(pdfshort, work_dir)
    query = build_concept_query(concept_tag)
    ranked = index.score(query)

    if not ranked:
        return []

    # Rotation: batch k starts at rank k * 4
    start_rank = batch_idx * 4
    if start_rank >= len(ranked):
        # If exhausted, wrap around or clamp
        start_rank = start_rank % len(ranked)

    pack = []
    total_words = 0

    for doc_id, score in ranked[start_rank:]:
        chunk = chunks_map.get(doc_id)
        if not chunk:
            continue

        c_text = chunk["text"]
        w_count = chunk.get("word_count") or len(c_text.split())

        # Stop if adding chunk exceeds max_words (allow at least 1 chunk)
        if pack and (total_words + w_count > max_words):
            break

        pack.append({
            "chunk_id": doc_id,
            "text": c_text,
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "score": round(score, 3),
            "words": w_count,
        })
        total_words += w_count

        if total_words >= max_words:
            break

    return pack


def main():
    parser = argparse.ArgumentParser(description="Extract a source pack of textbook chunks for question generation.")
    parser.add_argument("--pdf", required=True, help="Short name of the PDF (e.g. javanotes9).")
    parser.add_argument("--concept", required=True, help="Canonical concept tag (e.g. method-overriding).")
    parser.add_argument("--batch", type=int, default=0, help="Batch index (rotates ranking by batch*4).")
    parser.add_argument("--max-words", type=int, default=2200, help="Maximum word count per pack (default: 2200).")
    parser.add_argument("--full-text", action="store_true", help="Print full text of chunks instead of preview.")
    args = parser.parse_args()

    if args.concept not in CONCEPTS:
        print(f"Warning: '{args.concept}' is not in core.concepts.CONCEPTS.")

    pack = build_pack(args.pdf, args.concept, batch_idx=args.batch, max_words=args.max_words)
    total_words = sum(c["words"] for c in pack)
    page_ranges = ", ".join(f"pp.{c['page_start']}-{c['page_end']}" for c in pack) if pack else "None"

    print("=" * 70)
    print(f"  Source Pack: {args.concept} | PDF: {args.pdf} | Batch: {args.batch}")
    print(f"  Chunks: {len(pack)} | Total words: {total_words} / {args.max_words}")
    print(f"  Page ranges: {page_ranges}")
    print("=" * 70)

    for i, c in enumerate(pack, 1):
        print(f"\n[Chunk {i}] ID: {c['chunk_id']} | Pages: {c['page_start']}-{c['page_end']} | BM25 Score: {c['score']} | Words: {c['words']}")
        print("-" * 70)
        if args.full_text:
            print(c["text"])
        else:
            snippet = c["text"][:300].replace("\n", " ")
            print(f"{snippet}...")


if __name__ == "__main__":
    main()
