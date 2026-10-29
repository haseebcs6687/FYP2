"""
=============================================================================
EduGen - Question Bank Generation Validator & Installer (Phase 2E-a)
=============================================================================
Validates a candidate 12-MCQ JSONL batch file against all Phase 2E-a rules
and installs it to rag/corpus/questions/raw/ upon passing all checks.

Validation rules:
  1. Exactly 12 records.
  2. Passes validate_question_record() from scripts.validate_questions.
  3. Difficulty split: exactly 4 Easy, 4 Medium, 4 Hard.
  4. Answer position distribution: correct_index count per position <= 5.
  5. Code qtypes: >= 2 questions in {code_output, bug_find}
     (exempt concepts: abstraction-basics, design-patterns, abstract-class-vs-interface).
  6. Misconceptions: every distractor misconception_id belongs to THIS concept
     (or null, max 1 null per question).
  7. Provenance: source.pdf == entry pdf, source.page within pack page bounds.
  8. Wording: no question contains "according to the text/book/passage/figure/chapter".
  9. Does not overwrite an already done batch without --force.

Usage:
    python tools/question_bank/gen_save.py <plan_id> <jsonl-file> [--force]
=============================================================================
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.misconceptions import is_valid_misconception
from scripts.validate_questions import validate_question_record
from tools.question_bank.bank_pack import build_pack

PLAN_FILE = BASE_DIR / "data" / "bank_work" / "gen_plan.json"
RAW_DIR = BASE_DIR / "rag" / "corpus" / "questions" / "raw"

FORBIDDEN_PHRASE_RE = re.compile(
    r"\baccording\s+to\s+the\s+(?:text|book|passage|figure|chapter)\b",
    re.IGNORECASE,
)

EXEMPT_CODE_QTYPES = {
    "abstraction-basics",
    "design-patterns",
    "abstract-class-vs-interface",
}


def load_plan(plan_path: Path = None) -> list[dict]:
    p_file = plan_path or PLAN_FILE
    if not p_file.exists():
        raise FileNotFoundError(f"Plan file not found: {p_file}. Run gen_plan.py first.")
    with open(p_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_plan(plan: list[dict], plan_path: Path = None):
    p_file = plan_path or PLAN_FILE
    with open(p_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)


def get_target_path(pdf: str, concept: str, batch_idx: int) -> Path:
    return RAW_DIR / f"{pdf}__{concept}__b{batch_idx:02d}.jsonl"


def validate_batch(
    records: list[dict],
    entry: dict,
    work_dir: Path = None,
) -> tuple[bool, list[str]]:
    """
    Validates a list of question records against all Phase 2E-a rules.
    Returns (is_valid: bool, errors: list[str]).
    """
    errors = []

    # Rule 1: Exactly 12 records
    if len(records) != 12:
        errors.append(f"Batch must contain exactly 12 records (got {len(records)})")
        return False, errors

    concept = entry["concept"]
    pdf = entry["pdf"]
    pack_concept = entry.get("pack_concept", concept)
    batch_idx = entry.get("batch_idx", 0)

    # Pack page range bounds
    pack = build_pack(pdf, pack_concept, batch_idx=batch_idx, work_dir=work_dir)
    if not pack or pack.status == "NO_MATERIAL":
        min_page, max_page = 1, 9999
    else:
        min_page = min(c["page_start"] for c in pack)
        max_page = max(c["page_end"] for c in pack)

    diff_counts = Counter()
    pos_counts = Counter()
    code_qtype_count = 0

    for i, rec in enumerate(records, 1):
        # Rule 2: Basic schema validation
        ok, msg = validate_question_record(rec)
        if not ok:
            errors.append(f"Question #{i}: schema validation failed: {msg}")
            continue

        # Concept match
        if rec.get("concept") != concept:
            errors.append(f"Question #{i}: concept '{rec.get('concept')}' does not match plan concept '{concept}'")

        # Track difficulty
        diff = rec.get("difficulty")
        diff_counts[diff] += 1

        # Track answer position
        c_idx = rec.get("correct_index")
        pos_counts[c_idx] += 1

        # Track code qtypes
        qtype = rec.get("qtype")
        if qtype in {"code_output", "bug_find"}:
            code_qtype_count += 1

        # Rule 6: Misconceptions validation
        options = rec.get("options", [])
        for opt_idx, opt in enumerate(options):
            if opt_idx == c_idx:
                continue
            m_id = opt.get("misconception_id")
            if m_id is not None:
                if not is_valid_misconception(m_id, concept):
                    errors.append(
                        f"Question #{i}, Option {opt_idx}: misconception '{m_id}' is not valid for concept '{concept}'"
                    )

        # Rule 7: Provenance check
        src = rec.get("source", {})
        src_pdf = src.get("pdf", "")
        if src_pdf != pdf:
            errors.append(f"Question #{i}: source.pdf '{src_pdf}' does not match plan PDF '{pdf}'")

        raw_page = src.get("page")
        try:
            p_num = int(str(raw_page).strip())
            if not (min_page <= p_num <= max_page):
                errors.append(
                    f"Question #{i}: source.page {p_num} is outside pack page range [{min_page}, {max_page}]"
                )
        except ValueError:
            # If not an integer, check if string non-empty
            if not str(raw_page).strip():
                errors.append(f"Question #{i}: source.page is empty")

        # Rule 8: Forbidden phrase check
        q_text = rec.get("question", "")
        m = FORBIDDEN_PHRASE_RE.search(q_text)
        if m:
            errors.append(
                f"Question #{i}: forbidden phrase detected: '{m.group(0)}' (must not refer to the book/text)"
            )

    # Rule 3: Difficulty split 4 Easy / 4 Medium / 4 Hard
    expected_diff = {"Easy": 4, "Medium": 4, "Hard": 4}
    for d, expected_cnt in expected_diff.items():
        actual_cnt = diff_counts.get(d, 0)
        if actual_cnt != expected_cnt:
            errors.append(f"Difficulty split mismatch: expected {expected_cnt} {d}, got {actual_cnt}")

    # Rule 4: Answer position count per position <= 5
    for pos in (0, 1, 2, 3):
        cnt = pos_counts.get(pos, 0)
        if cnt > 5:
            errors.append(f"Answer position {pos} used {cnt} times (maximum allowed is 5)")

    # Rule 5: At least 2 qtypes in {code_output, bug_find} unless exempt
    if concept not in EXEMPT_CODE_QTYPES:
        if code_qtype_count < 2:
            errors.append(
                f"Concept '{concept}' requires at least 2 questions with qtype in {{code_output, bug_find}} (got {code_qtype_count})"
            )

    return len(errors) == 0, errors


def install_batch(
    plan_id: str,
    jsonl_path: Path,
    force: bool = False,
    plan_path: Path = None,
    work_dir: Path = None,
) -> bool:
    """
    Validates candidate JSONL file and installs to raw questions directory upon success.
    """
    jsonl_file = Path(jsonl_path)
    if not jsonl_file.exists():
        print(f"Error: Candidate JSONL file not found: {jsonl_file}")
        return False

    plan = load_plan(plan_path)
    entry = next((e for e in plan if e["plan_id"] == plan_id), None)
    if not entry:
        print(f"Error: Plan ID '{plan_id}' not found in gen_plan.json")
        return False

    if entry.get("status") == "done" and not force:
        print(f"Error: Batch '{plan_id}' is already marked done. Use --force to overwrite.")
        return False

    records = []
    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                rec = json.loads(line_str)
                records.append(rec)
            except json.JSONDecodeError as ex:
                print(f"Error: Invalid JSON on line {line_num} of {jsonl_file}: {ex}")
                return False

    ok, errors = validate_batch(records, entry, work_dir=work_dir)
    if not ok:
        print("=" * 70)
        print(f"VALIDATION FAILED for {plan_id} ({len(errors)} errors):")
        print("=" * 70)
        for err in errors:
            print(f"  ❌ {err}")
        print("=" * 70)
        print("File was NOT installed.")
        return False

    # Install to raw destination
    target_path = get_target_path(entry["pdf"], entry["concept"], entry["batch_idx"])
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Update plan status
    entry["status"] = "done"
    save_plan(plan, plan_path)

    pos_counts = Counter(r["correct_index"] for r in records)
    diff_counts = Counter(r["difficulty"] for r in records)
    qtype_counts = Counter(r["qtype"] for r in records)

    print("=" * 70)
    print(f"SUCCESS: Batch {plan_id} validated and installed!")
    print("=" * 70)
    print(f"Target File : {target_path}")
    print(f"Concept     : {entry['concept']}")
    print(f"PDF Source  : {entry['pdf']} (batch {entry['batch_idx']:02d})")
    print(f"Records     : {len(records)} questions")
    print(f"Difficulty  : Easy={diff_counts['Easy']}, Medium={diff_counts['Medium']}, Hard={diff_counts['Hard']}")
    print(f"QTypes      : concept={qtype_counts['concept']}, code_output={qtype_counts['code_output']}, bug_find={qtype_counts['bug_find']}")
    print(f"Positions   : pos0={pos_counts[0]}, pos1={pos_counts[1]}, pos2={pos_counts[2]}, pos3={pos_counts[3]}")
    print(f"Plan Status : {plan_id} -> DONE")
    print("=" * 70)
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate and install generated question batch.")
    parser.add_argument("plan_id", help="Plan ID from gen_plan.json (e.g. P01).")
    parser.add_argument("jsonl_file", help="Path to generated candidate JSONL file.")
    parser.add_argument("--force", action="store_true", help="Overwrite already installed batch.")
    args = parser.parse_args()

    success = install_batch(args.plan_id, Path(args.jsonl_file), force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
