"""
=============================================================================
EduGen - Question Bank Source Pack Builder
=============================================================================
Builds a focused "source pack" of textbook chunks for a given concept tag
and batch index. Grounded in textbook page numbers, concept anchors,
and misconception catalog.

Usage (CLI):
    python tools/question_bank/bank_pack.py --pdf javanotes9 --concept method-overriding --batch 0
    python tools/question_bank/bank_pack.py --pdf javanotes9 --concept method-overriding --batch 0 --inspect
=============================================================================
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.concepts import CONCEPTS
from core.misconceptions import misconceptions_for
from tools.question_bank.bank_prepare import BM25Index

# In-memory caches to speed up batch runs
_INDEX_CACHE = {}
_CHUNKS_CACHE = {}

GENERIC_STOPWORDS = {
    "class", "classes", "object", "objects", "method", "methods", "java", "variable",
    "variables", "code", "program", "value", "type", "use", "data", "field",
    "fields", "instance", "new", "public", "private", "void", "return"
}

ENGLISH_STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "of", "to", "for", "with", "from",
    "by", "at", "on", "as", "is", "are", "was", "were", "be", "been", "that"
}


def get_anchors(concept_tag: str) -> list[str]:
    """
    Returns the list of anchor terms for a concept:
      - Concept keywords from core.concepts.CONCEPTS[concept_tag]["keywords"]
      - Plus meaningful words of its title, lower-cased.
      - Generic words and trivial stop words are NEVER anchors on their own.
      - Multi-word phrases that contain them are preserved (e.g. 'abstract class').
    """
    meta = CONCEPTS.get(concept_tag, {})
    keywords = meta.get("keywords", [])
    title = meta.get("title", "")
    anchors = set()

    for kw in keywords:
        k = kw.strip().lower()
        if not k:
            continue
        if " " not in k and (k in GENERIC_STOPWORDS or k in ENGLISH_STOPWORDS):
            continue
        anchors.add(k)

    for word in re.findall(r"[a-zA-Z0-9_]+", title.lower()):
        if word in GENERIC_STOPWORDS or word in ENGLISH_STOPWORDS or len(word) <= 2:
            continue
        anchors.add(word)

    return sorted(list(anchors))


def build_concept_query(concept_tag: str) -> tuple[str, list[str]]:
    """
    Weighted query:
      - concept keywords x3
      - title words x3
      - summary x1
      - misconception TITLES and FACETS x1
      - NO misconception wrong_belief sentences.
    Returns (query_string, keywords_list).
    """
    meta = CONCEPTS.get(concept_tag, {})
    title = meta.get("title", "")
    keywords = meta.get("keywords", [])
    summary = meta.get("summary", "")

    parts = []
    # concept keywords x3
    for _ in range(3):
        parts.extend(keywords)

    # title words x3
    title_words = [w for w in title.split() if w.strip()]
    for _ in range(3):
        parts.extend(title_words)

    # summary x1
    if summary:
        parts.append(summary)

    # misconception TITLES and FACETS x1 (NO wrong_belief)
    for m in misconceptions_for(concept_tag):
        t = m.get("title")
        f = m.get("facet")
        if t:
            parts.append(t)
        if f:
            parts.append(f)

    return " ".join(parts), keywords


def check_chunk_anchors(text_lower: str, anchors: list[str]) -> tuple[dict[str, int], list[str]]:
    """Counts occurrences of each anchor in text_lower."""
    hits = {}
    for a in anchors:
        if a not in text_lower:
            continue
        pattern = r"(?<!\w)" + re.escape(a) + r"(?!\w)"
        cnt = len(re.findall(pattern, text_lower))
        if cnt > 0:
            hits[a] = cnt
    return hits, sorted(list(hits.keys()))


def has_exact_keyword_phrase(text_lower: str, keywords: list[str]) -> bool:
    """Returns True if any keyword from keywords appears in text_lower."""
    for kw in keywords:
        k = kw.strip().lower()
        if not k or k not in text_lower:
            continue
        pattern = r"(?<!\w)" + re.escape(k) + r"(?!\w)"
        if re.search(pattern, text_lower):
            return True
    return False


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
                    item["text_lower"] = item["text"].lower()
                    chunks_map[item["chunk_id"]] = item
        _CHUNKS_CACHE[pdfshort] = chunks_map

    return _INDEX_CACHE[pdfshort], _CHUNKS_CACHE[pdfshort]


class SourcePack(list):
    """Custom list representing a source pack, with metadata attributes."""
    def __init__(self, items=None, status="OK", candidate_count=0, strong_count=0):
        super().__init__(items or [])
        self.status = status
        self.candidate_count = candidate_count
        self.strong_count = strong_count


def build_pack(
    pdfshort: str,
    concept_tag: str,
    batch_idx: int = 0,
    max_words: int = 2200,
    work_dir: Path = None,
) -> SourcePack:
    """
    Builds a source pack of textbook chunks:
      - Uses weighted query + keyword phrase bonus (+20%).
      - Selects candidate chunks (containing >= 1 anchor).
      - Identifies strong chunks (>= 2 distinct anchors OR 1 anchor >= 3 times, AND score >= 40% best score).
      - If fewer than 3 candidate chunks exist: returns empty pack marked NO_MATERIAL.
      - Ranks by: strong chunks first (sorted by score descending), then regular candidates.
      - Batch rotation: batch k starts at rank k*4, wrapping around within strong chunks only.
      - Accumulates chunks up to max_words.
    """
    index, chunks_map = _get_index_and_chunks(pdfshort, work_dir)
    anchors = get_anchors(concept_tag)
    query, keywords = build_concept_query(concept_tag)

    raw_scores = dict(index.score(query))
    if not raw_scores:
        return SourcePack([], status="NO_MATERIAL", candidate_count=0, strong_count=0)

    candidates = []
    for doc_id, base_score in raw_scores.items():
        if base_score <= 0:
            continue
        chunk = chunks_map.get(doc_id)
        if not chunk:
            continue

        t_lower = chunk.get("text_lower") or chunk["text"].lower()
        hits, hit_list = check_chunk_anchors(t_lower, anchors)
        if not hit_list:
            continue

        score = base_score
        if has_exact_keyword_phrase(t_lower, keywords):
            score *= 1.20

        candidates.append({
            "chunk_id": doc_id,
            "text": chunk["text"],
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "score": score,
            "words": chunk.get("word_count") or len(chunk["text"].split()),
            "hits": hits,
            "hit_list": hit_list,
        })

    if len(candidates) < 3:
        return SourcePack([], status="NO_MATERIAL", candidate_count=len(candidates), strong_count=0)

    best_score = max(c["score"] for c in candidates)
    strong_chunks = []
    regular_chunks = []

    for c in candidates:
        is_strong = (len(c["hit_list"]) >= 2 or any(cnt >= 3 for cnt in c["hits"].values())) and (c["score"] >= 0.40 * best_score)
        c["is_strong"] = is_strong
        if is_strong:
            strong_chunks.append(c)
        else:
            regular_chunks.append(c)

    strong_chunks.sort(key=lambda x: x["score"], reverse=True)
    regular_chunks.sort(key=lambda x: x["score"], reverse=True)

    # Batch rotation: wrap around within STRONG chunks only (if >= 3 strong chunks)
    if len(strong_chunks) >= 3:
        n_strong = len(strong_chunks)
        start_idx = (batch_idx * 4) % n_strong
        ordered_pool = strong_chunks[start_idx:] + strong_chunks[:start_idx] + regular_chunks
    elif strong_chunks:
        # Fallback with few strong chunks
        all_pool = strong_chunks + regular_chunks
        start_idx = (batch_idx * 4) % len(all_pool)
        ordered_pool = all_pool[start_idx:] + all_pool[:start_idx]
    else:
        start_idx = (batch_idx * 4) % len(regular_chunks)
        ordered_pool = regular_chunks[start_idx:] + regular_chunks[:start_idx]

    pack_chunks = []
    total_words = 0
    seen_ids = set()

    for c in ordered_pool:
        if c["chunk_id"] in seen_ids:
            continue

        w_count = c["words"]
        if pack_chunks and (total_words + w_count > max_words):
            break

        pack_chunks.append({
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            "page_start": c["page_start"],
            "page_end": c["page_end"],
            "score": round(c["score"], 3),
            "words": w_count,
            "is_strong": c["is_strong"],
            "anchors_hit": c["hit_list"],
            "num_anchors": len(c["hit_list"]),
        })
        seen_ids.add(c["chunk_id"])
        total_words += w_count

        if total_words >= max_words:
            break

    return SourcePack(
        pack_chunks,
        status="OK",
        candidate_count=len(candidates),
        strong_count=len(strong_chunks),
    )


def main():
    parser = argparse.ArgumentParser(description="Extract a source pack of textbook chunks for question generation.")
    parser.add_argument("--pdf", required=True, help="Short name of the PDF (e.g. javanotes9).")
    parser.add_argument("--concept", required=True, help="Canonical concept tag (e.g. method-overriding).")
    parser.add_argument("--batch", type=int, default=0, help="Batch index (rotates ranking by batch*4).")
    parser.add_argument("--max-words", type=int, default=2200, help="Maximum word count per pack (default: 2200).")
    parser.add_argument("--full-text", action="store_true", help="Print full text of chunks.")
    parser.add_argument("--inspect", action="store_true", help="Inspect chunk details: page range, distinct anchors, hits, first 250 chars.")
    args = parser.parse_args()

    if args.concept not in CONCEPTS:
        print(f"Warning: '{args.concept}' is not in core.concepts.CONCEPTS.")

    pack = build_pack(args.pdf, args.concept, batch_idx=args.batch, max_words=args.max_words)

    if pack.status == "NO_MATERIAL" or len(pack) == 0:
        print(f"\n[{args.pdf} | {args.concept}] NO_MATERIAL (candidates: {pack.candidate_count})")
        return

    total_words = sum(c["words"] for c in pack)
    page_ranges = ", ".join(f"pp.{c['page_start']}-{c['page_end']}" for c in pack)

    print("=" * 70)
    print(f"  Source Pack: {args.concept} | PDF: {args.pdf} | Batch: {args.batch}")
    print(f"  Status: {pack.status} | Strong Chunks: {pack.strong_count} | Candidates: {pack.candidate_count}")
    print(f"  Pack Chunks: {len(pack)} | Total words: {total_words} / {args.max_words}")
    print(f"  Page ranges: {page_ranges}")
    print("=" * 70)

    for i, c in enumerate(pack, 1):
        strong_badge = "[STRONG]" if c.get("is_strong") else "[CANDIDATE]"
        anchors_hit = c.get("anchors_hit", [])
        num_anchors = len(anchors_hit)

        if args.inspect:
            snip = c["text"][:250].replace("\n", " ")
            print(f"\nChunk {i}: pp.{c['page_start']}-{c['page_end']} {strong_badge}")
            print(f"  Distinct Anchors: {num_anchors} | Hit: {anchors_hit}")
            print(f"  Score: {c['score']} | Words: {c['words']}")
            print(f"  Text: {snip}...")
        else:
            print(f"\n[Chunk {i}] ID: {c['chunk_id']} | pp.{c['page_start']}-{c['page_end']} {strong_badge} | Score: {c['score']} | Words: {c['words']}")
            print(f"  Anchors ({num_anchors}): {anchors_hit}")
            print("-" * 70)
            if args.full_text:
                print(c["text"])
            else:
                snippet = c["text"][:300].replace("\n", " ")
                print(f"{snippet}...")


if __name__ == "__main__":
    main()
