"""
=============================================================================
EduGen RAG - Ingestion Pipeline
=============================================================================
Reads everything in rag/corpus/, chunks it, embeds it, and writes the index.

Usage
-----
    python -m rag.ingest                     # build (or refresh) the index
    python -m rag.ingest --rebuild           # ignore any existing index
    python -m rag.ingest --backend hashing   # force a backend
    python -m rag.ingest --dry-run           # chunk only, report, do not embed

Add a book:
    drop the PDF into rag/corpus/books/  and run the command again.
=============================================================================
"""

import argparse
import json
import logging
import os
import sys
import time
import warnings
from pathlib import Path

# Silence pypdf fontTools warning
logging.getLogger("pypdf").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*fontTools.*")

# Allow `python rag/ingest.py` as well as `python -m rag.ingest`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.concepts import CONCEPTS                       # noqa: E402
from rag.chunker import chunk_document, chunk_question_record, iter_corpus_files  # noqa: E402
from rag.embedder import get_embedder                    # noqa: E402
from rag.embedding_cache import EmbeddingCache            # noqa: E402
from rag.vector_store import VectorStore                 # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
CORPUS_DIR = Path(os.environ.get("EDUGEN_RAG_CORPUS") or (BASE_DIR / "rag" / "corpus"))


def build(corpus_dir=None, index_dir=None, backend=None, rebuild=False, dry_run=False, batch=64):
    corpus_dir = Path(corpus_dir or CORPUS_DIR)
    store = VectorStore(index_dir)

    print("=" * 66)
    print("  EduGen RAG - building knowledge index")
    print("=" * 66)
    print("  Corpus : {}".format(corpus_dir))
    print("  Index  : {}".format(store.index_dir))

    files = list(iter_corpus_files(corpus_dir))
    if not files:
        print("\n  No documents found.")
        print("  Put .md / .txt / .pdf files in {} and run again.".format(corpus_dir))
        return None

    # ── 1. chunk books and notes ────────────────────────────
    t0 = time.time()
    chunks, skipped = [], []
    for path, collection in files:
        try:
            produced = chunk_document(path, collection=collection)
            chunks.extend(produced)
            print("  + {:<46} {:>4} chunks".format(
                str(path.relative_to(corpus_dir))[:46], len(produced)))
        except Exception as exc:                            # noqa: BLE001
            skipped.append((path.name, str(exc)))
            print("  ! {:<46} SKIPPED ({})".format(str(path.name)[:46], exc))

    # ── 1b. chunk question bank (collection: 'question') ────
    q_dir = corpus_dir / "questions" / "raw"
    q_chunks = []
    if q_dir.exists():
        for q_file in sorted(q_dir.glob("*.jsonl")):
            try:
                with open(q_file, "r", encoding="utf-8") as fh:
                    for line_no, line in enumerate(fh, start=1):
                        line_str = line.strip()
                        if not line_str or line_str.startswith("#"):
                            continue
                        rec = json.loads(line_str)
                        q_chunk = chunk_question_record(rec)
                        q_chunks.append(q_chunk)
            except Exception as exc:
                print(f"  ! Error reading {q_file.name}: {exc}")
        chunks.extend(q_chunks)
        print("  + Ingested {:>4} question MCQs into collection 'question'".format(len(q_chunks)))

    if not chunks:
        print("\n  Nothing could be chunked. Check the files and try again.")
        return None

    print("\n  Chunked {} documents + {} questions into {} chunks in {:.1f}s".format(
        len(files) - len(skipped), len(q_chunks), len(chunks), time.time() - t0))

    covered = {t for c in chunks for t in c.get("concept_tags", [])}
    missing = sorted(set(CONCEPTS) - covered)
    print("  Concept coverage: {}/{} tags".format(len(covered), len(CONCEPTS)))
    if missing:
        preview = ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else "")
        print("  Not covered yet : {}".format(preview))

    if dry_run:
        print("\n  Dry run - no embeddings written.")
        return {"chunk_count": len(chunks), "dry_run": True}

    # ── 2. embed ────────────────────────────────────────────
    embedder = get_embedder(backend)
    sig = embedder.signature()
    cache = EmbeddingCache()

    # Seed cache from existing store if cache is fresh and store matches sig
    if store.is_built() and store.meta.get("embedder") == sig:
        cache.seed_from_store(store, sig)

    chunk_hashes = [EmbeddingCache.hash_text(c.get("text", "")) for c in chunks]
    cached_map = cache.get_many(sig, chunk_hashes)
    missing_indices = [i for i, h in enumerate(chunk_hashes) if h not in cached_map]

    reused_count = len(chunks) - len(missing_indices)
    embedded_count = len(missing_indices)
    print("\n  Embedding cache: reused {} / embedded {}".format(reused_count, embedded_count))

    if missing_indices:
        print("  Embedding {} new/changed chunks with {} ...".format(len(missing_indices), sig))
        t1 = time.time()
        new_items = []
        for start in range(0, len(missing_indices), batch):
            batch_indices = missing_indices[start:start + batch]
            batch_texts = [chunks[i]["text"] for i in batch_indices]
            batch_vecs = embedder.embed(batch_texts)
            for idx, vec in zip(batch_indices, batch_vecs):
                h = chunk_hashes[idx]
                v_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                cached_map[h] = v_list
                new_items.append((h, v_list))
            done = min(start + batch, len(missing_indices))
            pct = 100.0 * done / len(missing_indices)
            sys.stdout.write("\r    {:>5}/{} ({:.0f}%)".format(done, len(missing_indices), pct))
            sys.stdout.flush()
        cache.put_many(sig, new_items)
        print("\n  Embedded in {:.1f}s".format(time.time() - t1))

    vectors = [cached_map[h] for h in chunk_hashes]

    # ── 3. save ─────────────────────────────────────────────
    meta = store.save(chunks, vectors, embedder.signature(), extra={
        "corpus_dir": str(corpus_dir),
        "skipped": [{"file": f, "reason": r} for f, r in skipped],
        "concept_coverage": len(covered),
    })

    print("\n" + "=" * 66)
    print("  Index ready")
    print("    chunks     : {}".format(meta["chunk_count"]))
    print("    dimension  : {}".format(meta["dimension"]))
    print("    sources    : {}".format(len(meta["sources"])))
    print("    written to : {}".format(store.index_dir))
    print("=" * 66)
    print("\n  Start the app:  python run.py\n")
    return meta


def main():
    parser = argparse.ArgumentParser(description="Build the EduGen RAG index")
    parser.add_argument("--corpus", default=None, help="corpus directory")
    parser.add_argument("--index", default=None, help="index output directory")
    parser.add_argument("--backend", default=None,
                        choices=["auto", "sentence-transformers", "ollama", "hashing"])
    parser.add_argument("--rebuild", action="store_true", help="discard the existing index")
    parser.add_argument("--dry-run", action="store_true", help="chunk and report only")
    args = parser.parse_args()

    build(corpus_dir=args.corpus, index_dir=args.index, backend=args.backend,
          rebuild=args.rebuild, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
