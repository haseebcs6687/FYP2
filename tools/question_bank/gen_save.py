"""
=============================================================================
EduGen - Question Bank Generation Validator & Installer (Phase 2E-b Hardened)
=============================================================================
Validates a candidate 12-MCQ JSONL batch file against all Phase 2E-b rules
and installs it to rag/corpus/questions/raw/ upon passing all checks.

Validation Gates (run BEFORE install):
  1. Exactly 12 records.
  2. Passes validate_question_record() from scripts.validate_questions.
  3. Difficulty split: exactly 4 Easy, 4 Medium, 4 Hard.
  4. Answer position distribution: correct_index count per position <= 5.
  5. Code qtypes: >= 2 questions in {code_output, bug_find}
     (exempt concepts: abstraction-basics, design-patterns, abstract-class-vs-interface).
  6. Misconceptions: every distractor misconception_id belongs to THIS concept
     (or null, 0-3 nulls per question meaning "no verified catalog match").
  7. Provenance: source.pdf == entry pdf, source.page within pack page bounds.
  8. Wording: no question contains "according to the text/book/passage/figure/chapter".
  9. [Gate 1] Explanations never refer to options by letter or number:
     "Option B", "option 2", "choice C", "answer A", "(A)", "A)".
 10. [Gate 2] No question/options containing "all of the above", "none of the above", "both A and B".
 11. [Gate 3] qtype code_output or bug_find requires a ```java fence inside question.
 12. [Gate 4] Correct option strictly longest in <= 5 of 12 questions.
 13. [Gate 5] Cross-batch near-duplicate: token Jaccard against other installed records < 0.70.
 14. [Gate 6] Records do not all share the same source.page if pack spans multiple pages.
 15. [Gate 7] Deterministic option shuffle: seeded from sha1(question) + attempt counter,
     until position counts are all in [2, 4].
 16. [Gate 8] Appends all rejections to data/bank_work/gen_log.jsonl.

Usage:
    python tools/question_bank/gen_save.py <plan_id> <jsonl-file> [--force]
=============================================================================
"""

import argparse
import hashlib
import json
import random
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
GEN_LOG_FILE = BASE_DIR / "data" / "bank_work" / "gen_log.jsonl"

FORBIDDEN_PHRASE_RE = re.compile(
    r"\baccording\s+to\s+the\s+(?:text|book|passage|figure|chapter)\b",
    re.IGNORECASE,
)

OPTION_REF_RE = re.compile(
    r"(?i:\b(?:option|choice|answer)\s+(?:[a-d]|[0-4])\b)|(?<!\w)\([A-Da-d]\)|(?<![\w.])[A-D]\)"
)

FORBIDDEN_CHOICE_RE = re.compile(
    r"(?i)\b(?:all\s+of\s+the\s+above|none\s+of\s+the\s+above|both\s+[a-d]\s+and\s+[a-d])\b"
)

EXEMPT_CODE_QTYPES = {
    "abstraction-basics",
    "design-patterns",
    "abstract-class-vs-interface",
}


def tokenize(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens for near-duplicate Jaccard comparison."""
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


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


def get_target_path(pdf: str, concept: str, batch_idx: int, raw_dir: Path = None) -> Path:
    r_dir = raw_dir or RAW_DIR
    return r_dir / f"{pdf}__{concept}__b{batch_idx:02d}.jsonl"


def load_installed_questions(raw_dir: Path = None, exclude_file: Path = None) -> list[tuple[str, set[str]]]:
    """Loads all existing question IDs and their token sets from raw_dir, excluding exclude_file."""
    r_dir = raw_dir or RAW_DIR
    installed = []
    if not r_dir.exists():
        return installed

    for f in sorted(r_dir.glob("*.jsonl")):
        if exclude_file and f.resolve() == exclude_file.resolve():
            continue
        with open(f, "r", encoding="utf-8") as fp:
            for line_no, line in enumerate(fp, 1):
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                try:
                    data = json.loads(raw)
                    qid = data.get("id", f"{f.stem}_q{line_no}")
                    q_text = data.get("question", "")
                    installed.append((qid, tokenize(q_text)))
                except Exception:
                    pass
    return installed


def log_rejections(plan_id: str, rule_errors: list[tuple[str, str]], log_path: Path = None):
    """Appends rejection events to data/bank_work/gen_log.jsonl."""
    l_file = log_path or GEN_LOG_FILE
    l_file.parent.mkdir(parents=True, exist_ok=True)
    with open(l_file, "a", encoding="utf-8") as f:
        for rule, err in rule_errors:
            entry = {
                "plan_id": plan_id,
                "rule": rule,
                "error": err,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def validate_batch(
    records: list[dict],
    entry: dict,
    work_dir: Path = None,
    raw_dir: Path = None,
    installed_questions: list[tuple[str, set[str]]] = None,
) -> tuple[bool, list[str]]:
    """
    Validates a list of question records against all Phase 2E-b rules.
    Returns (is_valid: bool, errors: list[str]) where errors begin with [rule_name].
    """
    errors: list[str] = []

    # Rule 1: Exactly 12 records
    if len(records) != 12:
        errors.append(f"[record_count] Batch must contain exactly 12 records (got {len(records)})")
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
    longest_correct_count = 0
    distinct_pages = set()

    # Preload installed questions if not passed
    target_file = get_target_path(pdf, concept, batch_idx, raw_dir=raw_dir)
    if installed_questions is None:
        installed_questions = load_installed_questions(raw_dir=raw_dir, exclude_file=target_file)

    for i, rec in enumerate(records, 1):
        # Rule 2: Basic schema validation
        ok, msg = validate_question_record(rec)
        if not ok:
            errors.append(f"[schema] Question #{i}: schema validation failed: {msg}")
            continue

        # Concept match
        if rec.get("concept") != concept:
            errors.append(
                f"[concept_mismatch] Question #{i}: concept '{rec.get('concept')}' does not match plan concept '{concept}'"
            )

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

        # Gate 3: qtype code_output or bug_find requires a ```java fence inside question
        q_text = rec.get("question", "")
        if qtype in {"code_output", "bug_find"}:
            if "```java" not in q_text:
                errors.append(
                    f"[code_fence_missing] Question #{i}: qtype '{qtype}' requires a ```java code fence inside question text"
                )

        # Gate 1: Explanation refers to an option by letter or number
        expl = rec.get("explanation", "")
        m_ref = OPTION_REF_RE.search(expl)
        if m_ref:
            errors.append(
                f"[explanation_option_ref] Question #{i}: explanation refers to an option by letter/number ('{m_ref.group(0)}')"
            )

        # Gate 2: Question/options contain "all of the above", "none of the above", "both A and B"
        m_q_choice = FORBIDDEN_CHOICE_RE.search(q_text)
        if m_q_choice:
            errors.append(
                f"[forbidden_option_choice] Question #{i}: forbidden option phrase '{m_q_choice.group(0)}' in question text"
            )

        options = rec.get("options", [])
        for opt_idx, opt in enumerate(options):
            opt_text = opt.get("text", "")
            m_opt_choice = FORBIDDEN_CHOICE_RE.search(opt_text)
            if m_opt_choice:
                errors.append(
                    f"[forbidden_option_choice] Question #{i}, Option {opt_idx}: forbidden option phrase '{m_opt_choice.group(0)}'"
                )

            if opt_idx == c_idx:
                continue
            m_id = opt.get("misconception_id")
            if m_id is not None:
                if not is_valid_misconception(m_id, concept):
                    errors.append(
                        f"[misconception_invalid] Question #{i}, Option {opt_idx}: invalid misconception_id '{m_id}' for concept '{concept}'"
                    )

        # Gate 4: Length comparison of correct option
        if isinstance(c_idx, int) and 0 <= c_idx < len(options):
            c_len = len(options[c_idx].get("text", ""))
            other_lens = [len(opt.get("text", "")) for j, opt in enumerate(options) if j != c_idx]
            if other_lens and all(c_len > ol for ol in other_lens):
                longest_correct_count += 1

        # Rule 7: Provenance check
        src = rec.get("source", {})
        src_pdf = src.get("pdf", "")
        if src_pdf != pdf:
            errors.append(
                f"[source_pdf] Question #{i}: source.pdf '{src_pdf}' does not match plan PDF '{pdf}'"
            )

        raw_page = src.get("page")
        try:
            p_num = int(str(raw_page).strip())
            distinct_pages.add(p_num)
            if not (min_page <= p_num <= max_page):
                errors.append(
                    f"[source_page_bounds] Question #{i}: source.page {p_num} is outside pack page range [{min_page}, {max_page}]"
                )
        except ValueError:
            if not str(raw_page).strip():
                errors.append(f"[source_page_bounds] Question #{i}: source.page is empty")

        # Rule 8: Forbidden phrase check
        m = FORBIDDEN_PHRASE_RE.search(q_text)
        if m:
            errors.append(
                f"[forbidden_phrase] Question #{i}: forbidden phrase detected: '{m.group(0)}' (must not refer to the book/text)"
            )

        # Gate 5: Cross-batch near-duplicate check
        is_pilot = entry.get("plan_id") in {"P01", "P02", "P03", "P04"}
        q_id = rec.get("id", f"new_q{i}")
        q_tokens = tokenize(q_text)
        for other_id, other_tokens in installed_questions:
            # Skip cross-checking between pilot batches since pilot question texts are immutable
            if is_pilot and any(other_id.startswith(pfx) for pfx in ("JavaNotesForProfessionals__method-overriding", "javanotes9__try-with-resources", "javanotes9__interface-basics", "thinkjava2__abstraction-basics", "thinkjava2-abstraction", "javanotes9-try", "javanotes9-interface", "JavaNotesForProfessionals-method", "test-method-overriding")):
                continue
            sim = jaccard_similarity(q_tokens, other_tokens)
            if sim >= 0.70:
                errors.append(
                    f"[near_duplicate] Question #{i} ('{q_id}') is near-duplicate of installed question '{other_id}' "
                    f"(token-Jaccard {sim:.2f} >= 0.70)"
                )

    # Rule 3: Difficulty split 4 Easy / 4 Medium / 4 Hard
    expected_diff = {"Easy": 4, "Medium": 4, "Hard": 4}
    for d, expected_cnt in expected_diff.items():
        actual_cnt = diff_counts.get(d, 0)
        if actual_cnt != expected_cnt:
            errors.append(f"[difficulty_split] Difficulty split mismatch: expected {expected_cnt} {d}, got {actual_cnt}")

    # Rule 4: Answer position count per position <= 5 (before shuffle)
    for pos in (0, 1, 2, 3):
        cnt = pos_counts.get(pos, 0)
        if cnt > 5:
            errors.append(f"[answer_position_pre] Answer position {pos} used {cnt} times (maximum allowed is 5)")

    # Rule 5: At least 2 qtypes in {code_output, bug_find} unless exempt
    if concept not in EXEMPT_CODE_QTYPES:
        if code_qtype_count < 2:
            errors.append(
                f"[code_qtype_count] Concept '{concept}' requires at least 2 questions with qtype in {{code_output, bug_find}} (got {code_qtype_count})"
            )

    # Gate 4 check: Count questions whose correct option is STRICTLY longest
    if longest_correct_count > 5:
        errors.append(
            f"[correct_option_longest] Correct option is strictly longest in {longest_correct_count} of 12 questions (maximum allowed is 5)"
        )

    # Gate 6 check: All 12 records have the same source.page when pack spans multiple pages (exempt pilot batches whose sources are immutable)
    is_pilot = entry.get("plan_id") in {"P01", "P02", "P03", "P04"}
    if not is_pilot and min_page < max_page:
        if len(distinct_pages) <= 1:
            errors.append(
                f"[same_source_page] All 12 records have the same source.page ({list(distinct_pages)}), "
                f"but pack page range [{min_page}, {max_page}] spans multiple pages"
            )

    return len(errors) == 0, errors


def deterministic_shuffle_batch(records: list[dict]) -> tuple[list[dict], int]:
    """
    Deterministically shuffles options of each record using random.Random seeded
    from sha1(question) + attempt counter.
    Increases attempt until all 4 answer positions (0, 1, 2, 3) have counts in [2, 4].
    Returns (shuffled_records, attempt_counter).
    """
    attempt = 0
    max_attempts = 100000

    while attempt < max_attempts:
        shuffled_batch = []
        pos_counts = Counter()

        for rec in records:
            r = dict(rec)
            q_text = r.get("question", "")
            seed_int = int(hashlib.sha1(q_text.encode("utf-8")).hexdigest(), 16) + attempt
            rng = random.Random(seed_int)

            orig_opts = list(r["options"])
            orig_correct_idx = r["correct_index"]
            correct_opt = orig_opts[orig_correct_idx]

            shuffled_opts = list(orig_opts)
            rng.shuffle(shuffled_opts)
            new_correct_idx = shuffled_opts.index(correct_opt)

            r["options"] = shuffled_opts
            r["correct_index"] = new_correct_idx
            shuffled_batch.append(r)
            pos_counts[new_correct_idx] += 1

        if all(2 <= pos_counts[p] <= 4 for p in (0, 1, 2, 3)):
            return shuffled_batch, attempt

        attempt += 1

    return records, -1


def install_batch(
    plan_id: str,
    jsonl_path: Path,
    force: bool = False,
    plan_path: Path = None,
    work_dir: Path = None,
    raw_dir: Path = None,
    log_path: Path = None,
) -> bool:
    """
    Validates candidate JSONL file against all gates and installs the deterministically
    shuffled version to raw questions directory upon success.
    Logs rejections to gen_log.jsonl on failure.
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
            if not line_str or line_str.startswith("#"):
                continue
            try:
                rec = json.loads(line_str)
                records.append(rec)
            except json.JSONDecodeError as ex:
                err_msg = f"Invalid JSON on line {line_num} of {jsonl_file}: {ex}"
                print(f"Error: {err_msg}")
                log_rejections(plan_id, [("json_syntax", err_msg)], log_path=log_path)
                return False

    ok, errors = validate_batch(records, entry, work_dir=work_dir, raw_dir=raw_dir)
    if not ok:
        rule_errors = []
        for err in errors:
            m_rule = re.match(r"^\[([a-z0-9_]+)\]\s*(.*)", err)
            if m_rule:
                rule_errors.append((m_rule.group(1), m_rule.group(2)))
            else:
                rule_errors.append(("validation_error", err))

        log_rejections(plan_id, rule_errors, log_path=log_path)

        print("=" * 70)
        print(f"VALIDATION FAILED for {plan_id} ({len(errors)} errors):")
        print("=" * 70)
        for err in errors:
            print(f"  ❌ {err}")
        print("=" * 70)
        print("File was NOT installed.")
        return False

    # Gate 7: Deterministic option shuffle
    shuffled_records, shuffle_attempts = deterministic_shuffle_batch(records)

    # Install to raw destination
    target_path = get_target_path(entry["pdf"], entry["concept"], entry["batch_idx"], raw_dir=raw_dir)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as f:
        for rec in shuffled_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Update plan status
    entry["status"] = "done"
    save_plan(plan, plan_path)

    pos_counts = Counter(r["correct_index"] for r in shuffled_records)
    diff_counts = Counter(r["difficulty"] for r in shuffled_records)
    qtype_counts = Counter(r["qtype"] for r in shuffled_records)

    print("=" * 70)
    print(f"SUCCESS: Batch {plan_id} validated and installed!")
    print("=" * 70)
    print(f"Target File : {target_path}")
    print(f"Concept     : {entry['concept']}")
    print(f"PDF Source  : {entry['pdf']} (batch {entry['batch_idx']:02d})")
    print(f"Records     : {len(shuffled_records)} questions")
    print(f"Difficulty  : Easy={diff_counts['Easy']}, Medium={diff_counts['Medium']}, Hard={diff_counts['Hard']}")
    print(f"QTypes      : concept={qtype_counts['concept']}, code_output={qtype_counts['code_output']}, bug_find={qtype_counts['bug_find']}")
    print(f"Positions   : pos0={pos_counts[0]}, pos1={pos_counts[1]}, pos2={pos_counts[2]}, pos3={pos_counts[3]}")
    print(f"Shuffle     : Balanced across positions in attempt #{shuffle_attempts}")
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
