"""
=============================================================================
EduGen - Unit Tests for Question Bank Preparation Tools
=============================================================================
Tests:
  1. Running header / footer detection and removal
  2. Text chunking (target words, overlap, page gap limits, formatting)
  3. BM25 indexing, scoring, and serialization
  4. Source pack rotation by batch index
  5. Quota distribution maths (weak concepts, min/max limits, totals)

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
from tools.question_bank.bank_pack import build_pack
from tools.question_bank.bank_prepare import (
    BM25Index,
    chunk_pages,
    clean_page_text,
    detect_running_headers_footers,
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

        detected = detect_running_headers_footers(pages, threshold=0.30)
        self.assertIn("RUNNING HEADER LINE - CONFIDENTIAL", detected)
        self.assertIn("RUNNING FOOTER - COPYRIGHT 2026", detected)
        # Content line or code brace should not be detected as header/footer
        self.assertNotIn("public class Example1 {", detected)
        self.assertNotIn("}", detected)

    def test_clean_page_text(self):
        running = {"HEADER TO REMOVE", "FOOTER TO REMOVE"}
        text = "HEADER TO REMOVE\nSome real content line.\n    int x = 42;\nFOOTER TO REMOVE"
        cleaned = clean_page_text(text, running)
        self.assertNotIn("HEADER TO REMOVE", cleaned)
        self.assertNotIn("FOOTER TO REMOVE", cleaned)
        self.assertIn("Some real content line.", cleaned)
        self.assertIn("    int x = 42;", cleaned)


class TestChunking(unittest.TestCase):
    def test_chunk_word_count_and_overlap(self):
        # Build 5 pages with 100 words per page
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

        # Check page bounds and word counts
        for c in chunks:
            self.assertGreaterEqual(c["page_end"], c["page_start"])
            self.assertGreater(c["word_count"], 0)
            self.assertTrue(c["chunk_id"].startswith("test_book_chunk_"))

        # Check that consecutive chunks have overlap
        words_c0 = set(chunks[0]["text"].split())
        words_c1 = set(chunks[1]["text"].split())
        overlap = words_c0.intersection(words_c1)
        self.assertGreater(len(overlap), 0, "Consecutive chunks should have overlapping vocabulary")

    def test_chunk_page_gap_constraint(self):
        # Pages with a gap > 2 pages (page 1 and page 5, gap = 4)
        pages = [
            {"page": 1, "text": "Short intro on page one."},
            {"page": 5, "text": "Content after page gap of four pages."},
        ]
        chunks = chunk_pages(pages, "test_gap", target_words=100, overlap_words=20, max_page_gap=2)
        # The two pages must not be combined into the same chunk because gap > 2
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

        scores_exc = self.index.score("try catch checked exceptions")
        self.assertEqual(scores_exc[0][0], "doc3", "Doc 3 must rank highest for exception query")

    def test_save_and_load(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            save_path = temp_dir / "test_bm25.pkl"
            self.index.save(save_path)
            loaded = BM25Index.load(save_path)
            self.assertEqual(loaded.doc_count, self.index.doc_count)
            self.assertEqual(loaded.avg_doc_len, self.index.avg_doc_len)

            orig_scores = self.index.score("polymorphism")
            loaded_scores = loaded.score("polymorphism")
            self.assertEqual(orig_scores, loaded_scores)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestSourcePackRotation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.pdfshort = "synthetic_pdf"
        pdf_dir = self.temp_dir / self.pdfshort
        pdf_dir.mkdir(parents=True)

        # Create 12 chunks
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
        # Batch 0 starts at rank 0
        pack0 = build_pack(self.pdfshort, "method-overriding", batch_idx=0, max_words=300, work_dir=self.temp_dir)
        # Batch 1 starts at rank 4
        pack1 = build_pack(self.pdfshort, "method-overriding", batch_idx=1, max_words=300, work_dir=self.temp_dir)

        self.assertTrue(len(pack0) > 0)
        self.assertTrue(len(pack1) > 0)
        # The top chunk of batch 0 should differ from the top chunk of batch 1
        self.assertNotEqual(pack0[0]["chunk_id"], pack1[0]["chunk_id"])


class TestQuotaMathematics(unittest.TestCase):
    def test_quota_allocation_rules(self):
        # 3 mock PDFs with coverage for all 44 concepts
        concepts = list(CONCEPTS.keys())
        mock_data = {"pdfA": {}, "pdfB": {}, "pdfC": {}}

        for i, c in enumerate(concepts):
            # pdfA has weak coverage for concept 0
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
            self.assertEqual(sum(quotas[pdf].values()), 84, f"{pdf} must have exactly 84 batches")

        # Rule 2: Weak concept gets 0 in that PDF
        self.assertEqual(quotas["pdfA"][concepts[0]], 0, "Weak concept must get 0 batches in pdfA")

        # Rule 3: Non-weak concepts get between 1 and 6 batches
        for pdf in ["pdfA", "pdfB", "pdfC"]:
            for c in concepts:
                if not mock_data[pdf][c]["weak"]:
                    self.assertGreaterEqual(quotas[pdf][c], 1)
                    self.assertLessEqual(quotas[pdf][c], 6)

        # Rule 4: Total batches across all PDFs is 252 and every concept has >= 4
        totals = {c: sum(quotas[p][c] for p in ["pdfA", "pdfB", "pdfC"]) for c in concepts}
        self.assertEqual(sum(totals.values()), 252)
        for c in concepts:
            self.assertGreaterEqual(totals[c], 4, f"Concept {c} should reach at least 4 batches total")


if __name__ == "__main__":
    unittest.main()
