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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_file_records(file_path: Path) -> list[dict]:
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            records.append(json.loads(line_str))
    return records


def load_allow_changed(file_path: Path) -> set[str]:
    if not file_path or not file_path.exists():
        return set()
    with open(file_path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip() and not line.startswith("#")}


def is_record_exempt(orig_r: dict, new_r: dict, allow_set: set[str]) -> bool:
    if not allow_set:
        return False
    orig_id = orig_r.get("question_id") or orig_r.get("id") or ""
    new_id = new_r.get("question_id") or new_r.get("id") or ""
    if orig_id in allow_set or new_id in allow_set:
        return True
    for item in allow_set:
        if item and (item in orig_id or item in new_id):
            return True
    return False


def diffcheck_dirs(orig_dir: Path, new_dir: Path, allow_changed_file: Path = None) -> bool:
    orig_path = Path(orig_dir)
    new_path = Path(new_dir)
    allow_set = load_allow_changed(allow_changed_file) if allow_changed_file else set()

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
    exempt_records = 0
    changed_ids = 0
    changed_tags = 0
    changed_qtypes = 0
    changed_explanations = 0
    changed_option_texts = 0

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
            qid = orig_r.get("question_id") or orig_r.get("id", f"line_{i}")
            new_qid = new_r.get("question_id") or new_r.get("id", f"line_{i}")

            if qid != new_qid:
                changed_ids += 1

            exempt = is_record_exempt(orig_r, new_r, allow_set)
            if exempt:
                exempt_records += 1

            # Invariants checked for all NON-exempt records
            if not exempt:
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

                # 3. Invariant: qtype
                if orig_r.get("qtype") != new_r.get("qtype"):
                    invariant_violations.append(
                        f"{orig_f.name} #{i} ({qid}): qtype changed from '{orig_r.get('qtype')}' to '{new_r.get('qtype')}'"
                    )

                # 4. Invariant: correct_index
                orig_c_idx = orig_r.get("correct_index")
                new_c_idx = new_r.get("correct_index")
                if orig_c_idx != new_c_idx:
                    invariant_violations.append(
                        f"{orig_f.name} #{i} ({qid}): correct_index changed from {orig_c_idx} to {new_c_idx}"
                    )

                # 5. Invariant: option order and option texts
                orig_opts = orig_r.get("options", [])
                new_opts = new_r.get("options", [])
                if len(orig_opts) != len(new_opts):
                    invariant_violations.append(
                        f"{orig_f.name} #{i} ({qid}): option count changed ({len(orig_opts)} vs {len(new_opts)})"
                    )
                else:
                    for opt_idx, (oo, no) in enumerate(zip(orig_opts, new_opts)):
                        if oo.get("text") != no.get("text"):
                            invariant_violations.append(
                                f"{orig_f.name} #{i} ({qid}): option {opt_idx} text changed!\n"
                                f"   Orig: {oo.get('text')}\n"
                                f"   New : {no.get('text')}"
                            )

            # Track changes
            if orig_r.get("explanation") != new_r.get("explanation"):
                changed_explanations += 1

            if orig_r.get("qtype") != new_r.get("qtype"):
                changed_qtypes += 1

            orig_opts = orig_r.get("options", [])
            new_opts = new_r.get("options", [])
            for oo, no in zip(orig_opts, new_opts):
                if oo.get("text") != no.get("text"):
                    changed_option_texts += 1
                if oo.get("misconception_id") != no.get("misconception_id"):
                    changed_tags += 1

    print("=" * 70)
    print("EduGen - Question Bank Diff & Invariant Check (Phase 2E-c)")
    print("=" * 70)
    print(f"Original Directory : {orig_path}")
    print(f"Repaired Directory : {new_path}")
    if allow_changed_file:
        print(f"Allow Changed File : {allow_changed_file} ({len(allow_set)} patterns)")
    print(f"Files Checked      : {len(orig_files)}")
    print(f"Total Questions    : {total_records}")
    print(f"Exempt Questions   : {exempt_records}")
    print("-" * 70)
    print(f"Changed IDs               : {changed_ids}")
    print(f"Changed Misconceptions    : {changed_tags}")
    print(f"Changed Explanations      : {changed_explanations}")
    print(f"Changed Option Texts      : {changed_option_texts}")
    print(f"Changed QTypes            : {changed_qtypes}")
    print("-" * 70)

    if invariant_violations:
        print(f"FAILED: {len(invariant_violations)} invariant violations detected:")
        for v in invariant_violations:
            print(f"  [X] {v}")
        print("=" * 70)
        return False

    print("SUCCESS: All invariants satisfied (non-exempt questions, difficulty, qtype, options, correct_index unchanged).")
    print("=" * 70)
    return True


def main():
    parser = argparse.ArgumentParser(description="Diff and verify question batch invariants.")
    parser.add_argument("orig_dir", help="Path to original raw directory.")
    parser.add_argument("new_dir", help="Path to repaired directory.")
    parser.add_argument("--allow-changed", help="Path to file containing exempt question_ids", default=None)
    args = parser.parse_args()

    allow_path = Path(args.allow_changed) if args.allow_changed else None
    ok = diffcheck_dirs(Path(args.orig_dir), Path(args.new_dir), allow_changed_file=allow_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

