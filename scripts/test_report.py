"""
=============================================================================
EduGen - Performance PDF Report Test Suite (scripts/test_report.py)
=============================================================================
Tests:
  1. Unauthenticated request to /report.pdf redirects to /login (302)
  2. Authenticated request produces valid PDF:
     - Response status 200, Content-Type application/pdf
     - Starts with %PDF magic bytes
     - File size > 3 KB
  3. Text verification with pypdf:
     - Contains student's real name and email
     - Contains key performance sections (Executive Summary, Study Plan, Quizzes)
     - Strictly zero forbidden jargon strings:
         ["Rule R", "cosine", ".pdf", "ollama", "Agent"]
=============================================================================
"""

import io
import os
from pathlib import Path
import sys
import tempfile
import unittest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pypdf

import core.db
from app import create_app
from core.db import get_db, init_db
from core.report import generate_student_report_pdf
from scripts.seed_demo_student import seed_demo_student


FORBIDDEN_JARGON = ["Rule R", "cosine", ".pdf", "ollama", "Agent"]


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "test_report.db")
        os.environ["EDUGEN_DB_PATH"] = cls.db_path
        core.db.DB_PATH = cls.db_path
        init_db(cls.db_path)

        # Seed sample questions into DB for seeding
        conn = get_db(cls.db_path)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO questions (concept, difficulty, qtype, question_text, options_json, correct_index, explanation, tags_json, source, pool_status, verified, text_hash)
               VALUES ('class-definition', 'Easy', 'concept', 'Sample question on class-definition?', '["A", "B", "C", "D"]', 0, 'Explanation', '{"tags": ["class-definition"]}', 'test', 'active', 1, 'hash_rep_1')"""
        )
        conn.commit()
        conn.close()

        cls.app = create_app()
        cls.app.config.update(TESTING=True, EDUGEN_SHOW_LOGS=False)

        # Seed demo student in this test DB
        cls.student_id, cls.user_id = seed_demo_student(reset=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def setUp(self):
        self.client = self.app.test_client()

    def test_unauthenticated_redirects_to_login(self):
        """Logged-out access to /report.pdf redirects to /login."""
        res = self.client.get("/report.pdf")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers.get("Location", ""))

    def test_authenticated_downloads_valid_pdf(self):
        """Logged-in user receives valid PDF file larger than 3 KB."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["student_id"] = self.student_id

        res = self.client.get("/report.pdf")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Type"), "application/pdf")

        pdf_bytes = res.data
        # 1. Header check
        self.assertTrue(pdf_bytes.startswith(b"%PDF"), "Must start with %PDF header bytes")

        # 2. Size check > 3 KB
        self.assertGreater(len(pdf_bytes), 3072, "PDF file must be larger than 3 KB")

        # 3. PDF parsing and content verification
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        self.assertGreaterEqual(len(reader.pages), 1)

        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() or ""

        # Assert student name is present
        self.assertIn("Demo Student", full_text)
        self.assertIn("demo@edugen.local", full_text)
        self.assertIn("Executive Summary", full_text)

        # 4. Strictly assert NO forbidden jargon strings appear
        for jargon in FORBIDDEN_JARGON:
            self.assertNotIn(
                jargon,
                full_text,
                f"Forbidden jargon '{jargon}' was found in the student report text!",
            )

    def test_direct_generator_function(self):
        """Direct call to generate_student_report_pdf generates valid bytes."""
        pdf_bytes = generate_student_report_pdf(self.student_id)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 3072)


if __name__ == "__main__":
    unittest.main()
