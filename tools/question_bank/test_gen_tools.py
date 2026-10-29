"""
=============================================================================
EduGen - Unit Tests for MCQ Generation Tooling (Phase 2E-a)
=============================================================================
Tests gen_plan, gen_next, and gen_save:
  - Plan structure, 50 entries, pilot order, round 2 concepts.
  - Brief formatting, catalog misconceptions inclusion, verbatim rules.
  - Validation acceptance and rejection on every specific rule.
=============================================================================
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS
from tools.question_bank.gen_next import RULES_TEXT, format_brief, get_next_pending_entries
from tools.question_bank.gen_plan import PILOT_CONCEPTS, ROUND2_CONCEPTS, build_generation_plan
from tools.question_bank.gen_save import install_batch, validate_batch


def make_valid_batch(concept: str = "method-overriding", pdf: str = "JavaNotesForProfessionals", page: int = 305) -> list[dict]:
    """Creates a strictly valid 12-MCQ batch conforming to all Phase 2E-a rules."""
    records = []
    difficulties = ["Easy"] * 4 + ["Medium"] * 4 + ["Hard"] * 4
    # Positions distributed 3 each across 0, 1, 2, 3 (each <= 5)
    positions = [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]

    valid_mids = [
        "method-overriding/static-methods-override",
        "method-overriding/can-reduce-visibility",
        "method-overriding/override-annotation-required",
    ]

    for i in range(12):
        diff = difficulties[i]
        c_pos = positions[i]
        qtype = "code_output" if i < 3 else ("bug_find" if i == 3 else "concept")

        # 4 options, c_pos has null, others have distinct misconception IDs
        options = []
        m_idx = 0
        for opt_idx in range(4):
            if opt_idx == c_pos:
                options.append({"text": f"Correct answer text for question {i+1}", "misconception_id": None})
            else:
                mid = valid_mids[m_idx % len(valid_mids)]
                m_idx += 1
                options.append({"text": f"Distractor {opt_idx} text for question {i+1}", "misconception_id": mid})

        code_snippet = "```java\npublic class Main {\n    public static void main(String[] args) {\n        System.out.println(\"Test\");\n    }\n}\n```"
        rec = {
            "concept": concept,
            "difficulty": diff,
            "qtype": qtype,
            "question": f"Self-contained test question #{i+1} about method overriding rules in Java.\n{code_snippet}",
            "options": options,
            "correct_index": c_pos,
            "explanation": f"Explanation for question #{i+1} stating why option {c_pos} is correct and why distractors are wrong.",
            "source": {
                "pdf": pdf,
                "page": page,
            },
        }
        records.append(rec)

    return records


class TestGenPlan(unittest.TestCase):
    def test_plan_size_and_pilot_order(self):
        plan = build_generation_plan()
        self.assertEqual(len(plan), 50)

        # First 4 are pilot
        pilot_in_plan = [e["concept"] for e in plan[:4]]
        self.assertEqual(pilot_in_plan, PILOT_CONCEPTS)

        # Plan IDs are P01..P50
        self.assertEqual(plan[0]["plan_id"], "P01")
        self.assertEqual(plan[49]["plan_id"], "P50")

        # Check javabeans pack_concept
        jb_entry = next((e for e in plan if e["concept"] == "javabeans"), None)
        self.assertIsNotNone(jb_entry)
        self.assertEqual(jb_entry["pack_concept"], "getters-setters")
        self.assertTrue(len(jb_entry["focus"]) > 0)

        # Check round 2 concepts (last 6)
        r2_in_plan = [e["concept"] for e in plan[-6:]]
        self.assertEqual(r2_in_plan, ROUND2_CONCEPTS)


class TestGenNext(unittest.TestCase):
    def test_format_brief_contains_catalog_and_rules(self):
        entry = {
            "plan_id": "P01",
            "pdf": "JavaNotesForProfessionals",
            "concept": "method-overriding",
            "batch_idx": 0,
            "pack_concept": "method-overriding",
            "focus": "",
            "status": "pending",
        }
        brief = format_brief(entry)

        self.assertIn("P01", brief)
        self.assertIn("method-overriding", brief)
        self.assertIn("JavaNotesForProfessionals__method-overriding__b00.jsonl", brief)
        # Must contain catalog misconception IDs
        self.assertIn("method-overriding/static-methods-override", brief)
        # Must contain verbatim rules text
        self.assertIn("RULES that every generated question must follow:", brief)
        self.assertIn("12 MCQs per batch: 4 Easy", brief)


class TestGenSave(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.entry = {
            "plan_id": "P01",
            "pdf": "JavaNotesForProfessionals",
            "concept": "method-overriding",
            "batch_idx": 0,
            "pack_concept": "method-overriding",
            "focus": "",
            "status": "pending",
        }

    def test_valid_batch_passes(self):
        records = make_valid_batch()
        ok, errors = validate_batch(records, self.entry)
        self.assertTrue(ok, f"Expected valid batch to pass, got errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_reject_not_12_records(self):
        records = make_valid_batch()[:11]
        ok, errors = validate_batch(records, self.entry)
        self.assertFalse(ok)
        self.assertTrue(any("exactly 12" in e for e in errors))

    def test_reject_difficulty_split_mismatch(self):
        records = make_valid_batch()
        # Change an Easy to Hard -> 3 Easy, 4 Medium, 5 Hard
        records[0]["difficulty"] = "Hard"
        ok, errors = validate_batch(records, self.entry)
        self.assertFalse(ok)
        self.assertTrue(any("Difficulty split mismatch" in e for e in errors))

    def test_reject_answer_position_skew(self):
        records = make_valid_batch()
        # Set 6 questions to correct_index = 0
        valid_mids = [
            "method-overriding/static-methods-override",
            "method-overriding/can-reduce-visibility",
            "method-overriding/override-annotation-required",
        ]
        for i in range(6):
            records[i]["correct_index"] = 0
            m_idx = 0
            for opt_idx, opt in enumerate(records[i]["options"]):
                if opt_idx == 0:
                    opt["misconception_id"] = None
                else:
                    opt["misconception_id"] = valid_mids[m_idx]
                    m_idx += 1
        ok, errors = validate_batch(records, self.entry)
        self.assertFalse(ok)
        self.assertTrue(any("Answer position 0 used" in e for e in errors))

    def test_reject_missing_code_qtypes(self):
        records = make_valid_batch()
        # Change all code qtypes to concept
        for r in records:
            r["qtype"] = "concept"
        ok, errors = validate_batch(records, self.entry)
        self.assertFalse(ok)
        self.assertTrue(any("requires at least 2 questions with qtype" in e for e in errors))

    def test_reject_foreign_misconception_id(self):
        records = make_valid_batch()
        # Put an exceptions misconception on a method-overriding question
        records[0]["options"][1]["misconception_id"] = "try-catch/catch-all-first"
        ok, errors = validate_batch(records, self.entry)
        self.assertFalse(ok)
        self.assertTrue(any("invalid misconception_id" in e for e in errors))

    def test_reject_source_pdf_mismatch(self):
        records = make_valid_batch()
        records[0]["source"]["pdf"] = "wrong_book.pdf"
        ok, errors = validate_batch(records, self.entry)
        self.assertFalse(ok)
        self.assertTrue(any("source.pdf 'wrong_book.pdf' does not match" in e for e in errors))

    def test_reject_forbidden_phrase(self):
        records = make_valid_batch()
        records[0]["question"] = "According to the text, which method overrides in Java?\n```java\nclass Main{}\n```"
        ok, errors = validate_batch(records, self.entry)
        self.assertFalse(ok)
        self.assertTrue(any("forbidden phrase" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
