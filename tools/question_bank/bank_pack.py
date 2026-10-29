"""
=============================================================================
EduGen - Question Bank Source Pack Builder
=============================================================================
Builds a focused "source pack" of textbook chunks for a given concept tag
and batch index. Grounded in textbook page numbers, concept anchors,
and misconception catalog.

Features (Phase 2D-fix-2):
  - CORE vs SUPPORT anchors based on phrase length, non-letter chars, and PDF document frequency (< 3%)
  - ANCHOR_EXTRA for disambiguating key concepts (treated as CORE)
  - No single generic word x3 strong rule
  - HEADING HIT detection (chapter/section headings with CORE phrases)
  - Alias borrowing for under-covered concepts (PACK_ALIASES)
  - Full inspect CLI distinguishing CORE/SUPPORT and marking [HEADING-HIT]

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

GENERIC_SUPPORT_WORDS = {
    "this", "reference", "static", "copy", "try", "close", "block",
    "final", "string", "dynamic", "chaining", "duplicate"
}

ANCHOR_EXTRA = {
    "method-overriding": ["redefine", "redefines", "overrides", "@override"],
    "dynamic-method-dispatch": ["dynamic binding", "late binding", "dynamically bound", "runtime polymorphism"],
    "this-keyword": ["this.", "this(", "this keyword"],
    "constructor-chaining": ["this(", "super(", "constructor chaining", "call another constructor"],
    "static-members": ["static method", "static variable", "static field", "class variable", "static member"],
}

PACK_ALIASES = {
    "data-hiding": ["access-modifiers", "getters-setters"],
    "dynamic-method-dispatch": ["method-overriding", "runtime-polymorphism"],
    "abstract-methods": ["abstract-classes"],
    "custom-exceptions": ["exception-throwing"],
    "javabeans": ["getters-setters"],
}


def get_anchors(concept_tag: str) -> list[str]:
    """
    Returns the list of anchor terms for a concept:
      - Concept keywords from core.concepts.CONCEPTS[concept_tag]["keywords"]
      - Plus meaningful words of its title, lower-cased.
      - Plus ANCHOR_EXTRA entries if defined.
      - Generic words and trivial stop words are never single-word anchors.
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

    # Add canonical multi-word concept phrases
    tag_phrase = concept_tag.replace("-", " ")
    if " " in tag_phrase:
        anchors.add(tag_phrase)
    if "-" in concept_tag:
        anchors.add(concept_tag)

    if concept_tag == "try-catch":
        anchors.update(["catch block", "try block", "catch("])
    elif concept_tag == "exception-chaining":
        anchors.update(["chained exception", "chained exceptions"])

    if concept_tag in ANCHOR_EXTRA:
        for extra in ANCHOR_EXTRA[concept_tag]:
            e = extra.strip().lower()
            if e:
                anchors.add(e)

    return sorted(list(anchors))


def split_anchors(concept_tag: str, anchors: list[str], df: dict, total_chunks: int) -> tuple[set[str], set[str]]:
    """
    Splits anchors into CORE and SUPPORT per (pdf, concept):
      - CORE = any multi-word phrase anchor,
               any token anchor containing a non-letter char (@override, super(, this(), this.),
               any anchor in ANCHOR_EXTRA (tools-side),
               and any single-word anchor whose document frequency in that PDF is < 3%.
      - SUPPORT = every other single-word anchor (e.g. this, reference, static, copy, dynamic, chaining...).
    """
    core = set()
    support = set()
    extras = {e.lower() for e in ANCHOR_EXTRA.get(concept_tag, [])}

    for a in anchors:
        a_low = a.lower()
        if a_low in extras:
            core.add(a_low)
        elif " " in a_low or any(not ch.isalnum() for ch in a_low):
            core.add(a_low)
        elif a_low in GENERIC_SUPPORT_WORDS:
            support.add(a_low)
        else:
            freq = df.get(a_low, 0)
            if total_chunks > 0 and (freq / total_chunks) < 0.03:
                core.add(a_low)
            else:
                support.add(a_low)

    return core, support


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
    keywords = list(meta.get("keywords", []))
    summary = meta.get("summary", "")

    # Include extra keywords if defined
    if concept_tag in ANCHOR_EXTRA:
        keywords.extend(ANCHOR_EXTRA[concept_tag])

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
    """Counts occurrences of each anchor in text_lower, handling punctuation tokens."""
    hits = {}
    for a in anchors:
        if a not in text_lower:
            continue
        if any(not ch.isalnum() for ch in a):
            # Token with symbol like @override, super(, this., this(
            if a[-1].isalnum():
                pattern = r"(?<!\w)" + re.escape(a) + r"(?!\w)"
            else:
                pattern = r"(?<!\w)" + re.escape(a)
        else:
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
        if k[-1].isalnum():
            pattern = r"(?<!\w)" + re.escape(k) + r"(?!\w)"
        else:
            pattern = r"(?<!\w)" + re.escape(k)
        if re.search(pattern, text_lower):
            return True
    return False


def check_heading_hit(text: str, core_anchors: set[str], concept_tag: str) -> bool:
    """
    Returns True if the first 300 characters of a chunk (after stripping leading page numbers /
    running headers) contain a section or chapter heading that includes a CORE phrase.
    """
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        l_str = lines[idx].strip()
        if not l_str:
            idx += 1
            continue
        if re.match(r"^\d+$", l_str):  # standalone page number
            idx += 1
            continue
        break

    head_text = "\n".join(lines[idx:])[:300]
    head_lines = [l.strip() for l in head_text.splitlines() if l.strip()]
    if not head_lines:
        return False

    # Core phrases to check in heading: multi-word phrases, non-letter tokens, or specific core anchors
    core_phrases = [a for a in core_anchors if (" " in a or any(not ch.isalnum() for ch in a))]
    if concept_tag in ANCHOR_EXTRA:
        core_phrases.extend([e.lower() for e in ANCHOR_EXTRA[concept_tag]])

    # Also add specific single-word core anchors that are not generic support words
    for a in core_anchors:
        if a not in GENERIC_SUPPORT_WORDS and len(a) >= 4 and a not in core_phrases:
            core_phrases.append(a)

    # Concept-specific heading phrases from canonical tag and title keywords
    tag_phrase = concept_tag.replace("-", " ")
    if tag_phrase not in core_phrases:
        core_phrases.append(tag_phrase)
    meta = CONCEPTS.get(concept_tag, {})
    for kw in meta.get("keywords", []):
        k = kw.strip().lower()
        if k not in GENERIC_SUPPORT_WORDS and k not in GENERIC_STOPWORDS and len(k) >= 4:
            if k not in core_phrases:
                core_phrases.append(k)

    for l in head_lines[:4]:
        if l.startswith(("//", "/*", "*", "package ", "import ", "@", "public ", "private ", "protected ")):
            continue
        if any(bad in l for bad in ["{", "}", ";", "=", "==", "!=", "->", "()"]):
            continue

        is_heading = False
        if re.match(r"^(?:chapter|section)\s+\d+.*", l, re.IGNORECASE):
            is_heading = True
        elif re.match(r"^\d+(?:\.\d+)+\.?\s+.*", l):
            is_heading = True
        elif re.match(r"^[A-Z][A-Za-z0-9\s,–—:-]{3,50}$", l):
            is_heading = True

        if is_heading:
            l_lower = l.lower()
            if "command-line interface" in l_lower or "user interface" in l_lower:
                continue
            for phrase in core_phrases:
                pat = r"(?<!\w)" + re.escape(phrase) + (r"(?!\w)" if phrase[-1].isalnum() else "")
                if re.search(pat, l_lower):
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
    def __init__(self, items=None, status="OK", candidate_count=0, strong_count=0, borrowed=False, source_concept=None):
        super().__init__(items or [])
        self.status = status
        self.candidate_count = candidate_count
        self.strong_count = strong_count
        self.borrowed = borrowed
        self.source_concept = source_concept


def _extract_candidates_for_concept(index, chunks_map, concept_tag: str):
    """Internal helper to score and filter candidate chunks for a concept."""
    anchors = get_anchors(concept_tag)
    core_anchors, support_anchors = split_anchors(concept_tag, anchors, index.df, index.doc_count)
    query, keywords = build_concept_query(concept_tag)

    raw_scores = dict(index.score(query))
    if not raw_scores:
        return [], core_anchors, support_anchors, 0.0

    candidates = []
    chunk_ids_in_order = sorted(chunks_map.keys())
    id_to_order = {cid: idx for idx, cid in enumerate(chunk_ids_in_order)}

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

        h_hit = check_heading_hit(chunk["text"], core_anchors, concept_tag)

        candidates.append({
            "chunk_id": doc_id,
            "text": chunk["text"],
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "score": score,
            "words": chunk.get("word_count") or len(chunk["text"].split()),
            "hits": hits,
            "hit_list": hit_list,
            "heading_hit": h_hit,
            "chapter_following_hit": False,
            "source_concept": concept_tag,
            "is_borrowed": False,
        })

    if not candidates:
        return [], core_anchors, support_anchors, 0.0

    cand_map = {c["chunk_id"]: c for c in candidates}

    # Propagate heading hit: next 3 chunks of the same chapter with >= 1 CORE anchor are STRONG
    for c in list(candidates):
        if not c["heading_hit"]:
            continue
        c_order = id_to_order.get(c["chunk_id"])
        if c_order is None:
            continue
        for step in (1, 2, 3):
            next_order = c_order + step
            if next_order >= len(chunk_ids_in_order):
                break
            next_cid = chunk_ids_in_order[next_order]
            next_chunk = chunks_map.get(next_cid)
            if not next_chunk:
                continue
            head_100 = next_chunk["text"][:100].lower()
            if re.match(r"^(?:chapter\s+\d+|#+\s+chapter)", head_100):
                break  # new chapter started

            next_t_lower = next_chunk.get("text_lower") or next_chunk["text"].lower()
            next_hits, next_hit_list = check_chunk_anchors(next_t_lower, anchors)
            if any(a in core_anchors for a in next_hit_list):
                if next_cid in cand_map:
                    cand_map[next_cid]["chapter_following_hit"] = True
                else:
                    cand_entry = {
                        "chunk_id": next_cid,
                        "text": next_chunk["text"],
                        "page_start": next_chunk["page_start"],
                        "page_end": next_chunk["page_end"],
                        "score": raw_scores.get(next_cid, 1.0),
                        "words": next_chunk.get("word_count") or len(next_chunk["text"].split()),
                        "hits": next_hits,
                        "hit_list": next_hit_list,
                        "heading_hit": False,
                        "chapter_following_hit": True,
                        "source_concept": concept_tag,
                        "is_borrowed": False,
                    }
                    candidates.append(cand_entry)
                    cand_map[next_cid] = cand_entry

    best_score = max(c["score"] for c in candidates)
    return candidates, core_anchors, support_anchors, best_score


def build_pack(
    pdfshort: str,
    concept_tag: str,
    batch_idx: int = 0,
    max_words: int = 2200,
    work_dir: Path = None,
    allow_borrow: bool = True,
) -> SourcePack:
    """
    Builds a source pack of textbook chunks:
      - Uses weighted query + keyword phrase bonus (+20%).
      - Selects candidate chunks (containing >= 1 anchor).
      - Identifies strong chunks:
          * (>= 1 CORE anchor hit) AND (>= 2 distinct anchors OR CORE anchor appears >= 2 times)
            AND (score >= 40% best score)
          * OR chunk has a HEADING HIT (or is one of next 3 chunks of chapter with >= 1 CORE anchor).
      - If fewer than 2 strong chunks and allow_borrow is True, borrows from PACK_ALIASES.
      - Ranks by: strong chunks first (sorted by score descending), then regular candidates.
      - Batch rotation: batch k starts at rank k*4, wrapping around within strong chunks only.
      - Accumulates chunks up to max_words.
    """
    index, chunks_map = _get_index_and_chunks(pdfshort, work_dir)
    candidates, core_anchors, support_anchors, best_score = _extract_candidates_for_concept(index, chunks_map, concept_tag)

    strong_chunks = []
    regular_chunks = []

    for c in candidates:
        is_strong = False
        if c["heading_hit"] or c["chapter_following_hit"]:
            is_strong = True
        else:
            core_hits = [a for a in c["hit_list"] if a in core_anchors]
            if len(core_hits) >= 1:
                distinct_ok = (len(c["hit_list"]) >= 2) or any(c["hits"][a] >= 2 for a in core_hits)
                score_ok = (c["score"] >= 0.40 * best_score)
                if distinct_ok and score_ok:
                    is_strong = True

        c["is_strong"] = is_strong
        if is_strong:
            strong_chunks.append(c)
        else:
            regular_chunks.append(c)

    # Check if borrowing is needed
    is_borrowed = False
    source_alias = None
    if len(strong_chunks) < 2 and allow_borrow and concept_tag in PACK_ALIASES:
        for alias in PACK_ALIASES[concept_tag]:
            alias_cands, a_core, a_supp, a_best = _extract_candidates_for_concept(index, chunks_map, alias)
            alias_strong = []
            for ac in alias_cands:
                ac_is_strong = False
                if ac["heading_hit"] or ac["chapter_following_hit"]:
                    ac_is_strong = True
                else:
                    ac_core_hits = [a for a in ac["hit_list"] if a in a_core]
                    if len(ac_core_hits) >= 1:
                        dist_ok = (len(ac["hit_list"]) >= 2) or any(ac["hits"][a] >= 2 for a in ac_core_hits)
                        sc_ok = (ac["score"] >= 0.40 * a_best)
                        if dist_ok and sc_ok:
                            ac_is_strong = True
                ac["is_strong"] = ac_is_strong
                if ac_is_strong:
                    ac["source_concept"] = alias
                    ac["is_borrowed"] = True
                    alias_strong.append(ac)

            if len(alias_strong) >= 2:
                strong_chunks.extend(alias_strong)
                is_borrowed = True
                source_alias = alias
                break

    if len(candidates) < 3 and not strong_chunks:
        return SourcePack([], status="NO_MATERIAL", candidate_count=len(candidates), strong_count=0)

    strong_chunks.sort(key=lambda x: x["score"], reverse=True)
    regular_chunks.sort(key=lambda x: x["score"], reverse=True)

    # Batch rotation: wrap around within STRONG chunks only (if >= 3 strong chunks)
    if len(strong_chunks) >= 3:
        n_strong = len(strong_chunks)
        start_idx = (batch_idx * 4) % n_strong
        ordered_pool = strong_chunks[start_idx:] + strong_chunks[:start_idx] + regular_chunks
    elif strong_chunks:
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

        c_hits = c.get("hit_list", [])
        c_core = [a for a in c_hits if a in core_anchors]
        c_supp = [a for a in c_hits if a in support_anchors]

        pack_chunks.append({
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            "page_start": c["page_start"],
            "page_end": c["page_end"],
            "score": round(c["score"], 3),
            "words": w_count,
            "is_strong": c["is_strong"],
            "heading_hit": c.get("heading_hit", False),
            "chapter_following_hit": c.get("chapter_following_hit", False),
            "anchors_hit": c_hits,
            "core_anchors_hit": c_core,
            "support_anchors_hit": c_supp,
            "num_anchors": len(c_hits),
            "source_concept": c.get("source_concept", concept_tag),
            "is_borrowed": c.get("is_borrowed", False),
        })
        seen_ids.add(c["chunk_id"])
        total_words += w_count

        if total_words >= max_words:
            break

    return SourcePack(
        pack_chunks,
        status="OK" if not is_borrowed else "BORROWED",
        candidate_count=len(candidates),
        strong_count=len(strong_chunks),
        borrowed=is_borrowed,
        source_concept=source_alias or concept_tag,
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
    if pack.borrowed:
        print(f"  [BORROWED] Material borrowed from related concept: {pack.source_concept}")
    print(f"  Pack Chunks: {len(pack)} | Total words: {total_words} / {args.max_words}")
    print(f"  Page ranges: {page_ranges}")
    print("=" * 70)

    for i, c in enumerate(pack, 1):
        badges = []
        if c.get("is_strong"):
            badges.append("[STRONG]")
        else:
            badges.append("[CANDIDATE]")
        if c.get("heading_hit"):
            badges.append("[HEADING-HIT]")
        elif c.get("chapter_following_hit"):
            badges.append("[CHAPTER-HIT]")
        if c.get("is_borrowed"):
            badges.append(f"[BORROWED from {c.get('source_concept')}]")

        badge_str = " ".join(badges)
        anchors_hit = c.get("anchors_hit", [])
        core_hits = c.get("core_anchors_hit", [])
        supp_hits = c.get("support_anchors_hit", [])
        num_anchors = len(anchors_hit)

        if args.inspect:
            snip = c["text"][:250].replace("\n", " ")
            print(f"\nChunk {i}: pp.{c['page_start']}-{c['page_end']} {badge_str}")
            print(f"  Source Concept: {c.get('source_concept')}")
            print(f"  Distinct Anchors ({num_anchors}):")
            print(f"    CORE ({len(core_hits)}): {core_hits}")
            print(f"    SUPPORT ({len(supp_hits)}): {supp_hits}")
            print(f"  Score: {c['score']} | Words: {c['words']}")
            print(f"  Text: {snip}...")
        else:
            print(f"\n[Chunk {i}] ID: {c['chunk_id']} | pp.{c['page_start']}-{c['page_end']} {badge_str} | Score: {c['score']} | Words: {c['words']}")
            print(f"  Anchors ({num_anchors}): CORE={core_hits} SUPPORT={supp_hits}")
            print("-" * 70)
            if args.full_text:
                print(c["text"])
            else:
                snippet = c["text"][:300].replace("\n", " ")
                print(f"{snippet}...")


if __name__ == "__main__":
    main()
