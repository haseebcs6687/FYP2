"""
=============================================================================
EduGen - Unit Tests for MCQ Generation Tooling (Phase 2E-b Hardened)
=============================================================================
Tests gen_plan, gen_next, gen_save, and all Phase 2E-b gates:
  - Plan structure, 50 entries, pilot order, round 2 concepts, focus guidance.
  - Brief formatting, catalog misconceptions inclusion, verbatim rules (R1..R8).
  - Gate 1: Reject explanation option letter/number references; accept clean explanations.
  - Gate 2: Reject "all/none of the above", "both A and B"; accept clean choices.
  - Gate 3: Reject missing ```java fence in code_output/bug_find; accept when fence present.
  - Gate 4: Reject when correct option strictly longest in > 5 of 12; accept when balanced.
  - Gate 5: Reject cross-batch near-duplicate (token Jaccard >= 0.70); accept distinct.
  - Gate 6: Reject all 12 on same source.page when pack spans multiple pages; accept spread pages.
  - Gate 7: Deterministic shuffle produces balanced correct_index counts in [2, 4].
  - Gate 8: Rejections logged to gen_log.jsonl with plan_id and rule name.
=============================================================================
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS
from tools.question_bank.gen_next import RULES_TEXT, format_brief, get_next_pending_entries
from tools.question_bank.gen_plan import PILOT_CONCEPTS, ROUND2_CONCEPTS, build_generation_plan
from tools.question_bank.gen_save import (
    deterministic_shuffle_batch,
    install_batch,
    validate_batch,
)


def make_valid_batch(concept: str = "method-overriding", pdf: str = "JavaNotesForProfessionals", pages: list[int] = None) -> list[dict]:
    """Creates a strictly valid 12-MCQ batch conforming to all Phase 2E-b rules."""
    records = []
    difficulties = ["Easy"] * 4 + ["Medium"] * 4 + ["Hard"] * 4
    positions = [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]

    valid_mids = [
        "method-overriding/static-methods-override",
        "method-overriding/can-reduce-visibility",
        "method-overriding/override-annotation-required",
    ]

    page_list = pages or ([304] * 6 + [305] * 6)

    for i in range(12):
        diff = difficulties[i]
        c_pos = positions[i]
        qtype = "code_output" if i < 3 else ("bug_find" if i == 3 else "concept")

        options = []
        m_idx = 0
        for opt_idx in range(4):
            if opt_idx == c_pos:
                options.append({"text": f"Valid correct concept explanation for question {i+1}", "misconception_id": None})
            else:
                mid = valid_mids[m_idx % len(valid_mids)]
                m_idx += 1
                options.append({"text": f"Plausible wrong distractor {opt_idx} detail for question {i+1}", "misconception_id": mid})

        code_snippet = "```java\npublic class Main {\n    public static void main(String[] args) {\n        System.out.println(\"Test\");\n    }\n}\n```"
        rec = {
            "id": f"test-method-overriding-q{i+1:02d}",
            "concept": concept,
            "difficulty": diff,
            "qtype": qtype,
            "question": f"Self-contained test question #{i+1} covering unique aspects of overriding #{i+1}.\n{code_snippet}",
            "options": options,
            "correct_index": c_pos,
            "explanation": f"The method signature must match and static methods cannot be polymorphically overridden in case #{i+1}.",
            "source": {
                "pdf": pdf,
                "page": page_list[i],
            },
        }
        records.append(rec)

    return records


class TestGenPlan(unittest.TestCase):
    def test_plan_size_and_pilot_order(self):
        plan = build_generation_plan()
        self.assertEqual(len(plan), 50)

        pilot_in_plan = [e["concept"] for e in plan[:4]]
        self.assertEqual(pilot_in_plan, PILOT_CONCEPTS)

        self.assertEqual(plan[0]["plan_id"], "P01")
        self.assertEqual(plan[49]["plan_id"], "P50")

        jb_entry = next((e for e in plan if e["concept"] == "javabeans"), None)
        self.assertIsNotNone(jb_entry)
        self.assertEqual(jb_entry["pack_concept"], "getters-setters")
        self.assertTrue(len(jb_entry["focus"]) > 0)

        # Check focus for dynamic-method-dispatch and runtime-polymorphism
        dmd = next((e for e in plan if e["concept"] == "dynamic-method-dispatch"), None)
        self.assertIn("chosen by the RUNTIME object's class", dmd["focus"])

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
        self.assertIn("method-overriding/static-methods-override", brief)

        # Verbatim rules checks
        self.assertIn("RULES that every generated question must follow:", brief)
        self.assertIn("12 MCQs per batch: 4 Easy", brief)
        self.assertIn("R1 Explanations never name an option by letter/number", brief)
        self.assertIn("R2 Distractor design", brief)
        self.assertIn("R3 All four options similar in length and detail", brief)
        self.assertIn("R4 qtype honesty", brief)
        self.assertIn("R7 source.page = the pack page that actually supports the question", brief)
        self.assertIn("R8 No \"all/none of the above\", no \"both A and B\"", brief)


class TestGenSaveGates(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.entry = {
            "plan_id": "P05",
            "pdf": "JavaNotesForProfessionals",
            "concept": "method-overriding",
            "batch_idx": 0,
            "pack_concept": "method-overriding",
            "focus": "",
            "status": "pending",
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_valid_batch_passes(self):
        records = make_valid_batch()
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertTrue(ok, f"Expected valid batch to pass, got errors: {errors}")
        self.assertEqual(len(errors), 0)

    # Gate 1: Explanation option references
    def test_gate1_reject_explanation_option_ref(self):
        records = make_valid_batch()
        records[0]["explanation"] = "Option B is correct because subclasses can override methods."
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertFalse(ok)
        self.assertTrue(any("explanation_option_ref" in e for e in errors))

    def test_gate1_accept_clean_explanation(self):
        records = make_valid_batch()
        records[0]["explanation"] = "Subclasses inherit instance methods and dynamically dispatch invocations at runtime."
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertTrue(ok)

    # Gate 2: Forbidden option phrases (all/none of the above, both A and B)
    def test_gate2_reject_forbidden_option_choice(self):
        records = make_valid_batch()
        records[0]["options"][1]["text"] = "None of the above"
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertFalse(ok)
        self.assertTrue(any("forbidden_option_choice" in e for e in errors))

    def test_gate2_accept_clean_options(self):
        records = make_valid_batch()
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertTrue(ok)

    # Gate 3: Code fence requirement for code_output/bug_find
    def test_gate3_reject_missing_code_fence(self):
        records = make_valid_batch()
        records[0]["qtype"] = "code_output"
        records[0]["question"] = "What does this code output when running without any markdown fences?"
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertFalse(ok)
        self.assertTrue(any("code_fence_missing" in e for e in errors))

    def test_gate3_accept_code_fence(self):
        records = make_valid_batch()
        records[0]["qtype"] = "code_output"
        records[0]["question"] = "What does this code output?\n```java\nclass Main{}\n```"
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertTrue(ok)

    # Gate 4: Strictly longest correct option count > 5
    def test_gate4_reject_correct_option_longest_excess(self):
        records = make_valid_batch()
        # Make correct option strictly the longest in 6 questions
        for i in range(6):
            c_pos = records[i]["correct_index"]
            records[i]["options"][c_pos]["text"] = "A" * 200
            for j in range(4):
                if j != c_pos:
                    records[i]["options"][j]["text"] = f"Distractor {j} " + ("B" * 20)

        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertFalse(ok)
        self.assertTrue(any("correct_option_longest" in e for e in errors))

    def test_gate4_accept_correct_option_longest_balanced(self):
        records = make_valid_batch()
        # All options equal length but distinct texts
        for r in records:
            for opt_idx, opt in enumerate(r["options"]):
                opt["text"] = f"Standard uniform length option text {opt_idx}"
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertTrue(ok)

    # Gate 5: Cross-batch near-duplicate check
    def test_gate5_reject_near_duplicate(self):
        from tools.question_bank.gen_save import tokenize
        records = make_valid_batch()
        # Mock an installed question with near-identical tokens to records[0]
        q_tokens = tokenize(records[0]["question"])
        installed = [("installed_q01", q_tokens)]
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir, installed_questions=installed)
        self.assertFalse(ok)
        self.assertTrue(any("near_duplicate" in e for e in errors))

    def test_gate5_accept_distinct_question(self):
        records = make_valid_batch()
        installed = [
            ("installed_q01", {"completely", "unrelated", "syntax", "tokens", "only", "about", "database"})
        ]
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir, installed_questions=installed)
        self.assertTrue(ok)

    # Gate 6: Same source.page on multi-page pack
    def test_gate6_reject_same_source_page_multi_page_pack(self):
        # All 12 records given page 305 when pack spans 304-308
        records = make_valid_batch(pages=[305] * 12)
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertFalse(ok)
        self.assertTrue(any("same_source_page" in e for e in errors))

    def test_gate6_accept_multiple_source_pages(self):
        records = make_valid_batch(pages=[304] * 6 + [305] * 6)
        ok, errors = validate_batch(records, self.entry, raw_dir=self.temp_dir)
        self.assertTrue(ok)

    # Gate 7: Deterministic shuffle
    def test_gate7_deterministic_shuffle(self):
        records = make_valid_batch()
        shuffled, attempts = deterministic_shuffle_batch(records)
        self.assertGreaterEqual(attempts, 0)
        self.assertEqual(len(shuffled), 12)

        pos_counts = {p: 0 for p in range(4)}
        for r in shuffled:
            c_idx = r["correct_index"]
            pos_counts[c_idx] += 1
            # Correct option must have null misconception_id
            self.assertIsNone(r["options"][c_idx]["misconception_id"])
            # Distractors retain their misconception_ids
            for j, opt in enumerate(r["options"]):
                if j != c_idx:
                    self.assertIsNotNone(opt["misconception_id"])

        for p in range(4):
            self.assertGreaterEqual(pos_counts[p], 2)
            self.assertLessEqual(pos_counts[p], 4)

    # Gate 8: Rejection logging to gen_log.jsonl
    def test_gate8_rejections_logged(self):
        log_path = self.temp_dir / "gen_log.jsonl"
        plan_path = self.temp_dir / "gen_plan.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump([self.entry], f)

        candidate_file = self.temp_dir / "bad_candidate.jsonl"
        # 11 records triggers record_count rejection
        with open(candidate_file, "w", encoding="utf-8") as f:
            for r in make_valid_batch()[:11]:
                f.write(json.dumps(r) + "\n")

        pid = self.entry["plan_id"]
        success = install_batch(pid, candidate_file, plan_path=plan_path, raw_dir=self.temp_dir, log_path=log_path)
        self.assertFalse(success)
        self.assertTrue(log_path.exists())

        with open(log_path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f]
        self.assertTrue(any(l["plan_id"] == pid and l["rule"] == "record_count" for l in lines))


if __name__ == "__main__":
    unittest.main()
