"""
=============================================================================
EduGen - Question Validator Unit & Integration Tests
=============================================================================
Tests scripts/validate_questions.py against various valid and invalid question
records, edge cases, deduplication, and file generation.

Usage:
    python scripts/test_questions.py
=============================================================================
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.validate_questions import (
    QuestionValidator,
    jaccard_similarity,
    tokenize,
    validate_question_record,
)

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS {name}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL {name}  <- {detail}")


def make_valid_question():
    return {
        "concept": "method-overriding",
        "difficulty": "Medium",
        "qtype": "code_output",
        "question": "What is printed by this program?\n```java\nclass A { void m() { System.out.print(\"A\"); } }\nclass B extends A { void m() { System.out.print(\"B\"); } }\npublic class Test { public static void main(String[] args) { A obj = new B(); obj.m(); } }\n```",
        "options": [
            {"text": "B", "misconception_id": None},
            {"text": "A", "misconception_id": "method-overriding/static-methods-override"},
            {"text": "AB", "misconception_id": "method-overriding/can-reduce-visibility"},
            {"text": "Compilation error", "misconception_id": "method-overriding/override-annotation-required"}
        ],
        "correct_index": 0,
        "explanation": "Runtime polymorphism invokes B's implementation of m() through dynamic method dispatch.",
        "source": {
            "pdf": "core_java.pdf",
            "page": "142"
        }
    }


def main():
    print("==================================================")
    print("  EduGen Question Validator Tests")
    print("==================================================")

    # 1. Valid record
    print("\n1. Schema structural validation")
    q = make_valid_question()
    ok, err = validate_question_record(q)
    check("valid question passes validation", ok, err)

    # 2. Missing field
    q_bad = make_valid_question()
    del q_bad["explanation"]
    ok, err = validate_question_record(q_bad)
    check("missing required field rejected", not ok and "explanation" in err, err)

    # 3. Invalid concept
    q_bad = make_valid_question()
    q_bad["concept"] = "quantum-computing"
    ok, err = validate_question_record(q_bad)
    check("unknown concept rejected", not ok and "concept" in err, err)

    # 4. Invalid difficulty
    q_bad = make_valid_question()
    q_bad["difficulty"] = "SuperHard"
    ok, err = validate_question_record(q_bad)
    check("invalid difficulty rejected", not ok and "difficulty" in err, err)

    # 5. Invalid qtype
    q_bad = make_valid_question()
    q_bad["qtype"] = "essay"
    ok, err = validate_question_record(q_bad)
    check("invalid qtype rejected", not ok and "qtype" in err, err)

    # 6. Unbalanced code fences
    q_bad = make_valid_question()
    q_bad["question"] = "What does this code do? ```java int x = 5;"
    ok, err = validate_question_record(q_bad)
    check("unbalanced code fences rejected", not ok and "fences" in err, err)

    # 7. Short question text
    q_bad = make_valid_question()
    q_bad["question"] = "Short?"
    ok, err = validate_question_record(q_bad)
    check("too short question rejected", not ok and "short" in err, err)

    # 8. Options count != 4
    q_bad = make_valid_question()
    q_bad["options"] = q_bad["options"][:3]
    ok, err = validate_question_record(q_bad)
    check("options length != 4 rejected", not ok and "4" in err, err)

    # 9. Duplicate option text
    q_bad = make_valid_question()
    q_bad["options"][1]["text"] = "B"  # same as option 0
    ok, err = validate_question_record(q_bad)
    check("duplicate option texts rejected", not ok and "Duplicate option text" in err, err)

    # 10. Correct option has non-null misconception_id
    q_bad = make_valid_question()
    q_bad["options"][0]["misconception_id"] = "method-overriding/static-methods-override"
    ok, err = validate_question_record(q_bad)
    check("correct option with misconception_id rejected", not ok and "null" in err, err)

    # 11. Wrong option has misconception from different concept
    q_bad = make_valid_question()
    q_bad["options"][1]["misconception_id"] = "catch-blocks/catch-all-hides-bugs"  # exception concept!
    ok, err = validate_question_record(q_bad)
    check("misconception from foreign concept rejected", not ok and "invalid misconception_id" in err, err)

    # 12. More than 1 distractor has null misconception_id
    q_bad = make_valid_question()
    q_bad["options"][1]["misconception_id"] = None
    q_bad["options"][2]["misconception_id"] = None
    ok, err = validate_question_record(q_bad)
    check("multiple null distractors rejected", not ok and "At most 1 wrong distractor" in err, err)

    # 13. Duplicate misconception_id across distractors
    q_bad = make_valid_question()
    q_bad["options"][1]["misconception_id"] = "method-overriding/static-methods-override"
    q_bad["options"][2]["misconception_id"] = "method-overriding/static-methods-override"
    ok, err = validate_question_record(q_bad)
    check("duplicate misconception_id on distractors rejected", not ok and "Duplicate misconception_id" in err, err)

    # Deduplication and File Pipeline Testing
    print("\n2. Deduplication & pipeline validation")
    tmp_dir = tempfile.mkdtemp()
    try:
        out_dir = os.path.join(tmp_dir, "val_out")
        validator = QuestionValidator(out_dir=out_dir)

        # Accept first question
        q1 = make_valid_question()
        accepted1 = validator.validate_and_add(q1)
        check("first question accepted", accepted1)

        # Exact duplicate rejected
        q_exact = make_valid_question()
        accepted2 = validator.validate_and_add(q_exact)
        check("exact duplicate question rejected", not accepted2)

        # Near-duplicate rejected (Jaccard >= 0.85)
        q_near = make_valid_question()
        # Slightly alter words but keep > 85% overlap
        q_near["question"] = "What is printed by this Java program?\n```java\nclass A { void m() { System.out.print(\"A\"); } }\nclass B extends A { void m() { System.out.print(\"B\"); } }\npublic class Test { public static void main(String[] args) { A obj = new B(); obj.m(); } }\n```"
        accepted3 = validator.validate_and_add(q_near)
        check("near-duplicate question rejected (Jaccard >= 0.85)", not accepted3)

        # Different question in same concept accepted
        q_diff = make_valid_question()
        q_diff["question"] = "Can an overriding method in a Java subclass have a more restrictive access modifier than the superclass method?"
        q_diff["qtype"] = "concept"
        q_diff["options"] = [
            {"text": "No, overriding methods cannot reduce visibility", "misconception_id": None},
            {"text": "Yes, any access modifier is allowed in subclasses", "misconception_id": "method-overriding/can-reduce-visibility"},
            {"text": "Only if protected is changed to package-private", "misconception_id": "method-overriding/override-annotation-required"},
            {"text": "Only if the class is marked abstract", "misconception_id": None}
        ]
        accepted4 = validator.validate_and_add(q_diff)
        check("distinct question in same concept accepted", accepted4)

        # Output files written
        acc_path, rej_path = validator.write_outputs()
        check("accepted.jsonl exists", os.path.exists(acc_path))
        check("rejected.jsonl exists", os.path.exists(rej_path))

        with open(acc_path, "r", encoding="utf-8") as f:
            acc_lines = [json.loads(line) for line in f if line.strip()]
        with open(rej_path, "r", encoding="utf-8") as f:
            rej_lines = [json.loads(line) for line in f if line.strip()]

        check("accepted file contains 2 questions", len(acc_lines) == 2, f"got {len(acc_lines)}")
        check("rejected file contains 2 questions", len(rej_lines) == 2, f"got {len(rej_lines)}")
        check("rejected file records have 'reason'", all("reason" in r for r in rej_lines))

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n==================================================")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print("==================================================")

    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
