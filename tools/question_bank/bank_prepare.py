"""
=============================================================================
EduGen - Question Bank PDF Preparation Tool
=============================================================================
Extracts per-page text from PDFs in rag/corpus/books/, cleans running headers
and footers, validates text layer (NEEDS OCR check), creates ~350-word chunks
with page boundaries, and builds a BM25 index per PDF.

Usage:
    python tools/question_bank/bank_prepare.py [--books-dir rag/corpus/books] [--force]
=============================================================================
"""

import argparse
import json
import math
import os
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import pymupdf as fitz
except ImportError:
    import fitz


class BM25Index:
    """
    Self-contained BM25 index (Okapi BM25) without external dependencies.
    k1 = 1.5, b = 0.75
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_len = {}  # doc_id -> int
        self.avg_doc_len = 0.0
        self.doc_count = 0
        self.df = {}  # term -> document frequency
        self.tf = {}  # term -> {doc_id: count}
        self.doc_metadata = {}  # doc_id -> metadata dict

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9_]+", (text or "").lower())

    def add_document(self, doc_id: str, text: str, metadata: dict = None):
        tokens = self.tokenize(text)
        length = len(tokens)
        self.doc_len[doc_id] = length
        self.doc_count += 1
        if metadata:
            self.doc_metadata[doc_id] = metadata

        counts = Counter(tokens)
        for term, cnt in counts.items():
            self.df[term] = self.df.get(term, 0) + 1
            if term not in self.tf:
                self.tf[term] = {}
            self.tf[term][doc_id] = cnt

    def finalize(self):
        if self.doc_count > 0:
            self.avg_doc_len = sum(self.doc_len.values()) / self.doc_count
        else:
            self.avg_doc_len = 0.0

    def score(self, query: str, top_k: int = None) -> list[tuple[str, float]]:
        """Compute BM25 scores for query and return sorted list of (doc_id, score)."""
        tokens = self.tokenize(query)
        scores = defaultdict(float)
        if self.doc_count == 0 or not tokens:
            return []

        for term in set(tokens):
            if term not in self.df:
                continue
            n_q = self.df[term]
            # Standard positive IDF formula
            idf = math.log((self.doc_count - n_q + 0.5) / (n_q + 0.5) + 1.0)
            term_docs = self.tf[term]
            q_freq = tokens.count(term)

            for doc_id, f in term_docs.items():
                d_len = self.doc_len[doc_id]
                denom = f + self.k1 * (1.0 - self.b + self.b * (d_len / self.avg_doc_len))
                score = idf * (f * (self.k1 + 1.0)) / denom
                scores[doc_id] += score * q_freq

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k] if top_k else ranked

    def save(self, file_path: Path):
        data = {
            "k1": self.k1,
            "b": self.b,
            "doc_len": self.doc_len,
            "avg_doc_len": self.avg_doc_len,
            "doc_count": self.doc_count,
            "df": self.df,
            "tf": self.tf,
            "doc_metadata": self.doc_metadata,
        }
        with open(file_path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, file_path: Path) -> "BM25Index":
        with open(file_path, "rb") as f:
            data = pickle.load(f)
        if isinstance(data, cls):
            return data
        obj = cls(k1=data.get("k1", 1.5), b=data.get("b", 0.75))
        obj.doc_len = data["doc_len"]
        obj.avg_doc_len = data["avg_doc_len"]
        obj.doc_count = data["doc_count"]
        obj.df = data["df"]
        obj.tf = data["tf"]
        obj.doc_metadata = data.get("doc_metadata", {})
        return obj


def detect_running_headers_footers(pages: list[dict], threshold: float = 0.30) -> set[str]:
    """
    Find lines that repeat across more than threshold (default 30%) of pages.
    Ignores purely trivial syntax lines like single braces.
    """
    total_pages = len(pages)
    if total_pages < 10:
        return set()

    line_page_counts = Counter()
    trivial_lines = {"{", "}", "};", "*/", "/*", ";", "...", "//"}

    for p in pages:
        text = p.get("text", "")
        # Get unique stripped lines on this page
        seen_on_page = set()
        for line in text.splitlines():
            s = line.strip()
            if s and len(s) >= 3 and s not in trivial_lines:
                seen_on_page.add(s)
        for s in seen_on_page:
            line_page_counts[s] += 1

    headers_footers = set()
    for line, count in line_page_counts.items():
        if (count / total_pages) > threshold:
            headers_footers.add(line)

    return headers_footers


def clean_page_text(text: str, running_lines: set[str]) -> str:
    """Remove running header/footer lines while preserving formatting and code lines."""
    if not running_lines:
        return text

    clean_lines = []
    for line in text.splitlines():
        if line.strip() in running_lines:
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


HEADINGS_PATTERN = re.compile(
    r"^(?:(?:chapter|section|\d+\.?)\s+)?(glossary|index|table\s+of\s+contents|contents|preface|acknowledgements?|acknowledgments?|credits|about\s+the\s+authors?|bibliography|references)(?:\s*[:\-—].*)?$",
    re.IGNORECASE,
)


def is_front_or_back_matter(page_num: int, total_pages: int, text: str) -> tuple[bool, str]:
    """
    Identifies front/back matter pages to drop:
      1. Headings in the first 400 characters: Glossary, Index, Table of Contents,
         Contents, Preface, Acknowledg(e)ments, Credits, About the Author(s),
         Bibliography, References. Heading position only, not mid-sentence.
      2. Index-like pages: > 40% non-empty lines end in number/page-range or contain 3+ dot leaders.
      3. Contents-like pages: > 40% lines end in page number AND contain Chapter/Section/numbered headings.
      Preserves appendices and chapter text.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return False, None

    # Check 1: Headings in first 400 chars (heading position: first 6 non-empty lines, short <= 60 chars)
    first_400 = text[:400]
    first_lines = [l.strip() for l in first_400.splitlines() if l.strip()]
    for line in first_lines[:6]:
        if len(line) <= 60 and HEADINGS_PATTERN.match(line):
            # Guard: Keep appendices
            if not re.search(r"\bappendix\b", line, re.IGNORECASE):
                return True, f"heading: {line}"

    # Check 2 & 3: Index-like and Contents-like
    if len(lines) >= 8:
        # Index-like check (>40% non-empty lines end in number or page-range, or contain 3+ dot leaders)
        index_hits = 0
        for l in lines:
            has_dots = bool(re.search(r"\.{3,}|\.\s*\.\s*\.", l))
            ends_num_or_range = bool(re.search(r"[a-zA-Z].*?(?:[,:\s]\s*\d+(?:[-–—]\d+)?|\d+[-–—]\d+)\s*$", l))
            is_dots_only = bool(re.search(r"^\s*[\.\s]{4,}\s*$", l))
            is_num_only = bool(re.search(r"^\s*\d+(?:[-–—]\d+)?\s*$", l))
            if has_dots or ends_num_or_range or is_dots_only or (is_num_only and (page_num <= 40 or page_num >= total_pages - 40)):
                index_hits += 1

        if (index_hits / len(lines)) > 0.40:
            if page_num <= 50 or page_num >= total_pages - 50 or (index_hits / len(lines)) > 0.65:
                if not any(re.search(r"\bappendix\b", l, re.IGNORECASE) for l in first_lines[:3]):
                    return True, f"index-like ({index_hits}/{len(lines)} lines)"

        # Contents-like check (>40% of lines end in page number AND contain Chapter/Section/numbered headings)
        contents_hits = 0
        for l in lines:
            ends_num = bool(re.search(r"\b\d+\s*$", l))
            has_chapter_sec = bool(re.search(r"\b(?:chapter|section|\d+\.\d+)\b", l, re.IGNORECASE))
            if ends_num and has_chapter_sec:
                contents_hits += 1

        if (contents_hits / len(lines)) > 0.40:
            if page_num <= 50 or page_num >= total_pages - 50:
                return True, f"contents-like ({contents_hits}/{len(lines)} lines)"

    return False, None


def chunk_pages(
    pages: list[dict],
    pdfshort: str,
    target_words: int = 350,
    overlap_words: int = 60,
    max_page_gap: int = 2,
) -> list[dict]:
    """
    Chunks text with:
      - ~350 words per chunk
      - ~60 words overlap
      - Never crosses a page gap of > 2 pages
      - Keeps code lines and newlines intact
      - Retains page_start and page_end
    """
    # 1. Break into paragraph blocks with page markers
    blocks = []
    for p in pages:
        page_num = p["page"]
        text = p["text"]
        if not text.strip():
            continue

        paragraphs = text.split("\n\n")
        for para in paragraphs:
            para_str = para.strip()
            if not para_str:
                continue
            words = para_str.split()
            blocks.append({
                "page": page_num,
                "text": para_str,
                "word_count": len(words),
            })

    if not blocks:
        return []

    chunks = []
    chunk_idx = 1
    i = 0
    total_blocks = len(blocks)

    while i < total_blocks:
        cur_blocks = []
        cur_words = 0
        page_start = blocks[i]["page"]
        page_end = page_start
        last_page = page_start

        j = i
        while j < total_blocks:
            blk = blocks[j]
            # Page gap check: never cross gap of > max_page_gap
            if (blk["page"] - last_page) > max_page_gap and cur_blocks:
                break

            cur_blocks.append(blk)
            cur_words += blk["word_count"]
            page_end = blk["page"]
            last_page = blk["page"]
            j += 1

            # Check if target words reached
            if cur_words >= target_words:
                break

        if not cur_blocks:
            break

        chunk_text = "\n\n".join(b["text"] for b in cur_blocks)
        chunks.append({
            "chunk_id": f"{pdfshort}_chunk_{chunk_idx:05d}",
            "pdf": pdfshort,
            "page_start": page_start,
            "page_end": page_end,
            "text": chunk_text,
            "word_count": cur_words,
        })
        chunk_idx += 1

        # Advance with overlap: roll back ~overlap_words from the end
        if j >= total_blocks:
            break

        overlap_acc = 0
        rollback = 0
        for k in range(len(cur_blocks) - 1, -1, -1):
            w = cur_blocks[k]["word_count"]
            overlap_acc += w
            rollback += 1
            if overlap_acc >= overlap_words:
                break

        # If rollback covers all blocks, advance by at least 1 block to ensure progress
        if rollback >= len(cur_blocks):
            rollback = len(cur_blocks) - 1

        if rollback > 0:
            i = j - rollback
        else:
            i = j

    return chunks


def process_pdf(pdf_path: Path, work_dir: Path, force: bool = False) -> dict:
    """Process a single PDF: extract, clean, check OCR, chunk, and index."""
    pdfshort = pdf_path.stem
    pdf_out_dir = work_dir / pdfshort
    pdf_out_dir.mkdir(parents=True, exist_ok=True)

    pages_file = pdf_out_dir / "pages.jsonl"
    chunks_file = pdf_out_dir / "chunks.jsonl"
    index_file = pdf_out_dir / "bm25.pkl"

    start_time = time.time()
    print(f"\n=======================================================")
    print(f"Processing PDF: {pdfshort} ({pdf_path.name})")
    print(f"=======================================================")

    # Step 1: Extract text or load cached pages
    pages = []
    if pages_file.exists() and not force:
        print(f"  [Cache hit] Loading extracted pages from {pages_file}")
        with open(pages_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    pages.append(json.loads(line))
        print(f"  Loaded {len(pages)} cached pages.")
    else:
        print(f"  Extracting text per page with PyMuPDF...")
        doc = fitz.open(pdf_path)
        total_doc_pages = len(doc)
        with open(pages_file, "w", encoding="utf-8") as f:
            for page_idx, page in enumerate(doc, start=1):
                page_text = page.get_text("text") or ""
                p_entry = {"page": page_idx, "text": page_text}
                pages.append(p_entry)
                f.write(json.dumps(p_entry, ensure_ascii=False) + "\n")
                if page_idx % 100 == 0 or page_idx == total_doc_pages:
                    print(f"  [{pdfshort}] Extracted {page_idx}/{total_doc_pages} pages...")
        doc.close()

    total_pages = len(pages)
    if total_pages == 0:
        print(f"  [Error] No pages extracted from {pdf_path}")
        return {"pdf": pdfshort, "pages": 0, "needs_ocr": True}

    # Step 2: Scanned PDF check (< 50 characters on > 20% of pages)
    short_pages = sum(1 for p in pages if len(p.get("text", "").strip()) < 50)
    pages_with_text = total_pages - short_pages
    pct_with_text = (pages_with_text / total_pages) * 100.0
    needs_ocr = (short_pages / total_pages) > 0.20

    print(f"  Page text stats: {pages_with_text}/{total_pages} ({pct_with_text:.1f}%) pages with >= 50 characters.")

    if needs_ocr:
        print(f"  [WARNING] NEEDS OCR: {pdfshort} has {short_pages}/{total_pages} pages with < 50 chars.")
        duration = time.time() - start_time
        return {
            "pdf": pdfshort,
            "pages": total_pages,
            "pct_with_text": pct_with_text,
            "chunks": 0,
            "needs_ocr": True,
            "duration": duration,
        }

    # Step 3: Header/footer removal
    headers_footers = detect_running_headers_footers(pages, threshold=0.30)
    print(f"  Detected {len(headers_footers)} running header/footer lines.")
    if headers_footers:
        for p in pages:
            p["text"] = clean_page_text(p["text"], headers_footers)

    # Step 3b: Front/back matter filter (apply BEFORE chunking)
    dropped_pages = []
    kept_pages = []
    for p in pages:
        is_drop, reason = is_front_or_back_matter(p["page"], total_pages, p["text"])
        if is_drop:
            dropped_pages.append({"page": p["page"], "reason": reason})
        else:
            kept_pages.append(p)

    dropped_file = pdf_out_dir / "dropped_pages.json"
    with open(dropped_file, "w", encoding="utf-8") as f:
        json.dump(dropped_pages, f, indent=2)

    print(f"  Front/back matter filter: dropped {len(dropped_pages)} pages (kept {len(kept_pages)}).")
    if dropped_pages:
        examples = [f"p.{dp['page']} ({dp['reason']})" for dp in dropped_pages[:3]]
        print(f"    Examples dropped: {', '.join(examples)}")

    # Step 4: Chunking
    chunks = chunk_pages(kept_pages, pdfshort, target_words=350, overlap_words=60, max_page_gap=2)
    print(f"  Created {len(chunks)} chunks (~350 words, ~60 overlap).")

    with open(chunks_file, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # Step 5: Build BM25 index
    print(f"  Building BM25 index over {len(chunks)} chunks...")
    bm25 = BM25Index(k1=1.5, b=0.75)
    for c in chunks:
        bm25.add_document(
            doc_id=c["chunk_id"],
            text=c["text"],
            metadata={"page_start": c["page_start"], "page_end": c["page_end"]},
        )
    bm25.finalize()
    bm25.save(index_file)
    print(f"  Saved BM25 index to {index_file}")

    duration = time.time() - start_time
    print(f"  Finished {pdfshort} in {duration:.1f} seconds.")

    return {
        "pdf": pdfshort,
        "pages": total_pages,
        "pct_with_text": pct_with_text,
        "dropped_pages": len(dropped_pages),
        "kept_pages": len(kept_pages),
        "chunks": len(chunks),
        "needs_ocr": False,
        "duration": duration,
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare PDFs for question generation.")
    parser.add_argument("--books-dir", default="rag/corpus/books", help="Directory containing PDF textbooks.")
    parser.add_argument("--work-dir", default="data/bank_work", help="Working directory for chunk caches and indices.")
    parser.add_argument("--force", action="store_true", help="Force re-extraction even if pages.jsonl exists.")
    args = parser.parse_args()

    books_dir = Path(args.books_dir)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(list(books_dir.glob("*.pdf")))
    if not pdf_files:
        print(f"No PDFs found in {books_dir}")
        return

    results = []
    for pdf_path in pdf_files:
        res = process_pdf(pdf_path, work_dir, force=args.force)
        results.append(res)

    print("\n" + "=" * 65)
    print("  PDF Preparation Summary")
    print("=" * 65)
    for r in results:
        ocr_flag = " [NEEDS OCR]" if r["needs_ocr"] else ""
        print(f"  {r['pdf']:<28} : {r['pages']:>4} pages ({r.get('dropped_pages', 0):>2} dropped) | {r['pct_with_text']:>5.1f}% text | {r['chunks']:>5} chunks | {r['duration']:>5.1f}s{ocr_flag}")
    print("=" * 65)


if __name__ == "__main__":
    main()
