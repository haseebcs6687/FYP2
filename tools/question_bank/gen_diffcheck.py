"""
=============================================================================
EduGen - Question Bank Diff & Invariant Checker (Phase 2E-b)
=============================================================================
Compares original pilot question records against repaired pilot question
records across all batches in the given directories.

Asserts invariants:
  1. 'question' text is strictly identical.
  2. 'difficulty' is strictly identical.
  3. Correct option text is strictly identical (regardless of option order).
  4. 'source' dictionary (pdf, page) is strictly identical.

Tracks and reports counts of:
  - changed explanations (Rule R1)
  - changed misconception tags (Rule R2)
  - changed wrong option texts
  - changed qtypes (Rule R4)

Exits with code 1 if any invariant is broken.

Usage:
    python tools/question_bank/gen_diffcheck.py <orig_dir> <new_dir>
=============================================================================
"""

import argparse
import json
import sys
from pathlib import Path


def load_file_records(file_path: Path) -> list[dict]:
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            records.append(json.loads(line_str))
    return records


def diffcheck_dirs(orig_dir: Path, new_dir: Path) -> bool:
    orig_path = Path(orig_dir)
    new_path = Path(new_dir)

    if not orig_path.exists():
        print(f"Error: Original directory does not exist: {orig_path}")
        return False
    if not new_path.exists():
        print(f"Error: Repaired directory does not exist: {new_path}")
        return False

    orig_files = sorted(orig_path.glob("*.jsonl"))
    if not orig_files:
        print(f"Error: No .jsonl files found in {orig_path}")
        return False

    total_records = 0
    changed_explanations = 0
    changed_tags = 0
    changed_option_texts = 0
    changed_qtypes = 0

    invariant_violations = []

    for orig_f in orig_files:
        new_f = new_path / orig_f.name
        if not new_f.exists():
            invariant_violations.append(f"Missing repaired file for {orig_f.name}")
            continue

        orig_recs = load_file_records(orig_f)
        new_recs = load_file_records(new_f)

        if len(orig_recs) != len(new_recs):
            invariant_violations.append(
                f"{orig_f.name}: Record count mismatch (orig={len(orig_recs)}, new={len(new_recs)})"
            )
            continue

        for i, (orig_r, new_r) in enumerate(zip(orig_recs, new_recs), 1):
            total_records += 1
            qid = orig_r.get("id", f"line_{i}")

            # 1. Invariant: question text
            if orig_r.get("question") != new_r.get("question"):
                invariant_violations.append(
                    f"{orig_f.name} #{i} ({qid}): question text was modified"
                )

            # 2. Invariant: difficulty
            if orig_r.get("difficulty") != new_r.get("difficulty"):
                invariant_violations.append(
                    f"{orig_f.name} #{i} ({qid}): difficulty changed from '{orig_r.get('difficulty')}' to '{new_r.get('difficulty')}'"
                )

            # 3. Invariant: correct option text
            orig_c_idx = orig_r.get("correct_index", 0)
            new_c_idx = new_r.get("correct_index", 0)
            orig_c_text = orig_r["options"][orig_c_idx]["text"].strip()
            new_c_text = new_r["options"][new_c_idx]["text"].strip()

            if orig_c_text != new_c_text:
                invariant_violations.append(
                    f"{orig_f.name} #{i} ({qid}): correct option text changed!\n"
                    f"   Orig: {orig_c_text}\n"
                    f"   New : {new_c_text}"
                )

            # 4. Invariant: source
            if orig_r.get("source") != new_r.get("source"):
                invariant_violations.append(
                    f"{orig_f.name} #{i} ({qid}): source changed from {orig_r.get('source')} to {new_r.get('source')}"
                )

            # Track allowable changes:
            # (i) explanation
            if orig_r.get("explanation") != new_r.get("explanation"):
                changed_explanations += 1

            # (ii) qtype
            if orig_r.get("qtype") != new_r.get("qtype"):
                changed_qtypes += 1

            # (iii) option texts and tags
            # Compare options (distractors)
            orig_distractors = [opt for idx, opt in enumerate(orig_r["options"]) if idx != orig_c_idx]
            new_distractors = [opt for idx, opt in enumerate(new_r["options"]) if idx != new_c_idx]

            # If lengths match (always 3 distractors)
            for od, nd in zip(orig_distractors, new_distractors):
                if od.get("text") != nd.get("text"):
                    changed_option_texts += 1
                if od.get("misconception_id") != nd.get("misconception_id"):
                    changed_tags += 1

    print("=" * 70)
    print("EduGen - Question Bank Diff & Invariant Check (Phase 2E-b)")
    print("=" * 70)
    print(f"Original Directory : {orig_path}")
    print(f"Repaired Directory : {new_path}")
    print(f"Files Checked      : {len(orig_files)}")
    print(f"Total Questions    : {total_records}")
    print("-" * 70)
    print(f"Changed Explanations (R1) : {changed_explanations}")
    print(f"Changed Misconceptions (R2): {changed_tags}")
    print(f"Changed Distractor Texts  : {changed_option_texts}")
    print(f"Changed QTypes (R4)       : {changed_qtypes}")
    print("-" * 70)

    if invariant_violations:
        print(f"FAILED: {len(invariant_violations)} invariant violations detected:")
        for v in invariant_violations:
            print(f"  ❌ {v}")
        print("=" * 70)
        return False

    print("SUCCESS: All invariants satisfied (questions, difficulty, correct answers, sources unchanged).")
    print("=" * 70)
    return True


def main():
    parser = argparse.ArgumentParser(description="Diff and verify question batch invariants.")
    parser.add_argument("orig_dir", help="Path to original raw/pilot_orig directory.")
    parser.add_argument("new_dir", help="Path to repaired directory.")
    args = parser.parse_args()

    ok = diffcheck_dirs(Path(args.orig_dir), Path(args.new_dir))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
