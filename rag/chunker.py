"""
=============================================================================
EduGen RAG - Document Loading and Chunking
=============================================================================
Turns whatever sits in rag/corpus/ into clean, tagged, retrievable chunks.

Supported inputs : .md  .txt  .pdf
Chunking policy  : split on Markdown headings first (semantic boundaries),
                   then pack to ~900 characters with 150 characters overlap,
                   never cutting a sentence in half if it can be helped.

Every chunk carries concept tags. Tags come from two places:
  1. explicit front matter in a note file  ->  `concept: method-overriding`
  2. automatic keyword matching against core/concepts.py

Those tags are what let the retriever filter by concept instead of relying on
vector similarity alone - the single biggest quality win in this pipeline.
=============================================================================
"""

import json
import logging
import os
import re
import warnings
from pathlib import Path

from core.concepts import CONCEPTS
from rag.levels import infer_level

# Silence pypdf fontTools warning
logging.getLogger("pypdf").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*fontTools.*")

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

CHUNK_TARGET_CHARS = 900
CHUNK_OVERLAP_CHARS = 150
CHUNK_MIN_CHARS = 180

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WS_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")
PAGE_MARKER_RE = re.compile(r"===PAGE:(\d+)===")

RAG_CACHE_DIR = Path(os.environ.get("EDUGEN_RAG_CACHE") or (Path(__file__).resolve().parent.parent / "data" / "rag_cache"))

# Pre-compute keyword -> tag lookups once
_KEYWORD_INDEX = []
for _tag, _meta in CONCEPTS.items():
    phrases = set(k.lower() for k in _meta["keywords"])
    phrases.add(_meta["title"].lower())
    phrases.add(_tag.replace("-", " "))
    _KEYWORD_INDEX.append((_tag, sorted(phrases, key=len, reverse=True)))


# ─────────────────────────────────────────────────────────────
# Loading
# ─────────────────────────────────────────────────────────────
def _parse_pdf_pages(path):
    """Extract page dicts [{'page': n, 'text': ...}] with 100-page progress logging."""
    pages = []
    # 1. Try pymupdf (fitz)
    try:
        import pymupdf as fitz
        doc = fitz.open(str(path))
        for page_idx, page in enumerate(doc, start=1):
            if page_idx % 100 == 0:
                print(f"  [{path.name}] parsed {page_idx} pages...")
            t = page.get_text() or ""
            pages.append({"page": page_idx, "text": t})
        if pages:
            return pages
    except Exception:
        pass

    # 2. Try pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        for page_idx, page in enumerate(reader.pages, start=1):
            if page_idx % 100 == 0:
                print(f"  [{path.name}] parsed {page_idx} pages...")
            t = page.extract_text() or ""
            pages.append({"page": page_idx, "text": t})
        if pages:
            return pages
    except Exception:
        pass

    # 3. Try pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                if page_idx % 100 == 0:
                    print(f"  [{path.name}] parsed {page_idx} pages...")
                t = page.extract_text() or ""
                pages.append({"page": page_idx, "text": t})
        if pages:
            return pages
    except Exception as exc:
        raise RuntimeError(
            f"Could not read {path.name}. Install a PDF reader: pip install pymupdf pypdf ({exc})"
        )
    return pages


def load_pdf(path, cache_dir=None):
    """
    Extract text from a PDF with page markers.
    Caches parsed pages to data/rag_cache/<pdf-stem>.jsonl keyed by file size + mtime.
    Subsequent runs read from cache without re-parsing.
    Emits progress line every 100 pages during parsing.
    """
    path = Path(path)
    c_dir = Path(cache_dir or RAG_CACHE_DIR)
    c_dir.mkdir(parents=True, exist_ok=True)
    cache_file = c_dir / f"{path.stem}.jsonl"

    st = path.stat()
    file_size = st.st_size
    file_mtime = st.st_mtime

    # Try reading from cache
    if cache_file.exists():
        try:
            pages = []
            valid_cache = False
            with open(cache_file, "r", encoding="utf-8") as fh:
                first_line = fh.readline()
                if first_line:
                    header = json.loads(first_line)
                    if header.get("size") == file_size and header.get("mtime") == file_mtime:
                        valid_cache = True
                        for line in fh:
                            line_str = line.strip()
                            if line_str:
                                rec = json.loads(line_str)
                                pages.append(rec)
            if valid_cache and pages:
                text_parts = [
                    f"\n\n===PAGE:{p['page']}===\n\n{p['text']}"
                    for p in pages
                    if p.get("text", "").strip()
                ]
                return "\n\n".join(text_parts)
        except Exception:
            pass  # Corrupted cache fallback

    # Parse fresh and populate cache
    pages = _parse_pdf_pages(path)
    try:
        with open(cache_file, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"size": file_size, "mtime": file_mtime}) + "\n")
            for p in pages:
                fh.write(json.dumps({"page": p["page"], "text": p["text"]}, ensure_ascii=False) + "\n")
    except Exception:
        pass

    text_parts = [
        f"\n\n===PAGE:{p['page']}===\n\n{p['text']}"
        for p in pages
        if p.get("text", "").strip()
    ]
    return "\n\n".join(text_parts)


def load_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def parse_frontmatter(raw):
    """Return (metadata_dict, body) for a Markdown file with `---` front matter."""
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    meta = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key in ("tags", "concepts", "concept_tags"):
            meta[key] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            meta[key] = value
    return meta, raw[match.end():]


def load_document(path):
    """Load one file -> dict(text, meta)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        return {"text": clean_text(load_pdf(path)), "meta": {}}
    raw = load_text(path)
    meta, body = parse_frontmatter(raw)
    return {"text": clean_text(body), "meta": meta}


def clean_text(text):
    """Normalise whitespace and strip PDF page-number noise, preserving page markers."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n\s*\d{1,4}\s*\n", "\n\n", text)      # stray page numbers
    text = re.sub(r"\n\s*Page \|\s*\d+\s*\n", "\n\n", text)
    text = _WS_RE.sub(" ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────
# Tagging
# ─────────────────────────────────────────────────────────────
def infer_concept_tags(text, limit=4):
    """Score every canonical concept against a chunk and keep the best few."""
    lowered = " " + (text or "").lower() + " "
    scored = []
    for tag, phrases in _KEYWORD_INDEX:
        score = 0
        for phrase in phrases:
            if phrase in lowered:
                # longer phrases are stronger evidence
                score += 2 if len(phrase) > 10 else 1
        if score:
            scored.append((score, tag))
    scored.sort(reverse=True)
    return [tag for _, tag in scored[:limit]]


# ─────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────
def _split_sections(text):
    """Split Markdown by headings -> [(section_title, body)]."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]

    sections = []
    if matches[0].start() > 0:
        head = text[:matches[0].start()].strip()
        if head:
            sections.append(("", head))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((m.group(2).strip(), body))
    return sections


def _pack(body, target=CHUNK_TARGET_CHARS, overlap=CHUNK_OVERLAP_CHARS):
    """Greedy paragraph packing with a character overlap between chunks."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    chunks, current = [], ""

    for para in paragraphs:
        if len(para) > target * 1.8:
            # very long paragraph: cut on sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if len(current) + len(sent) + 1 > target and current:
                    chunks.append(current.strip())
                    current = current[-overlap:] if overlap else ""
                current += " " + sent
            continue

        if len(current) + len(para) + 2 > target and current:
            chunks.append(current.strip())
            current = current[-overlap:] if overlap else ""
        current += "\n\n" + para

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if len(c) >= CHUNK_MIN_CHARS] or ([body] if body.strip() else [])


def chunk_document(path, source_label=None, collection="book"):
    """
    Read one file and return a list of chunk dicts ready for embedding.

    Chunk metadata:
      { id, text, collection, concept_tags, type, difficulty, level, source, page, ... }
    """
    path = Path(path)
    doc = load_document(path)
    text, meta = doc["text"], doc["meta"]
    if not text.strip():
        return []

    col = (collection or "").lower()
    if "book" in col or path.suffix.lower() == ".pdf":
        norm_collection = "book"
    elif "note" in col or path.suffix.lower() in (".md", ".txt"):
        norm_collection = "note"
    elif "question" in col:
        norm_collection = "question"
    else:
        norm_collection = "note"

    doc_title = meta.get("title") or path.stem.replace("_", " ").replace("-", " ").title()
    declared = meta.get("concept_tags") or meta.get("tags") or meta.get("concepts") or []
    if isinstance(declared, str):
        declared = [declared]
    if meta.get("concept"):
        declared = [meta["concept"]] + list(declared)
    declared = [t for t in declared if t in CONCEPTS]

    source = source_label or path.name
    chunks = []
    index = 0
    current_page = 1

    for section_title, body in _split_sections(text):
        for piece in _pack(body):
            page_matches = PAGE_MARKER_RE.findall(piece)
            if page_matches:
                try:
                    current_page = int(page_matches[-1])
                except ValueError:
                    pass
                piece = PAGE_MARKER_RE.sub("", piece).strip()

            if not piece:
                continue

            heading_context = "{} - {}".format(doc_title, section_title).strip(" -")
            tags = list(declared)
            for tag in infer_concept_tags(section_title + " " + piece):
                if tag not in tags:
                    tags.append(tag)

            has_code = "```" in piece or "class " in piece or "public " in piece or "System.out" in piece
            chunk_type = "example" if has_code else "lesson"
            level = infer_level(piece, heading=heading_context)

            chunks.append({
                "id": "{}::{}".format(source, index),
                "text": piece,
                "collection": norm_collection,
                "concept_tags": tags[:6],
                "type": chunk_type,
                "difficulty": None,
                "level": level,
                "source": source,
                "page": current_page,
                "title": doc_title,
                "section": section_title,
                "heading": heading_context,
            })
            index += 1

    return chunks


def chunk_question_record(rec: dict) -> dict:
    """
    Ingest one MCQ record into collection 'question'.
    Embedded text = question text + the correct option + the explanation (NOT wrong options).
    """
    q_text = rec.get("question", "").strip()
    c_idx = rec.get("correct_index", 0)
    options = rec.get("options", [])
    c_text = options[c_idx].get("text", "").strip() if (isinstance(c_idx, int) and 0 <= c_idx < len(options)) else ""
    expl = rec.get("explanation", "").strip()
    embedded_text = f"{q_text}\nCorrect answer: {c_text}\nExplanation: {expl}".strip()

    diff = rec.get("difficulty", "Medium")
    if diff == "Easy":
        level = "basic"
    elif diff == "Hard":
        level = "advanced"
    else:
        level = "standard"

    concept = rec.get("concept", "")
    src = rec.get("source", {})
    qid = rec.get("question_id") or rec.get("id", "")
    misconceptions = [
        opt.get("misconception_id")
        for opt in options
        if opt.get("misconception_id")
    ]

    return {
        "id": qid,
        "text": embedded_text,
        "collection": "question",
        "concept_tags": [concept] if concept else [],
        "type": "mcq",
        "difficulty": diff,
        "level": level,
        "source": src.get("pdf", "question_bank"),
        "page": src.get("page", 1),
        "question_id": qid,
        "concept": concept,
        "qtype": rec.get("qtype", "concept"),
        "correct_index": c_idx,
        "raw_record": rec,
        "misconception_ids": misconceptions,
        "title": qid,
        "section": concept,
        "heading": f"{concept} ({diff})",
    }


def iter_corpus_files(corpus_dir):
    """Yield (path, collection) for every supported file under corpus_dir."""
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.exists():
        return
    for root, _dirs, files in os.walk(corpus_dir):
        for name in sorted(files):
            if name.startswith(".") or name.upper() in ("README.MD", "SOURCES.MD"):
                continue
            path = Path(root) / name
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            rel = path.relative_to(corpus_dir)
            raw_col = rel.parts[0].lower() if len(rel.parts) > 1 else "root"
            if "book" in raw_col:
                col = "book"
            elif "note" in raw_col:
                col = "note"
            elif "question" in raw_col:
                col = "question"
            else:
                col = "book" if path.suffix.lower() == ".pdf" else "note"
            yield path, col
