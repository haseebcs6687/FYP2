"""
=============================================================================
EduGen - Question Bank Source Pack Builder
=============================================================================
Builds a focused "source pack" of textbook chunks for a given concept tag
and batch index. Grounded in textbook page numbers, concept anchors,
and misconception catalog.

Phase 2D-fix-5 Updates:
  - PHRASE_CORE/WORD_CORE split: a chunk is STRONG only if it has >= 1 PHRASE_CORE hit
    (or an UNAMBIGUOUS single-word hit). WORD_CORE alone = CANDIDATE.
  - NO_MATERIAL returned if < 2 STRONG/HINT chunks in a PDF (candidates alone never form a pack).
  - Borrowing enforced in build_pack itself: borrowed chunk kept only if target PHRASE_CORE >= 1.
  - Page hints force-include ALL overlapping chunks (no anchor needed, up to 6), ordered by score.
  - 'this.' demoted to SUPPORT (bare English word); this(, this keyword, current object kept as PHRASE_CORE.
  - data-hiding ANCHOR_EXTRA extended with phrase anchors.

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
_PAGE_HINTS_CACHE = None

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

FILLER_WORDS = {
    "basics", "keyword", "definition", "introduction", "overview", "concepts", "members"
}

LOOSE_WORDS = {
    "contract", "cleanup", "invariant", "resource", "resources", "basics", "constant", "clone"
}

# Single words that are unambiguous enough to count as PHRASE_CORE even without a phrase partner.
# These are rare, domain-specific enough that they cannot be English noise.
UNAMBIGUOUS_SINGLE_WORDS = {
    "immutable", "autocloseable", "getter", "setter", "getters", "setters",
    "accessor", "mutator", "implements", "dispatch", "shadowing", "polymorphic",
}

# 'this.' in English prose is a determiner + period - demote to SUPPORT.
# Keep the other this-keyword tokens as PHRASE_CORE.
_THIS_DOT_SUPPORT = {"this."}

ANCHOR_EXTRA = {
    "method-overriding": ["redefine", "redefines", "overrides", "@override"],
    "dynamic-method-dispatch": [
        "dispatch", "dynamic binding", "late binding", "dynamically bound", "runtime polymorphism",
        "overridden method", "polymorphic call"
    ],
    "this-keyword": ["this.", "this(", "this keyword", "current object", "implicit parameter", "shadowing"],
    "constructor-chaining": ["this(", "super(", "constructor chaining", "call another constructor"],
    "static-members": ["static method", "static variable", "static field", "class variable", "static member"],
    "interface-basics": ["implements", "interface"],
    "finally-block": ["finally block", "finally clause"],
    "try-with-resources": ["autocloseable", "try-with-resources", "suppressed exception", "close()"],
    "copy-constructor": ["copy constructor", "clone()", "deep copy", "shallow copy"],
    "immutability": ["immutable class", "immutable object"],
    "getters-setters": ["getter", "setter", "getters", "setters", "accessor", "mutator"],
    "class-definition": [
        "class definition", "defining a class", "class declaration", "declare a class",
        "instance variables", "instance methods", "class body", "blueprint", "public class"
    ],
    "data-hiding": [
        "data hiding", "information hiding", "private field", "private variable", "encapsulation"
    ],
}

PACK_ALIASES = {}

PAGE_HINTS_FILE = BASE_DIR / "tools" / "question_bank" / "page_hints.json"

_TOC_CACHE = {}

TOC_EXCLUDED_WORDS = {
    "class", "classes", "object", "objects", "method", "methods", "java", "variable",
    "variables", "code", "program", "value", "values", "type", "types", "use", "using",
    "data", "field", "fields", "instance", "instances", "new", "public", "private",
    "void", "return", "basics", "keyword", "keywords", "definition", "introduction",
    "overview", "concepts", "members", "create", "creating", "example", "examples",
    "simple", "first", "chapter", "section", "part", "advanced", "guide",
    "collection", "collections", "reference", "references", "what", "with", "from",
    "this", "static", "copy", "try", "close", "block", "final", "string", "dynamic",
    "chaining", "duplicate", "multiple", "contract", "cleanup", "invariant", "resource",
    "resources", "constant", "clone", "about", "more", "other", "another"
}

FRONT_BACK_RE = re.compile(
    r"^(?:glossary|index|table of contents|contents|preface|acknowledg|credits|about the author|bibliography|references)",
    re.IGNORECASE,
)


def get_toc(pdfshort: str, work_dir: Path = None) -> list[dict]:
    """Loads extracted outline/TOC entries for a PDF from data/bank_work/<pdfshort>/toc.json."""
    global _TOC_CACHE
    if work_dir is None:
        work_dir = BASE_DIR / "data" / "bank_work"
    else:
        work_dir = Path(work_dir)
    if pdfshort in _TOC_CACHE:
        return _TOC_CACHE[pdfshort]
    toc_file = work_dir / pdfshort / "toc.json"
    if not toc_file.exists():
        _TOC_CACHE[pdfshort] = []
        return []
    try:
        with open(toc_file, "r", encoding="utf-8") as f:
            entries = json.load(f)
            _TOC_CACHE[pdfshort] = entries
            return entries
    except Exception:
        _TOC_CACHE[pdfshort] = []
        return []


SUB_CONCEPT_EXCLUDED_STEMS = {
    "copy-constructor": {"constru"},
    "constructor-chaining": {"constru"},
    "constructor-overloading": {"constru"},
    "default-constructor": {"constru"},
    "multiple-inheritance": {"inherit"},
    "custom-exceptions": {"excepti"},
    "exception-chaining": {"excepti"},
    "exception-throwing": {"excepti"},
    "null-pointer-exception": {"excepti"},
}


def get_concept_stems(concept_tag: str) -> set[str]:
    """Extracts non-generic stems (first 6-7 letters) from concept title and tag."""
    meta = CONCEPTS.get(concept_tag, {})
    title = meta.get("title", "")
    words = re.findall(r"[a-z0-9]+", (title + " " + concept_tag).lower())
    stems = set()
    for w in words:
        if w in TOC_EXCLUDED_WORDS or len(w) <= 3:
            continue
        if w.startswith("instantiat"):
            stems.add("instanti")
        elif len(w) >= 7:
            stems.add(w[:7])
        else:
            stems.add(w[:6])
    if concept_tag in SUB_CONCEPT_EXCLUDED_STEMS:
        stems -= SUB_CONCEPT_EXCLUDED_STEMS[concept_tag]
    return stems


def match_toc_sections(
    pdfshort: str,
    concept_tag: str,
    work_dir: Path = None,
    toc_entries: list[dict] = None,
) -> list[dict]:
    """
    Phase 2D-fix-6 TOC matching:
      - Section matches concept if title contains a PHRASE_CORE anchor (>=4 chars)
        or a title/tag word by stem (first 6-7 letters), excluding generic words.
      - Skips front/back matter.
      - Skips sections longer than 25 pages.
      - Prefers level 2/3 sections over level-1 chapters.
    """
    if toc_entries is None:
        toc_entries = get_toc(pdfshort, work_dir)
    if not toc_entries:
        return []

    anchors = get_anchors(concept_tag)
    phrase_core, _, _ = split_anchors(concept_tag, anchors, {}, 0)
    stems = get_concept_stems(concept_tag)

    matches = []
    for entry in toc_entries:
        title = entry.get("title", "").strip()
        if FRONT_BACK_RE.search(title):
            continue
        page_len = entry.get("page_end", 0) - entry.get("page_start", 0) + 1
        if page_len > 25:
            continue

        t_low = title.lower()
        hit = False
        # 1. Check PHRASE_CORE anchors (multi-word phrases or unambiguous symbols/tokens)
        for phrase in phrase_core:
            if len(phrase) >= 4:
                pat = r"(?<!\w)" + re.escape(phrase) + (r"(?!\w)" if phrase[-1].isalnum() else "")
                if re.search(pat, t_low):
                    hit = True
                    break

        # 2. Check title/tag word stem (6-7 letters)
        if not hit:
            t_words = re.findall(r"[a-z0-9]+", t_low)
            for tw in t_words:
                for s in stems:
                    if tw.startswith(s):
                        hit = True
                        break
                if hit:
                    break

        if hit:
            matches.append(entry)

    # Prefer level 2/3 sections over level-1 chapters
    if any(m.get("level", 1) >= 2 for m in matches):
        matches = [m for m in matches if m.get("level", 1) >= 2]

    return matches


_VERIFIED_HINTS_CACHE = {}


def get_page_hints(
    pdfshort: str,
    concept_tag: str,
    hints_path: Path = None,
    work_dir: Path = None,
) -> list[list[int]]:
    """Loads verified human page hints for a (pdf, concept) from page_hints.json."""
    global _VERIFIED_HINTS_CACHE
    p_file = Path(hints_path or PAGE_HINTS_FILE)
    w_dir = Path(work_dir or BASE_DIR / "data" / "bank_work")
    cache_key = (str(p_file), str(w_dir))
    if cache_key not in _VERIFIED_HINTS_CACHE or hints_path is not None:
        try:
            from tools.question_bank.verify_hints import verify_hints_data
            verified, _, _ = verify_hints_data(p_file, w_dir)
            if hints_path is None:
                _VERIFIED_HINTS_CACHE[cache_key] = verified
            else:
                return verified.get(pdfshort, {}).get(concept_tag, [])
        except Exception:
            if hints_path is None:
                _VERIFIED_HINTS_CACHE[cache_key] = {}
            else:
                return []
    return _VERIFIED_HINTS_CACHE[cache_key].get(pdfshort, {}).get(concept_tag, [])


def get_effective_ranges(
    pdfshort: str,
    concept_tag: str,
    work_dir: Path = None,
    hints_file: Path = None,
) -> tuple[list[list[int]], str]:
    """
    Phase 2D-fix-7: The ONLY human-driven page source is tools/question_bank/page_hints.json.
    TOC matches never make a chunk STRONG and are for review suggestions only.
    """
    ranges = get_page_hints(pdfshort, concept_tag, hints_file, work_dir)
    if ranges:
        return ranges, "HINT"
    return [], "NONE"



def get_anchors(concept_tag: str) -> list[str]:
    """
    Returns the list of anchor terms for a concept:
      - Concept keywords from core.concepts.CONCEPTS[concept_tag]["keywords"]
      - Plus meaningful words of its title, lower-cased.
      - Plus ANCHOR_EXTRA entries.
      - Canonical concept tag phrases (e.g. 'interface basics', 'try catch').
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

    if concept_tag in ANCHOR_EXTRA:
        for extra in ANCHOR_EXTRA[concept_tag]:
            e = extra.strip().lower()
            if e:
                anchors.add(e)

    return sorted(list(anchors))


def split_anchors(
    concept_tag: str, anchors: list[str], df: dict, total_chunks: int
) -> tuple[set[str], set[str], set[str]]:
    """
    Phase 2D-fix-5: Splits anchors into PHRASE_CORE, WORD_CORE, and SUPPORT.

    PHRASE_CORE (can make a chunk STRONG on their own):
      - Multi-word phrases (2+ words)
      - Symbol tokens (@override, super(, this(, close(), etc.) — but NOT 'this.' (English noise)
      - Any entry in ANCHOR_EXTRA[concept_tag]
      - Any single word in UNAMBIGUOUS_SINGLE_WORDS

    WORD_CORE (in CORE but cannot make a chunk STRONG alone):
      - Single words from concept TITLE or TAG that are not in GENERIC_SUPPORT_WORDS / FILLER_WORDS
        (stem: first 7 letters)
      - Single words not in title/tag with df < 3%, not in LOOSE_WORDS
      - Exception: 'constructors' stem-matches 'constructor' but constructors alone is never PHRASE_CORE.

    SUPPORT:
      - Everything else.
    """
    phrase_core = set()
    word_core = set()
    support = set()
    extras = {e.lower() for e in ANCHOR_EXTRA.get(concept_tag, [])}

    meta = CONCEPTS.get(concept_tag, {})
    title = meta.get("title", "")
    title_tag_words = set(re.findall(r"[a-z0-9]+", (title + " " + concept_tag).lower()))
    valid_title_tag_words = {
        w for w in title_tag_words
        if w not in GENERIC_SUPPORT_WORDS and w not in FILLER_WORDS
    }

    for a in anchors:
        a_low = a.lower()

        # Rule 0: 'this.' is English noise — always SUPPORT
        if a_low in _THIS_DOT_SUPPORT:
            support.add(a_low)
            continue

        # Rule 1: ANCHOR_EXTRA entries are PHRASE_CORE
        if a_low in extras:
            phrase_core.add(a_low)
            continue

        # Rule 2: Multi-word phrases are PHRASE_CORE
        if " " in a_low:
            phrase_core.add(a_low)
            continue

        # Rule 3: Symbol tokens (contain non-alnum chars, except 'this.') are PHRASE_CORE
        if any(not ch.isalnum() for ch in a_low):
            phrase_core.add(a_low)
            continue

        # Rule 4: Unambiguous single words are PHRASE_CORE
        if a_low in UNAMBIGUOUS_SINGLE_WORDS:
            phrase_core.add(a_low)
            continue

        # Rule 5: Single-word anchor in TITLE or TAG (stem matching first 7 letters)
        is_title_or_tag = False
        if a_low not in GENERIC_SUPPORT_WORDS and a_low not in FILLER_WORDS:
            for w in valid_title_tag_words:
                if a_low == w:
                    is_title_or_tag = True
                    break
                if len(a_low) >= 7 and len(w) >= 7 and a_low[:7] == w[:7]:
                    is_title_or_tag = True
                    break

        if is_title_or_tag:
            word_core.add(a_low)
        else:
            # Rule 6: Not in title/tag: check LOOSE_WORDS and DF < 3%
            if a_low in GENERIC_SUPPORT_WORDS or a_low in FILLER_WORDS or a_low in LOOSE_WORDS:
                support.add(a_low)
            else:
                freq = df.get(a_low, 0)
                if total_chunks > 0 and (freq / total_chunks) < 0.03:
                    word_core.add(a_low)
                else:
                    support.add(a_low)

    return phrase_core, word_core, support


def all_core(phrase_core: set, word_core: set) -> set:
    """Convenience: union of PHRASE_CORE and WORD_CORE for anchor-hit checks."""
    return phrase_core | word_core


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

    if concept_tag in ANCHOR_EXTRA:
        keywords.extend(ANCHOR_EXTRA[concept_tag])

    parts = []
    for _ in range(3):
        parts.extend(keywords)

    title_words = [w for w in title.split() if w.strip()]
    for _ in range(3):
        parts.extend(title_words)

    if summary:
        parts.append(summary)

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


def check_heading_hit(text: str, core_anchors: set[str], concept_tag: str) -> str | None:
    """
    Returns the heading line if the first 300 characters of a chunk (after stripping leading page numbers /
    running headers) contain a section or chapter heading that includes a CORE phrase. Otherwise None.
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
        return None

    core_phrases = [
        a for a in core_anchors
        if a not in _THIS_DOT_SUPPORT and (" " in a or any(not ch.isalnum() for ch in a) or a in UNAMBIGUOUS_SINGLE_WORDS)
    ]
    if concept_tag in ANCHOR_EXTRA:
        for extra in ANCHOR_EXTRA[concept_tag]:
            e = extra.strip().lower()
            if e not in _THIS_DOT_SUPPORT and (" " in e or any(not ch.isalnum() for ch in e) or e in UNAMBIGUOUS_SINGLE_WORDS):
                if e not in core_phrases:
                    core_phrases.append(e)

    tag_phrase = concept_tag.replace("-", " ")
    if " " in tag_phrase and tag_phrase not in core_phrases:
        core_phrases.append(tag_phrase)

    # Fall back to single-word core anchors ONLY if the concept has no phrase/unambiguous anchors
    if not core_phrases:
        for a in core_anchors:
            if a not in GENERIC_SUPPORT_WORDS and a not in FILLER_WORDS and len(a) >= 4 and a not in core_phrases:
                core_phrases.append(a)

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
                    return l

    return None


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
    """Internal helper to score and filter candidate chunks for a concept.
    Returns: (candidates, phrase_core, word_core, support_anchors, best_score, anchors, chunk_ids_in_order)
    """
    anchors = get_anchors(concept_tag)
    phrase_core, word_core, support_anchors = split_anchors(concept_tag, anchors, index.df, index.doc_count)
    core_anchors = all_core(phrase_core, word_core)
    query, keywords = build_concept_query(concept_tag)

    raw_scores = dict(index.score(query))
    if not raw_scores:
        return [], phrase_core, word_core, support_anchors, 0.0, anchors

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

        h_hit_text = check_heading_hit(chunk["text"], phrase_core, concept_tag)
        h_hit = bool(h_hit_text)

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
            "heading_text": h_hit_text or "",
            "chapter_following_hit": False,
            "is_hint": False,
            "source_concept": concept_tag,
            "is_borrowed": False,
        })

    if not candidates:
        return [], phrase_core, word_core, support_anchors, 0.0, anchors

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
            effective_pc = phrase_core if phrase_core else core_anchors
            if any(a in effective_pc for a in next_hit_list):
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
                        "is_hint": False,
                        "source_concept": concept_tag,
                        "is_borrowed": False,
                    }
                    candidates.append(cand_entry)
                    cand_map[next_cid] = cand_entry

    best_score = max(c["score"] for c in candidates)
    return candidates, phrase_core, word_core, support_anchors, best_score, anchors


def _is_chunk_strong(c: dict, phrase_core: set, word_core: set, best_score: float) -> bool:
    """Phase 2D-fix-5: A chunk is STRONG only if it has >= 1 PHRASE_CORE hit
    (or UNAMBIGUOUS single-word hit). WORD_CORE alone => CANDIDATE only.
    HEADING_HIT or CHAPTER_FOLLOWING_HIT also makes it STRONG."""
    if c.get("is_hint") or c.get("heading_hit") or c.get("chapter_following_hit"):
        return True
    phrase_hits = [a for a in c.get("hit_list", []) if a in phrase_core]
    if len(phrase_hits) >= 1:
        all_hits = c.get("hit_list", [])
        distinct_ok = (len(all_hits) >= 2) or any(c.get("hits", {}).get(a, 0) >= 2 for a in phrase_hits)
        score_ok = (c["score"] >= 0.40 * best_score)
        if distinct_ok and score_ok:
            return True
    return False



def build_pack(
    pdfshort: str,
    concept_tag: str,
    batch_idx: int = 0,
    max_words: int = 2200,
    work_dir: Path = None,
    allow_borrow: bool = True,
    hints_file: Path = None,
) -> SourcePack:
    """
    Builds a source pack of textbook chunks (Phase 2D-fix-7 rules):
      - Curated human page hints (tools/question_bank/page_hints.json) are the ONLY page source.
      - Chunks overlapping a verified hinted range are STRONG and [HINT], ordered by PAGE ORDER.
      - Batch rotation: batch k starts at chunk 4k and wraps inside the hinted chunks.
      - Concepts WITHOUT a hint entry use fix-5 anchor logic (PHRASE_CORE, NO_MATERIAL rules).
      - Returns NO_MATERIAL if < 2 STRONG chunks.
      - Borrowing disabled completely (PACK_ALIASES = {}).
    """
    index, chunks_map = _get_index_and_chunks(pdfshort, work_dir)
    candidates, phrase_core, word_core, support_anchors, best_score, anchors = _extract_candidates_for_concept(
        index, chunks_map, concept_tag
    )
    core_anchors = all_core(phrase_core, word_core)

    # --- Step 1: Collect chunks inside verified human page hint ranges ---
    eff_ranges, range_source = get_effective_ranges(pdfshort, concept_tag, work_dir, hints_file)
    hint_pool: list[dict] = []
    hint_cids: set[str] = set()
    cand_map_by_id = {c["chunk_id"]: c for c in candidates}

    if eff_ranges:
        for cid, chunk in chunks_map.items():
            c_start = chunk["page_start"]
            c_end = chunk["page_end"]
            if any(max(c_start, r[0]) <= min(c_end, r[1]) for r in eff_ranges):
                if cid in cand_map_by_id:
                    c = cand_map_by_id[cid]
                else:
                    t_lower = chunk.get("text_lower") or chunk["text"].lower()
                    h_hits, h_hit_list = check_chunk_anchors(t_lower, anchors) if anchors else ({}, [])
                    c = {
                        "chunk_id": cid,
                        "text": chunk["text"],
                        "page_start": c_start,
                        "page_end": c_end,
                        "score": 1.0,
                        "words": chunk.get("word_count") or len(chunk["text"].split()),
                        "hits": h_hits,
                        "hit_list": h_hit_list,
                        "heading_hit": False,
                        "heading_text": "",
                        "chapter_following_hit": False,
                        "source_concept": concept_tag,
                        "is_borrowed": False,
                    }
                c["is_strong"] = True
                c["is_hint"] = True
                c["is_toc"] = False
                hint_cids.add(cid)
                hint_pool.append(c)

        # Hint chunks are strictly ordered by PAGE ORDER
        hint_pool.sort(key=lambda x: (x["page_start"], x["page_end"], x["chunk_id"]))

    # --- Step 2: Classify non-hint candidates as anchor-STRONG or CANDIDATE ---
    anchor_strong: list[dict] = []
    regular_chunks: list[dict] = []

    for c in candidates:
        if c["chunk_id"] in hint_cids:
            continue
        is_strong = _is_chunk_strong(c, phrase_core, word_core, best_score)
        c["is_strong"] = is_strong
        c["is_hint"] = False
        c["is_toc"] = False
        if is_strong:
            anchor_strong.append(c)
        else:
            regular_chunks.append(c)

    total_strong_count = len(hint_pool) + len(anchor_strong)

    # --- Step 3: NO_MATERIAL if < 2 strong chunks ---
    if total_strong_count < 2:
        return SourcePack(
            [], status="NO_MATERIAL",
            candidate_count=len(candidates),
            strong_count=total_strong_count,
        )

    # --- Step 4: Order and fill pack ---
    # Batch rotation: batch k starts at chunk 4k, wrapping inside hinted chunks
    if hint_pool:
        n_hint = len(hint_pool)
        start_idx = (batch_idx * 4) % n_hint
        rotated_hint = hint_pool[start_idx:] + hint_pool[:start_idx]
    else:
        rotated_hint = []

    anchor_strong.sort(key=lambda x: x["score"], reverse=True)
    if len(anchor_strong) >= 3:
        n_anchor = len(anchor_strong)
        start_idx = (batch_idx * 4) % n_anchor
        rotated_anchor = anchor_strong[start_idx:] + anchor_strong[:start_idx]
    else:
        rotated_anchor = anchor_strong

    regular_chunks.sort(key=lambda x: x["score"], reverse=True)

    ordered_pool = rotated_hint + rotated_anchor + regular_chunks

    pack_chunks: list[dict] = []
    total_words = 0
    seen_ids: set[str] = set()

    for c in ordered_pool:
        if c["chunk_id"] in seen_ids:
            continue

        w_count = c["words"]
        if pack_chunks and (total_words + w_count > max_words):
            break

        if c.get("is_hint"):
            t_low = c.get("text_lower") or c["text"].lower()
            _, c_hits = check_chunk_anchors(t_low, anchors)
        else:
            c_hits = c.get("hit_list", [])
        c_phrase = [a for a in c_hits if a in phrase_core]
        c_word = [a for a in c_hits if a in word_core]
        c_supp = [a for a in c_hits if a in support_anchors]

        pack_chunks.append({
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            "page_start": c["page_start"],
            "page_end": c["page_end"],
            "score": round(c["score"], 3),
            "words": w_count,
            "is_strong": c["is_strong"],
            "is_hint": c.get("is_hint", False),
            "is_toc": False,
            "heading_hit": c.get("heading_hit", False),
            "heading_text": c.get("heading_text", ""),
            "chapter_following_hit": c.get("chapter_following_hit", False),
            "anchors_hit": c_hits,
            "phrase_core_hit": c_phrase,
            "word_core_hit": c_word,
            # Legacy key for compat with existing inspect/dump code:
            "core_anchors_hit": c_phrase + c_word,
            "support_anchors_hit": c_supp,
            "num_anchors": len(c_hits),
            "source_concept": c.get("source_concept", concept_tag),
            "is_borrowed": False,
        })
        seen_ids.add(c["chunk_id"])
        total_words += w_count

        if total_words >= max_words:
            break

    return SourcePack(
        pack_chunks,
        status="OK",
        candidate_count=len(candidates),
        strong_count=total_strong_count,
        borrowed=False,
        source_concept=concept_tag,
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
        if c.get("is_hint"):
            badges.append("[HINT]")
        if c.get("heading_hit"):
            h_text = c.get("heading_text")
            if h_text:
                badges.append(f'[HEADING-HIT: "{h_text}"]')
            else:
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
            snip = c["text"][:300].replace("\n", " ")
            print(f"\nChunk {i}: pp.{c['page_start']}-{c['page_end']} {badge_str}")
            print(f"  Source Concept: {c.get('source_concept')}")
            if c.get("heading_hit") and c.get("heading_text"):
                print(f"  Heading: {c.get('heading_text')}")
            print(f"  Distinct Anchors ({num_anchors}):")
            print(f"    CORE ({len(core_hits)}): {core_hits}")
            print(f"    SUPPORT ({len(supp_hits)}): {supp_hits}")
            print(f"  Score: {c['score']} | Words: {c['words']}")
            print(f"  Text: {snip}")
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
