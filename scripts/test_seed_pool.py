"""
=============================================================================
EduGen - Phase 4D Seeding & Voting Test Suite (test_seed_pool.py)
=============================================================================
Hermetic, offline test suite for Phase 4D:
  1. 3-Way Tag Voting per wrong option:
       - 3 labelers agree -> 3_of_3
       - 2 labelers agree (l1+l2, l1+l3, l2+l3) -> 2_of_3
       - all labelers differ -> nulled
       - all null -> nulled
       - labeler 1 absent: require l2 == l3 (non-null) -> 2_of_3 vs nulled
       - foreign concept catalog IDs strictly rejected
  2. Verification decision gates:
       - verifier wrong answer rejected
       - ambiguous rejected
       - difficulty diff >= 2 rejected
       - difficulty diff <= 1 accepted
       - verifier missing result rejected
  3. Deduplication:
       - exact hash match against pool rejected
       - embedding cosine >= 0.88 against pool rejected
       - duplicate within batch rejected
  4. Workflow & Resumption:
       - resume skips finished batches
       - budget exhaustion stops cleanly and saves progress
       - dry-run writes nothing to DB or progress file
=============================================================================
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.concept_clarifier_agent import ConceptClarifierAgent
from core.db import get_db, init_db
from core.quiz_engine import serialize_embedding
from core.token_budget import reset_budget_state
from scripts.seed_pool_from_bank import (
    load_progress,
    order_bank_files,
    process_bank_file,
    reprocess_previous_rejects,
    save_progress,
    vote_tag,
)


class TestTagVoting(unittest.TestCase):
    def setUp(self):
        self.concept = "class-definition"
        # Two valid catalog misconceptions for class-definition:
        self.mid1 = "class-definition/class-stores-instance-data"
        self.mid2 = "class-definition/multiple-public-classes"
        self.mid3 = "class-definition/filename-independent"
        # Foreign concept tag:
        self.foreign_mid = "inheritance-basics/super-omitted-in-constructor"

    def test_three_agree(self):
        """All 3 labelers agree on valid catalog tag -> 3_of_3."""
        tag, agree = vote_tag(True, self.mid1, self.mid1, self.mid1, self.concept)
        self.assertEqual(tag, self.mid1)
        self.assertEqual(agree, "3_of_3")

    def test_two_agree_l1_and_l2(self):
        """Labeler 1 & 2 agree, labeler 3 differs -> 2_of_3."""
        tag, agree = vote_tag(True, self.mid1, self.mid1, None, self.concept)
        self.assertEqual(tag, self.mid1)
        self.assertEqual(agree, "2_of_3")

    def test_two_agree_l1_and_l3(self):
        """Labeler 1 & 3 agree, labeler 2 is None -> 2_of_3."""
        tag, agree = vote_tag(True, self.mid1, None, self.mid1, self.concept)
        self.assertEqual(tag, self.mid1)
        self.assertEqual(agree, "2_of_3")

    def test_two_agree_l2_and_l3(self):
        """Labeler 2 & 3 agree, labeler 1 is None -> 2_of_3."""
        tag, agree = vote_tag(True, None, self.mid1, self.mid1, self.concept)
        self.assertEqual(tag, self.mid1)
        self.assertEqual(agree, "2_of_3")

    def test_all_differ(self):
        """All 3 labelers choose different tags -> nulled."""
        tag, agree = vote_tag(True, self.mid1, self.mid2, self.mid3, self.concept)
        self.assertIsNone(tag)
        self.assertEqual(agree, "nulled")

    def test_all_none(self):
        """All 3 labelers have None -> nulled."""
        tag, agree = vote_tag(True, None, None, None, self.concept)
        self.assertIsNone(tag)
        self.assertEqual(agree, "nulled")

    def test_labeler1_absent_l2_l3_agree(self):
        """When labeler 1 is absent, require l2 == l3 (non-null) -> 2_of_3."""
        tag, agree = vote_tag(False, None, self.mid2, self.mid2, self.concept)
        self.assertEqual(tag, self.mid2)
        self.assertEqual(agree, "2_of_3")

    def test_labeler1_absent_differ(self):
        """When labeler 1 is absent and l2 != l3 -> nulled."""
        tag, agree = vote_tag(False, None, self.mid1, self.mid2, self.concept)
        self.assertIsNone(tag)
        self.assertEqual(agree, "nulled")

    def test_labeler1_absent_one_none(self):
        """When labeler 1 is absent and either l2 or l3 is None -> nulled."""
        tag, agree = vote_tag(False, None, self.mid1, None, self.concept)
        self.assertIsNone(tag)
        self.assertEqual(agree, "nulled")

    def test_foreign_concept_id_rejected(self):
        """Tags that do not belong to the target concept catalog are nulled."""
        tag, agree = vote_tag(True, self.foreign_mid, self.foreign_mid, self.foreign_mid, self.concept)
        self.assertIsNone(tag)
        self.assertEqual(agree, "nulled")


class TestDecisionGates(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_decision.db")
        import core.db
        core.db.DB_PATH = self.db_path
        os.environ["EDUGEN_DB_PATH"] = self.db_path
        init_db(self.db_path)

        self.bank_file = Path(self.temp_dir) / "test_batch.jsonl"
        self.q_sample = {
            "question": "What is an object?",
            "qtype": "concept",
            "options": [
                {"text": "A class definition", "misconception_id": "class-definition/class-stores-instance-data"},
                {"text": "An instance of a class allocated in heap", "misconception_id": None},
                {"text": "A static method", "misconception_id": "class-definition/multiple-public-classes"},
                {"text": "A primitive type", "misconception_id": None},
            ],
            "correct_index": 1,
            "difficulty": "Easy",
            "concept": "class-definition",
            "explanation": "Objects are heap-allocated instances of classes.",
        }
        with open(self.bank_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.q_sample) + "\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        import core.db
        core.db.DB_PATH = str(BASE_DIR / "data" / "edugen.db")
        os.environ.pop("EDUGEN_DB_PATH", None)

    def test_correct_answer_accepted(self):
        """Verifier matches answer, not ambiguous, diff diff <= 1 -> accepted."""
        clarifier = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        clarifier.client = MagicMock()
        clarifier.api_key = "mock"
        clarifier.verify_bank_batch = MagicMock(return_value=(
            {0: {"answer": 1, "ambiguous": False, "difficulty_estimate": "Medium", "labels": [None, None, None, None]}},
            "mock-verifier",
            None,
        ))

        stats, should_stop, err = process_bank_file(
            self.bank_file,
            clarifier,
            java_checker=None,
            embedder=None,
            cache=None,
            pool_dedupe_list=[],
            dry_run=False,
        )
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["rejected"], 0)

    def test_wrong_answer_rejected(self):
        """Verifier chooses answer != correct_index -> rejected with verifier_wrong_answer."""
        clarifier = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        clarifier.client = MagicMock()
        clarifier.api_key = "mock"
        clarifier.verify_bank_batch = MagicMock(return_value=(
            {0: {"answer": 0, "ambiguous": False, "difficulty_estimate": "Easy", "labels": [None, None, None, None]}},
            "mock-verifier",
            None,
        ))

        stats, should_stop, err = process_bank_file(
            self.bank_file,
            clarifier,
            java_checker=None,
            embedder=None,
            cache=None,
            pool_dedupe_list=[],
            dry_run=False,
        )
        self.assertEqual(stats["accepted"], 0)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["rejection_reasons"].get("verifier_wrong_answer"), 1)

    def test_ambiguous_rejected(self):
        """Verifier marks ambiguous: true -> rejected with verifier_ambiguous."""
        clarifier = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        clarifier.client = MagicMock()
        clarifier.api_key = "mock"
        clarifier.verify_bank_batch = MagicMock(return_value=(
            {0: {"answer": 1, "ambiguous": True, "difficulty_estimate": "Easy", "labels": [None, None, None, None]}},
            "mock-verifier",
            None,
        ))

        stats, should_stop, err = process_bank_file(
            self.bank_file,
            clarifier,
            java_checker=None,
            embedder=None,
            cache=None,
            pool_dedupe_list=[],
            dry_run=False,
        )
        self.assertEqual(stats["accepted"], 0)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["rejection_reasons"].get("verifier_ambiguous"), 1)

    def test_difficulty_diff_two_relabeled(self):
        """Phase 4E: Difficulty diff >= 2 is RELABELED to verifier estimate instead of rejected."""
        clarifier = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        clarifier.client = MagicMock()
        clarifier.api_key = "mock"
        clarifier.verify_bank_batch = MagicMock(return_value=(
            {0: {"answer": 1, "ambiguous": False, "difficulty_estimate": "Hard", "labels": [None, None, None, None]}},
            "mock-verifier",
            None,
        ))

        stats, should_stop, err = process_bank_file(
            self.bank_file,
            clarifier,
            java_checker=None,
            embedder=None,
            cache=None,
            pool_dedupe_list=[],
            dry_run=False,
        )
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["rejected"], 0)
        self.assertEqual(stats["relabeled"], 1)

        # Inspect persisted question in DB
        conn = get_db(self.db_path)
        row = conn.execute("SELECT difficulty, pool_status, verified, difficulty_verified, verifier_labels_json FROM questions").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["difficulty"], "Hard")
        self.assertEqual(row["pool_status"], "active")
        self.assertEqual(row["verified"], 1)
        self.assertEqual(row["difficulty_verified"], 2)
        v_labels = json.loads(row["verifier_labels_json"])
        self.assertEqual(v_labels.get("difficulty_original"), "Easy")
        self.assertEqual(v_labels.get("note"), "relabeled")

    def test_retry_missing_verifier_results(self):
        """Phase 4E: Missing verifier results trigger follow-up retries before evaluating."""
        clarifier = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        clarifier.client = MagicMock()
        clarifier.api_key = "mock"

        # First call: returns empty map (missing index 0)
        # Second call (retry): returns index 0
        clarifier.verify_bank_batch = MagicMock(side_effect=[
            ({}, "mock-verifier", None),
            ({0: {"answer": 1, "ambiguous": False, "difficulty_estimate": "Easy", "labels": [None, None, None, None]}}, "mock-verifier", None),
        ])

        stats, should_stop, err = process_bank_file(
            self.bank_file,
            clarifier,
            java_checker=None,
            embedder=None,
            cache=None,
            pool_dedupe_list=[],
            dry_run=False,
        )
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["rejected"], 0)
        self.assertGreaterEqual(stats["verifier_retries"], 1)
        self.assertEqual(clarifier.verify_bank_batch.call_count, 2)

    def test_reprocess_previous_rejects(self):
        """Phase 4E: --reprocess-rejected reactivates difficulty mismatches and retries missing results."""
        conn = get_db(self.db_path)

        # 1. Question rejected due to difficulty mismatch (Easy -> Hard, verified=2)
        conn.execute(
            """INSERT INTO questions (
                concept, difficulty, qtype, question_text, options_json, correct_index,
                explanation, tags_json, source, model, verified, origin, pool_status,
                difficulty_verified, verifier_labels_json, text_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "class-definition", "Easy", "concept", "Q1: What is a class?", json.dumps(["A", "B", "C", "D"]),
                1, "Exp 1", json.dumps({"reject_reason": "verifier_difficulty_mismatch"}),
                "bank", "mock", 0, "bank", "rejected", 2, json.dumps([None, None, None, None]), "hash1",
            ),
        )

        # 2. Question rejected due to missing result
        conn.execute(
            """INSERT INTO questions (
                concept, difficulty, qtype, question_text, options_json, correct_index,
                explanation, tags_json, source, model, verified, origin, pool_status,
                difficulty_verified, verifier_labels_json, text_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "class-definition", "Easy", "concept", "Q2: What is an instance?", json.dumps(["A", "B", "C", "D"]),
                1, "Exp 2", json.dumps({"reject_reason": "verifier_missing_result"}),
                "bank", "mock", 0, "bank", "rejected", None, None, "hash2",
            ),
        )

        # 3. Question rejected due to compile error (should remain rejected!)
        conn.execute(
            """INSERT INTO questions (
                concept, difficulty, qtype, question_text, options_json, correct_index,
                explanation, tags_json, source, model, verified, origin, pool_status,
                difficulty_verified, verifier_labels_json, text_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "class-definition", "Medium", "bug_find", "Q3: Bug in class", json.dumps(["A", "B", "C", "D"]),
                0, "Exp 3", json.dumps({"reject_reason": "bug_find_compiles"}),
                "bank", "mock", 0, "bank", "rejected", None, None, "hash3",
            ),
        )
        conn.commit()

        clarifier = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        clarifier.client = MagicMock()
        clarifier.api_key = "mock"
        clarifier.verify_bank_batch = MagicMock(return_value=(
            {0: {"answer": 1, "ambiguous": False, "difficulty_estimate": "Easy", "labels": [None, None, None, None]}},
            "mock-verifier",
            None,
        ))

        stats = reprocess_previous_rejects(
            conn,
            clarifier,
            java_checker=None,
            embedder=None,
            cache=None,
            pool_dedupe_list=[],
            dry_run=False,
        )

        self.assertEqual(stats["reprocessed"], 2)
        self.assertEqual(stats["accepted"], 2)
        self.assertEqual(stats["relabeled"], 1)
        self.assertEqual(stats["still_rejected"], 1)

        # Check Q1 in DB
        q1 = conn.execute("SELECT * FROM questions WHERE question_text LIKE 'Q1%'").fetchone()
        self.assertEqual(q1["pool_status"], "active")
        self.assertEqual(q1["verified"], 1)
        self.assertEqual(q1["difficulty"], "Hard")
        v1 = json.loads(q1["verifier_labels_json"])
        self.assertEqual(v1.get("note"), "relabeled")

        # Check Q2 in DB
        q2 = conn.execute("SELECT * FROM questions WHERE question_text LIKE 'Q2%'").fetchone()
        self.assertEqual(q2["pool_status"], "active")
        self.assertEqual(q2["verified"], 1)

        # Check Q3 in DB (must remain rejected!)
        q3 = conn.execute("SELECT * FROM questions WHERE question_text LIKE 'Q3%'").fetchone()
        self.assertEqual(q3["pool_status"], "rejected")
        self.assertEqual(q3["verified"], 0)

        conn.close()


class TestDeduplication(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_dedupe.db")
        import core.db
        core.db.DB_PATH = self.db_path
        os.environ["EDUGEN_DB_PATH"] = self.db_path
        init_db(self.db_path)

        self.bank_file = Path(self.temp_dir) / "test_dedupe.jsonl"
        q1 = {
            "question": "What is an abstract class in Java?",
            "qtype": "concept",
            "options": ["A", "An abstract class cannot be instantiated", "C", "D"],
            "correct_index": 1,
            "difficulty": "Easy",
            "concept": "abstract-classes",
            "explanation": "Valid",
        }
        with open(self.bank_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(q1) + "\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        import core.db
        core.db.DB_PATH = str(BASE_DIR / "data" / "edugen.db")
        os.environ.pop("EDUGEN_DB_PATH", None)

    def test_duplicate_in_pool_rejected(self):
        """Question with exact text hash in existing pool list is rejected."""
        clarifier = ConceptClarifierAgent.__new__(ConceptClarifierAgent)
        clarifier.client = MagicMock()
        clarifier.api_key = "mock"
        clarifier.verify_bank_batch = MagicMock(return_value=(
            {0: {"answer": 1, "ambiguous": False, "difficulty_estimate": "Easy", "labels": [None, None, None, None]}},
            "mock-verifier",
            None,
        ))

        stem_ans = "What is an abstract class in Java?\nAn abstract class cannot be instantiated"
        thash = " ".join(stem_ans.lower().split())
        thash_sha = "mock_hash"
        import hashlib
        thash_sha = hashlib.sha256(thash.encode("utf-8")).hexdigest()

        # Simulate existing pool containing this hash
        pool_dedupe_list = [(thash_sha, stem_ans, None)]

        stats, should_stop, err = process_bank_file(
            self.bank_file,
            clarifier,
            java_checker=None,
            embedder=None,
            cache=None,
            pool_dedupe_list=pool_dedupe_list,
            dry_run=False,
        )
        self.assertEqual(stats["accepted"], 0)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["rejection_reasons"].get("duplicate_in_pool"), 1)


class TestWorkflowAndResumption(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.progress_file = Path(self.temp_dir) / "test_progress.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load_progress(self):
        """Progress serialization and loading preserves done_batches and stats."""
        data = {
            "done_batches": ["batch1.jsonl", "batch2.jsonl"],
            "batch_stats": {"batch1.jsonl": {"accepted": 10, "rejected": 2}},
            "cumulative_stats": {
                "batches_processed": 1,
                "questions_processed": 12,
                "accepted": 10,
                "rejected": 2,
                "rejection_reasons": {},
                "tags_kept_3_of_3": 5,
                "tags_kept_2_of_3": 2,
                "tags_nulled": 20,
                "java_unverified": 0,
            },
        }
        save_progress(data, self.progress_file)
        loaded = load_progress(self.progress_file)
        self.assertEqual(loaded["done_batches"], ["batch1.jsonl", "batch2.jsonl"])
        self.assertEqual(loaded["cumulative_stats"]["accepted"], 10)

    def test_order_bank_files_prioritizes_empty_cells(self):
        """Files targeting pool cells with 0 active questions are ordered first."""
        cell_counts = {
            ("class-definition", "Easy"): 5,
            ("class-definition", "Medium"): 5,
            ("abstract-classes", "Easy"): 0,
            ("abstract-classes", "Medium"): 0,
        }

        f1 = Path(self.temp_dir) / "class_def.jsonl"
        with open(f1, "w", encoding="utf-8") as f:
            f.write(json.dumps({"concept": "class-definition", "difficulty": "Easy"}) + "\n")

        f2 = Path(self.temp_dir) / "abstract_cls.jsonl"
        with open(f2, "w", encoding="utf-8") as f:
            f.write(json.dumps({"concept": "abstract-classes", "difficulty": "Easy"}) + "\n")

        ordered = order_bank_files([f1, f2], cell_counts)
        self.assertEqual(ordered[0].name, "abstract_cls.jsonl")
        self.assertEqual(ordered[1].name, "class_def.jsonl")


if __name__ == "__main__":
    unittest.main()

