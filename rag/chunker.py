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

import os
import re
from pathlib import Path

from core.concepts import CONCEPTS

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

CHUNK_TARGET_CHARS = 900
CHUNK_OVERLAP_CHARS = 150
CHUNK_MIN_CHARS = 180

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WS_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")

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
def load_pdf(path):
    """Extract text from a PDF. Tries pypdf, then pdfplumber."""
    text_parts = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                text_parts.append(t)
        if text_parts:
            return "\n\n".join(text_parts)
    except Exception:
        pass

    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    text_parts.append(t)
    except Exception as exc:
        raise RuntimeError(
            "Could not read {}. Install a PDF reader:  pip install pypdf  ({})".format(path.name, exc)
        )
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
    """Normalise whitespace and strip PDF page-number noise."""
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


def chunk_document(path, source_label=None, collection="library"):
    """
    Read one file and return a list of chunk dicts ready for embedding.

    Chunk shape:
      { id, text, source, collection, title, section, concept_tags }
    """
    path = Path(path)
    doc = load_document(path)
    text, meta = doc["text"], doc["meta"]
    if not text.strip():
        return []

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

    for section_title, body in _split_sections(text):
        for piece in _pack(body):
            heading_context = "{} - {}".format(doc_title, section_title).strip(" -")
            tags = list(declared)
            for tag in infer_concept_tags(section_title + " " + piece):
                if tag not in tags:
                    tags.append(tag)
            chunks.append({
                "id": "{}::{}".format(source, index),
                "text": piece,
                "source": source,
                "collection": collection,
                "title": doc_title,
                "section": section_title,
                "heading": heading_context,
                "concept_tags": tags[:6],
            })
            index += 1

    return chunks


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
            collection = rel.parts[0] if len(rel.parts) > 1 else "root"
            yield path, collection
