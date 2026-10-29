"""
=============================================================================
EduGen - Unit Tests for Question Bank Preparation Tools
=============================================================================
Tests:
  1. Running header / footer detection (including digit normalization)
  2. Text chunking (target words, overlap, page gap limits, formatting)
  3. BM25 indexing, scoring, and serialization
  4. Source pack rotation by batch index
  5. Front/back matter page filtering
  6. Anchor relevance: CORE vs SUPPORT, heading hits, generic anchors x3 not strong
  7. Borrowed pack labelling and source concept tracking
  8. Quota distribution mathematics and caps

Usage:
    python tools/question_bank/test_bank_tools.py
=============================================================================
"""

import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.concepts import CONCEPTS
from tools.question_bank.bank_coverage import allocate_quotas
from tools.question_bank.bank_pack import (
    ANCHOR_EXTRA,
    PACK_ALIASES,
    build_pack,
    check_chunk_anchors,
    check_heading_hit,
    get_anchors,
    split_anchors,
)
from tools.question_bank.bank_prepare import (
    BM25Index,
    chunk_pages,
    clean_page_text,
    detect_running_headers_footers,
    is_front_or_back_matter,
    normalize_header_line,
)


class TestHeaderFooterDetection(unittest.TestCase):
    def test_running_header_footer_detection(self):
        # 10 synthetic pages; header appears on 6 pages (60% > 30% threshold)
        pages = []
        for i in range(1, 11):
            text_lines = [
                f"Page content for page {i} discussing object-oriented programming concepts in Java.",
                f"public class Example{i} {{",
                f"    int x{i} = {i};",
                "}",
            ]
            if i <= 6:
                text_lines.insert(0, "RUNNING HEADER LINE - CONFIDENTIAL")
                text_lines.append("RUNNING FOOTER - COPYRIGHT 2026")
            pages.append({"page": i, "text": "\n".join(text_lines)})

        exact, norm = detect_running_headers_footers(pages, threshold=0.30)
        self.assertIn("RUNNING HEADER LINE - CONFIDENTIAL", exact)
        self.assertIn("RUNNING FOOTER - COPYRIGHT 2026", exact)
        self.assertNotIn("public class Example1 {", exact)
        self.assertNotIn("}", exact)

    def test_clean_page_text(self):
        running_exact = {"HEADER TO REMOVE", "FOOTER TO REMOVE"}
        text = "HEADER TO REMOVE\nSome real content line.\n    int x = 42;\nFOOTER TO REMOVE"
        cleaned = clean_page_text(text, running_exact)
        self.assertNotIn("HEADER TO REMOVE", cleaned)
        self.assertNotIn("FOOTER TO REMOVE", cleaned)
        self.assertIn("Some real content line.", cleaned)
        self.assertIn("    int x = 42;", cleaned)

    def test_header_normalization_strips_digit_varying_headers(self):
        # Requirement 10(d): header normalization strips digit-varying headers
        # (e.g. "432 CHAPTER 8. CORRECTNESS..." and "433 CHAPTER 8. CORRECTNESS...")
        pages = []
        for i in range(1, 15):
            p_text = f"{400 + i} CHAPTER 8. CORRECTNESS\nReal content paragraph on page {i}.\n"
            pages.append({"page": i, "text": p_text})

        exact, norm = detect_running_headers_footers(pages, threshold=0.30)
        # Normalized pattern with # should be detected
        self.assertTrue(any("# CHAPTER #. CORRECTNESS" in n for n in norm))

        # Stripping test: clean_page_text should remove the header even on a page with a new number
        sample_page = "450 CHAPTER 8. CORRECTNESS\nActual programming logic."
        cleaned = clean_page_text(sample_page, exact, norm)
        self.assertNotIn("CHAPTER 8. CORRECTNESS", cleaned)
        self.assertIn("Actual programming logic.", cleaned)


class TestChunking(unittest.TestCase):
    def test_chunk_word_count_and_overlap(self):
        pages = []
        word_counter = 0
        for p in range(1, 6):
            paras = []
            for _ in range(2):
                words = [f"word{word_counter + i}" for i in range(50)]
                word_counter += 50
                paras.append(" ".join(words))
            pages.append({"page": p, "text": "\n\n".join(paras)})

        chunks = chunk_pages(pages, "test_book", target_words=150, overlap_words=40, max_page_gap=2)
        self.assertTrue(len(chunks) > 1)

        for c in chunks:
            self.assertGreaterEqual(c["page_end"], c["page_start"])
            self.assertGreater(c["word_count"], 0)
            self.assertTrue(c["chunk_id"].startswith("test_book_chunk_"))

        words_c0 = set(chunks[0]["text"].split())
        words_c1 = set(chunks[1]["text"].split())
        overlap = words_c0.intersection(words_c1)
        self.assertGreater(len(overlap), 0, "Consecutive chunks should have overlapping vocabulary")

    def test_chunk_page_gap_constraint(self):
        pages = [
            {"page": 1, "text": "Short intro on page one."},
            {"page": 5, "text": "Content after page gap of four pages."},
        ]
        chunks = chunk_pages(pages, "test_gap", target_words=100, overlap_words=20, max_page_gap=2)
        for c in chunks:
            self.assertFalse(c["page_start"] == 1 and c["page_end"] == 5)


class TestBM25Index(unittest.TestCase):
    def setUp(self):
        self.index = BM25Index(k1=1.5, b=0.75)
        self.docs = {
            "doc1": "Java inheritance extends base class methods and super constructor calls.",
            "doc2": "Polymorphism allows dynamic method dispatch and method overriding at runtime.",
            "doc3": "Try catch finally blocks handle runtime exceptions and checked exceptions.",
            "doc4": "Static fields belong to the class while instance fields belong to objects.",
        }
        for doc_id, text in self.docs.items():
            self.index.add_document(doc_id, text)
        self.index.finalize()

    def test_ranking_relevance(self):
        scores = self.index.score("method overriding dynamic dispatch runtime")
        self.assertTrue(len(scores) > 0)
        top_doc, top_score = scores[0]
        self.assertEqual(top_doc, "doc2", "Doc 2 must rank highest for method overriding query")

    def test_save_and_load(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            save_path = temp_dir / "test_bm25.pkl"
            self.index.save(save_path)
            loaded = BM25Index.load(save_path)
            self.assertEqual(loaded.doc_count, self.index.doc_count)
            self.assertEqual(loaded.avg_doc_len, self.index.avg_doc_len)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestSourcePackRotation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.pdfshort = "synthetic_pdf"
        pdf_dir = self.temp_dir / self.pdfshort
        pdf_dir.mkdir(parents=True)

        chunks = []
        index = BM25Index(k1=1.5, b=0.75)
        for i in range(1, 13):
            cid = f"{self.pdfshort}_chunk_{i:05d}"
            text = f"Paragraph {i} regarding method overriding and inheritance in Java. Repeat overriding " * (i * 10)
            c_entry = {
                "chunk_id": cid,
                "pdf": self.pdfshort,
                "page_start": i,
                "page_end": i,
                "text": text,
                "word_count": len(text.split()),
            }
            chunks.append(c_entry)
            index.add_document(cid, text)
        index.finalize()
        index.save(pdf_dir / "bm25.pkl")

        with open(pdf_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_batch_rotation(self):
        pack0 = build_pack(self.pdfshort, "method-overriding", batch_idx=0, max_words=300, work_dir=self.temp_dir)
        pack1 = build_pack(self.pdfshort, "method-overriding", batch_idx=1, max_words=300, work_dir=self.temp_dir)

        self.assertTrue(len(pack0) > 0)
        self.assertTrue(len(pack1) > 0)
        self.assertNotEqual(pack0[0]["chunk_id"], pack1[0]["chunk_id"])


class TestFrontBackMatterFilter(unittest.TestCase):
    def test_glossary_page_is_dropped(self):
        text = "Glossary\n761\nnull. A special pointer value that means not pointing to anything.\nqueue. A data structure."
        is_drop, reason = is_front_or_back_matter(page_num=770, total_pages=780, text=text)
        self.assertTrue(is_drop, "Glossary page must be dropped")
        self.assertIn("heading: Glossary", reason)

    def test_dotted_index_page_is_dropped(self):
        lines = [
            "Index",
            "Abstract class . . . . . . . . . . . . . . . . . . . . . . . . . 272",
            "Access modifier . . . . . . . . . . . . . . . . . . . . . . . . 189",
            "Array covariance . . . . . . . . . . . . . . . . . . . . . . . . 120",
            "Binary search . . . . . . . . . . . . . . . . . . . . . . . . . 340",
            "Class definition . . . . . . . . . . . . . . . . . . . . . . . . 45",
            "Constructor chaining . . . . . . . . . . . . . . . . . . . . . . 210",
            "Dynamic dispatch . . . . . . . . . . . . . . . . . . . . . . . . 280",
            "Exception handling . . . . . . . . . . . . . . . . . . . . . . . 400",
            "Final keyword . . . . . . . . . . . . . . . . . . . . . . . . . 150",
        ]
        text = "\n".join(lines)
        is_drop, reason = is_front_or_back_matter(page_num=775, total_pages=780, text=text)
        self.assertTrue(is_drop, "Dotted index page must be dropped")

    def test_chapter_text_is_kept(self):
        text = (
            "5.5 Inheritance and Polymorphism\n"
            "Inheritance is a powerful feature of object-oriented programming in Java.\n"
            "A subclass can extend a superclass and inherit all of its public and protected members.\n"
            "public class Dog extends Animal {\n"
            "    public void speak() {\n"
            "        System.out.println(\"Woof\");\n"
            "    }\n"
            "}\n"
        )
        is_drop, reason = is_front_or_back_matter(page_num=250, total_pages=780, text=text)
        self.assertFalse(is_drop, "Real chapter text must not be dropped")


class TestPhase2DFix2Rules(unittest.TestCase):
    def setUp(self):
        from tools.question_bank.bank_pack import _INDEX_CACHE, _CHUNKS_CACHE
        _INDEX_CACHE.clear()
        _CHUNKS_CACHE.clear()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.pdfshort = "test_book_rules"
        self.pdf_dir = self.temp_dir / self.pdfshort
        self.pdf_dir.mkdir(parents=True)

    def tearDown(self):
        from tools.question_bank.bank_pack import _INDEX_CACHE, _CHUNKS_CACHE
        _INDEX_CACHE.clear()
        _CHUNKS_CACHE.clear()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_mock_index(self, chunks):
        index = BM25Index(k1=1.5, b=0.75)
        for c in chunks:
            index.add_document(c["chunk_id"], c["text"])
        index.finalize()
        index.save(self.pdf_dir / "bm25.pkl")

        with open(self.pdf_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

    def test_generic_anchors_x3_not_strong(self):
        # Requirement 10(a): a chunk with only "chaining"/"dynamic"/"copy" x3 is NOT strong.
        # Under Phase 2D-fix-2, SUPPORT anchors alone make a chunk a CANDIDATE only, NEVER STRONG.
        chunks = [
            # Chunk with chaining x3, dynamic x3, copy x3 (SUPPORT anchors only)
            {
                "chunk_id": f"{self.pdfshort}_chunk_00001",
                "pdf": self.pdfshort,
                "page_start": 20,
                "page_end": 20,
                "text": "Discussion on chaining chaining chaining conditionals and dynamic dynamic dynamic arrays with copy copy copy files.",
                "word_count": 18,
            },
            # Chunk with real CORE anchor for constructor-chaining
            {
                "chunk_id": f"{self.pdfshort}_chunk_00002",
                "pdf": self.pdfshort,
                "page_start": 21,
                "page_end": 21,
                "text": "Constructor chaining in Java allows invoking super(args) or this(args) as first statement.",
                "word_count": 15,
            },
            # Padding candidate chunk
            {
                "chunk_id": f"{self.pdfshort}_chunk_00003",
                "pdf": self.pdfshort,
                "page_start": 22,
                "page_end": 22,
                "text": "Another constructor chaining explanation with super(x) call.",
                "word_count": 8,
            },
        ]
        self._setup_mock_index(chunks)

        pack = build_pack(self.pdfshort, "constructor-chaining", batch_idx=0, max_words=1000, work_dir=self.temp_dir)
        c1 = next(c for c in pack if c["chunk_id"] == f"{self.pdfshort}_chunk_00001")
        # Must be CANDIDATE only, NOT strong!
        self.assertFalse(c1["is_strong"], "Chunk with only generic support words x3 must not be strong")
        self.assertEqual(len(c1["core_anchors_hit"]), 0)

    def test_heading_hit_chunk_is_strong(self):
        # Requirement 10(b): heading-hit chunk is strong regardless of score ratio
        chunks = [
            # Chunk with a chapter heading containing a CORE phrase
            {
                "chunk_id": f"{self.pdfshort}_chunk_00010",
                "pdf": self.pdfshort,
                "page_start": 153,
                "page_end": 153,
                "text": "Chapter 153: Dynamic Method Dispatch\nThis chapter explains polymorphic dispatch.",
                "word_count": 10,
            },
            # Unrelated chunk with high BM25 score
            {
                "chunk_id": f"{self.pdfshort}_chunk_00011",
                "pdf": self.pdfshort,
                "page_start": 154,
                "page_end": 154,
                "text": "Dynamic method dispatch and dynamic binding runtime polymorphism dispatch dispatch dispatch.",
                "word_count": 12,
            },
            {
                "chunk_id": f"{self.pdfshort}_chunk_00012",
                "pdf": self.pdfshort,
                "page_start": 155,
                "page_end": 155,
                "text": "Third candidate chunk with dynamic binding and late binding.",
                "word_count": 10,
            },
        ]
        self._setup_mock_index(chunks)

        pack = build_pack(self.pdfshort, "dynamic-method-dispatch", batch_idx=0, max_words=1000, work_dir=self.temp_dir)
        heading_chunk = next(c for c in pack if c["chunk_id"] == f"{self.pdfshort}_chunk_00010")
        self.assertTrue(heading_chunk["heading_hit"])
        self.assertTrue(heading_chunk["is_strong"], "Heading-hit chunk must be strong regardless of score ratio")

    def test_borrowed_pack_labels_source_concept(self):
        # Requirement 10(c): borrowed pack labels source concept
        # Create a book where 'custom-exceptions' has NO native material, but 'exception-throwing' has strong chunks.
        chunks = [
            {
                "chunk_id": f"{self.pdfshort}_chunk_00020",
                "pdf": self.pdfshort,
                "page_start": 40,
                "page_end": 40,
                "text": "Throwing exceptions using throw new IllegalArgumentException when argument is invalid.",
                "word_count": 12,
            },
            {
                "chunk_id": f"{self.pdfshort}_chunk_00021",
                "pdf": self.pdfshort,
                "page_start": 41,
                "page_end": 41,
                "text": "Exception throwing allows signaling errors up the call stack with throw statement and custom exceptions subclass.",
                "word_count": 16,
            },
            {
                "chunk_id": f"{self.pdfshort}_chunk_00022",
                "pdf": self.pdfshort,
                "page_start": 42,
                "page_end": 42,
                "text": "More exception throwing examples with throws clause on method signature and custom exceptions class.",
                "word_count": 15,
            },
        ]
        self._setup_mock_index(chunks)

        # custom-exceptions borrows from exception-throwing via PACK_ALIASES
        pack = build_pack(self.pdfshort, "custom-exceptions", batch_idx=0, max_words=1000, work_dir=self.temp_dir, allow_borrow=True)
        self.assertTrue(pack.borrowed)
        self.assertEqual(pack.source_concept, "exception-throwing")
        self.assertTrue(len(pack) > 0)
        # Borrowed chunks in the pack must label their source concept
        borrowed = [c for c in pack if c["is_borrowed"]]
        self.assertTrue(len(borrowed) >= 1)
        for c in borrowed:
            self.assertEqual(c["source_concept"], "exception-throwing")
            self.assertTrue(c["is_borrowed"])


class TestPhase2DFix3Rules(unittest.TestCase):
    def setUp(self):
        from tools.question_bank.bank_pack import _INDEX_CACHE, _CHUNKS_CACHE, _PAGE_HINTS_CACHE
        _INDEX_CACHE.clear()
        _CHUNKS_CACHE.clear()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.pdfshort = "test_fix3_book"
        self.pdf_dir = self.temp_dir / self.pdfshort
        self.pdf_dir.mkdir(parents=True)

    def tearDown(self):
        from tools.question_bank.bank_pack import _INDEX_CACHE, _CHUNKS_CACHE
        _INDEX_CACHE.clear()
        _CHUNKS_CACHE.clear()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_mock_index(self, chunks):
        index = BM25Index(k1=1.5, b=0.75)
        for c in chunks:
            index.add_document(c["chunk_id"], c["text"])
        index.finalize()
        index.save(self.pdf_dir / "bm25.pkl")

        with open(self.pdf_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c) + "\n")

    def test_title_word_interface_is_core_for_interface_basics(self):
        # Test (a): title word 'interface' is CORE for interface-basics despite high df
        anchors = ["interface", "basics", "contract", "implements"]
        df = {"interface": 1000, "basics": 1, "contract": 2, "implements": 50}
        core, support = split_anchors("interface-basics", anchors, df=df, total_chunks=1000)

        # 'interface' is title/tag word -> CORE
        self.assertIn("interface", core)
        # 'implements' is in ANCHOR_EXTRA -> CORE
        self.assertIn("implements", core)
        # 'basics' is in FILLER_WORDS -> SUPPORT
        self.assertIn("basics", support)
        # 'contract' is in LOOSE_WORDS -> SUPPORT
        self.assertIn("contract", support)

    def test_contract_cleanup_alone_never_make_chunk_strong(self):
        # Test (b): contract/cleanup alone never make a chunk STRONG
        chunks = [
            # Chunk with contract and cleanup repeated (df < 3% words)
            {
                "chunk_id": f"{self.pdfshort}_chunk_00101",
                "pdf": self.pdfshort,
                "page_start": 10,
                "page_end": 10,
                "text": "Discussion on contract contract contract and cleanup cleanup cleanup in software architecture.",
                "word_count": 13,
            },
            # Chunk with real CORE anchor
            {
                "chunk_id": f"{self.pdfshort}_chunk_00102",
                "pdf": self.pdfshort,
                "page_start": 11,
                "page_end": 11,
                "text": "Interface in Java specifies an interface and implements keyword for classes.",
                "word_count": 11,
            },
            {
                "chunk_id": f"{self.pdfshort}_chunk_00103",
                "pdf": self.pdfshort,
                "page_start": 12,
                "page_end": 12,
                "text": "Another interface declaration with implements clause.",
                "word_count": 7,
            },
        ]
        self._setup_mock_index(chunks)

        pack = build_pack(self.pdfshort, "interface-basics", batch_idx=0, max_words=1000, work_dir=self.temp_dir)
        c101 = next(c for c in pack if c["chunk_id"] == f"{self.pdfshort}_chunk_00101")
        self.assertFalse(c101["is_strong"], "contract/cleanup alone must NEVER make a chunk strong")

    def test_borrowed_chunk_without_target_core_anchor_is_rejected(self):
        # Test (c): borrowed chunk without target CORE anchor is rejected
        # target concept: dynamic-method-dispatch, alias: method-overriding
        chunks = [
            # Chunk for method-overriding that does NOT contain any target CORE anchor
            {
                "chunk_id": f"{self.pdfshort}_chunk_00201",
                "pdf": self.pdfshort,
                "page_start": 30,
                "page_end": 30,
                "text": "Method overriding allows subclass to redefine behavior with @Override annotation assertions.",
                "word_count": 11,
            },
            # Chunk for method-overriding that DOES contain a target CORE anchor ('dispatch' / 'late binding')
            {
                "chunk_id": f"{self.pdfshort}_chunk_00202",
                "pdf": self.pdfshort,
                "page_start": 31,
                "page_end": 31,
                "text": "Method overriding causes dynamic method dispatch with late binding of overridden method at runtime.",
                "word_count": 14,
            },
            {
                "chunk_id": f"{self.pdfshort}_chunk_00203",
                "pdf": self.pdfshort,
                "page_start": 32,
                "page_end": 32,
                "text": "More method overriding examples with super call.",
                "word_count": 8,
            },
        ]
        self._setup_mock_index(chunks)

        pack = build_pack(self.pdfshort, "dynamic-method-dispatch", batch_idx=0, max_words=1000, work_dir=self.temp_dir, allow_borrow=True)
        chunk_ids_in_pack = [c["chunk_id"] for c in pack]

        # Chunk 202 has 'late binding' / 'dispatch' (target CORE anchors) -> accepted
        self.assertIn(f"{self.pdfshort}_chunk_00202", chunk_ids_in_pack)
        # Chunk 201 has no target CORE anchor -> rejected from borrowed strong pack
        borrowed_201 = [c for c in pack if c["chunk_id"] == f"{self.pdfshort}_chunk_00201" and c["is_borrowed"]]
        self.assertEqual(len(borrowed_201), 0, "Chunk without target CORE anchor must be rejected from borrowing")

    def test_cap_strong_div_2_enforced(self):
        # Test (d): cap strong // 2 enforced (e.g. data-hiding with 3 strong gets at most 1)
        mock_data = {
            "book1": {
                c: {
                    "coverage": 100.0,
                    "strong": 3 if c == "data-hiding" else 20,
                    "weak": False,
                    "heading_hits": 0,
                }
                for c in CONCEPTS
            }
        }
        quotas = allocate_quotas(mock_data, target_per_pdf=84, min_total=4, max_per_concept=6)
        dh_batches = quotas["book1"]["data-hiding"]["batches"]
        self.assertLessEqual(dh_batches, 1, f"data-hiding with 3 strong must get at most 1 batch, got {dh_batches}")

    def test_page_hint_ordering(self):
        # Test (e): page hint puts hinted chunk first (marked [HINT], treated as STRONG)
        hints_file = self.temp_dir / "hints.json"
        with open(hints_file, "w", encoding="utf-8") as f:
            json.dump({self.pdfshort: {"method-overriding": [[50, 50]]}}, f)

        chunks = [
            # High-score non-hinted chunk on page 10
            {
                "chunk_id": f"{self.pdfshort}_chunk_00301",
                "pdf": self.pdfshort,
                "page_start": 10,
                "page_end": 10,
                "text": "Method overriding method overriding method overriding redefine redefine overrides @override.",
                "word_count": 11,
            },
            # Hinted chunk on page 50 with lower raw score
            {
                "chunk_id": f"{self.pdfshort}_chunk_00302",
                "pdf": self.pdfshort,
                "page_start": 50,
                "page_end": 50,
                "text": "Chapter on method overriding basics.",
                "word_count": 5,
            },
            {
                "chunk_id": f"{self.pdfshort}_chunk_00303",
                "pdf": self.pdfshort,
                "page_start": 12,
                "page_end": 12,
                "text": "Additional method overriding notes.",
                "word_count": 4,
            },
        ]
        self._setup_mock_index(chunks)

        pack = build_pack(
            self.pdfshort,
            "method-overriding",
            batch_idx=0,
            max_words=1000,
            work_dir=self.temp_dir,
            hints_file=hints_file,
        )
        self.assertTrue(len(pack) > 0)
        # Hinted chunk on page 50 must be first chunk in the pack!
        self.assertEqual(pack[0]["chunk_id"], f"{self.pdfshort}_chunk_00302")
        self.assertTrue(pack[0]["is_hint"])
        self.assertTrue(pack[0]["is_strong"])


class TestQuotaMathematics(unittest.TestCase):
    def test_quota_allocation_rules(self):
        concepts = list(CONCEPTS.keys())
        mock_data = {"pdfA": {}, "pdfB": {}, "pdfC": {}}

        for i, c in enumerate(concepts):
            mock_data["pdfA"][c] = {
                "coverage": 30.0 if i == 0 else 100.0 + (i * 2),
                "strong": 2 if i == 0 else 10 + i,
                "weak": (i == 0),
            }
            mock_data["pdfB"][c] = {
                "coverage": 120.0 + (i * 1.5),
                "strong": 15,
                "weak": False,
            }
            mock_data["pdfC"][c] = {
                "coverage": 90.0 + (i * 1.2),
                "strong": 12,
                "weak": False,
            }

        quotas = allocate_quotas(mock_data, target_per_pdf=84, min_total=4, max_per_concept=6)

        # Rule 1: Exactly 84 batches per PDF
        for pdf in ["pdfA", "pdfB", "pdfC"]:
            total_pdf_batches = sum(quotas[pdf][c]["batches"] for c in concepts)
            self.assertEqual(total_pdf_batches, 84, f"{pdf} must have exactly 84 batches")

        # Rule 2: Weak concept gets 0 native batches in that PDF
        self.assertEqual(quotas["pdfA"][concepts[0]]["batches"], 0, "Weak concept must get 0 batches in pdfA")

        # Rule 3: Non-weak concepts get between 1 and 6 batches
        for pdf in ["pdfA", "pdfB", "pdfC"]:
            for c in concepts:
                if not mock_data[pdf][c]["weak"]:
                    b = quotas[pdf][c]["batches"]
                    self.assertGreaterEqual(b, 1)
                    self.assertLessEqual(b, 6)

        # Rule 4: Total batches across all PDFs is 252
        totals = {c: sum(quotas[p][c]["batches"] for p in ["pdfA", "pdfB", "pdfC"]) for c in concepts}
        self.assertEqual(sum(totals.values()), 252)


if __name__ == "__main__":
    unittest.main()

