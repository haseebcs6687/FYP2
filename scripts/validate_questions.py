"""
=============================================================================
EduGen - Question Bank Validator
=============================================================================
Validates question records against the canonical schema (docs/QUESTION_FORMAT.md).
Performs structural checks, misconception catalog alignment, and duplicate detection
(exact SHA-256 normalized hash & token-Jaccard >= 0.85 within the same concept).

Usage:
    python scripts/validate_questions.py <file-or-folder> [--out rag/corpus/questions_validated]
=============================================================================
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS
from core.misconceptions import MISCONCEPTIONS, is_valid_misconception

VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}
VALID_QTYPES = {"concept", "code_output", "bug_find"}
JACCARD_THRESHOLD = 0.85
MIN_QUESTION_LENGTH = 15


def tokenize(text: str) -> set:
    """Extract lowercase alphanumeric tokens for near-duplicate Jaccard comparison."""
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def jaccard_similarity(tokens_a: set, tokens_b: set) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def normalize_text_for_hash(text: str) -> str:
    """Normalize text by collapsing whitespace and lowercasing."""
    words = re.findall(r"\w+", (text or "").lower())
    return " ".join(words)


def compute_text_hash(text: str) -> str:
    norm = normalize_text_for_hash(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def validate_question_record(rec: dict) -> tuple[bool, str]:
    """
    Validate a single question record against all QUESTION_FORMAT rules.
    Returns (is_valid: bool, error_message: str).
    """
    if not isinstance(rec, dict):
        return False, "Record must be a JSON object"

    # Required top-level fields
    required_fields = ["concept", "difficulty", "qtype", "question", "options", "correct_index", "explanation", "source"]
    for field in required_fields:
        if field not in rec:
            return False, f"Missing required field: '{field}'"

    # 1. Concept
    concept = rec.get("concept")
    if not isinstance(concept, str) or concept not in CONCEPTS:
        return False, f"Invalid or unknown concept tag: '{concept}'"

    # 2. Difficulty
    diff = rec.get("difficulty")
    if diff not in VALID_DIFFICULTIES:
        return False, f"Invalid difficulty: '{diff}'. Must be one of {sorted(VALID_DIFFICULTIES)}"

    # 3. Question type
    qtype = rec.get("qtype")
    if qtype not in VALID_QTYPES:
        return False, f"Invalid qtype: '{qtype}'. Must be one of {sorted(VALID_QTYPES)}"

    # 4. Question text & code fences
    question = rec.get("question")
    if not isinstance(question, str) or len(question.strip()) < MIN_QUESTION_LENGTH:
        return False, f"Question text too short (< {MIN_QUESTION_LENGTH} characters) or not a string"

    fence_count = question.count("```")
    if fence_count % 2 != 0:
        return False, f"Unbalanced markdown code fences (found {fence_count} '```' markers)"

    # 5. Options
    options = rec.get("options")
    if not isinstance(options, list) or len(options) != 4:
        return False, f"Options must be an array of exactly 4 items (got {len(options) if isinstance(options, list) else type(options)})"

    seen_texts = set()
    for idx, opt in enumerate(options):
        if not isinstance(opt, dict):
            return False, f"Option {idx} must be an object with 'text' and 'misconception_id'"
        if "text" not in opt or not isinstance(opt["text"], str) or not opt["text"].strip():
            return False, f"Option {idx} has missing or empty 'text'"
        norm_opt_text = opt["text"].strip()
        if norm_opt_text in seen_texts:
            return False, f"Duplicate option text found at index {idx}: '{norm_opt_text[:30]}...'"
        seen_texts.add(norm_opt_text)

        if "misconception_id" not in opt:
            return False, f"Option {idx} missing 'misconception_id' field"

    # 6. Correct index
    c_idx = rec.get("correct_index")
    if not isinstance(c_idx, int) or c_idx not in (0, 1, 2, 3) or isinstance(c_idx, bool):
        return False, f"correct_index must be an integer 0, 1, 2, or 3 (got {c_idx})"

    # Correct option must have misconception_id == None
    correct_opt = options[c_idx]
    if correct_opt.get("misconception_id") is not None:
        return False, f"Correct option at index {c_idx} must have 'misconception_id' = null (got '{correct_opt.get('misconception_id')}')"

    # Distractor validation
    null_distractor_count = 0
    used_distractor_misconceptions = set()

    for idx, opt in enumerate(options):
        if idx == c_idx:
            continue
        m_id = opt.get("misconception_id")
        if m_id is None:
            null_distractor_count += 1
            if null_distractor_count > 1:
                return False, "At most 1 wrong distractor may have 'misconception_id' = null (pure careless/unrelated)"
        else:
            if not isinstance(m_id, str):
                return False, f"Distractor at index {idx} has invalid non-string misconception_id: {m_id}"
            if not is_valid_misconception(m_id, concept):
                return False, f"Distractor at index {idx} has invalid misconception_id '{m_id}' for concept '{concept}'"
            if m_id in used_distractor_misconceptions:
                return False, f"Duplicate misconception_id '{m_id}' used across multiple distractors in the same question"
            used_distractor_misconceptions.add(m_id)

    # 7. Explanation
    explanation = rec.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return False, "Explanation must be a non-empty string"

    # 8. Source
    source = rec.get("source")
    if not isinstance(source, dict):
        return False, "Source must be an object with 'pdf' and 'page'"
    if not source.get("pdf") or not isinstance(source.get("pdf"), str):
        return False, "Source must have a non-empty 'pdf' string"
    if "page" not in source or source.get("page") is None or str(source.get("page")).strip() == "":
        return False, "Source must have a non-empty 'page' field"

    return True, ""


class QuestionValidator:
    """
    Validates a stream or collection of question records, checks exact & near duplicates,
    writes accepted/rejected outputs, and generates comprehensive summary statistics.
    """

    def __init__(self, out_dir: str = "rag/corpus/questions_validated"):
        self.out_dir = Path(out_dir)
        self.accepted = []
        self.rejected = []
        self.exact_hashes = set()  # set of normalized question hashes
        self.concept_tokens = defaultdict(list)  # concept -> list of (tokens, question_text)

        # Summary tracking
        self.concept_diff_counts = defaultdict(lambda: Counter())
        self.qtype_counts = Counter()
        self.used_misconceptions = set()
        self.reject_reasons = Counter()

    def validate_and_add(self, rec: dict, raw_line: str = None) -> bool:
        """
        Validate single record and perform deduplication. Returns True if accepted, False otherwise.
        """
        is_valid, reason = validate_question_record(rec)
        if not is_valid:
            rej_entry = dict(rec) if isinstance(rec, dict) else {"raw": raw_line or str(rec)}
            rej_entry["reason"] = reason
            self.rejected.append(rej_entry)
            self.reject_reasons[reason] += 1
            return False

        # Deduplication checks
        q_text = rec["question"]
        q_hash = compute_text_hash(q_text)
        if q_hash in self.exact_hashes:
            rej_entry = dict(rec)
            rej_entry["reason"] = "Exact duplicate question text (hash collision)"
            self.rejected.append(rej_entry)
            self.reject_reasons[rej_entry["reason"]] += 1
            return False

        concept = rec["concept"]
        tokens = tokenize(q_text)
        for existing_tokens, _ in self.concept_tokens[concept]:
            sim = jaccard_similarity(tokens, existing_tokens)
            if sim >= JACCARD_THRESHOLD:
                rej_entry = dict(rec)
                rej_entry["reason"] = f"Near-duplicate question (token-Jaccard {sim:.2f} >= {JACCARD_THRESHOLD}) in concept '{concept}'"
                self.rejected.append(rej_entry)
                self.reject_reasons[rej_entry["reason"]] += 1
                return False

        # Accept question
        self.exact_hashes.add(q_hash)
        self.concept_tokens[concept].append((tokens, q_text))
        self.accepted.append(rec)

        # Update stats
        self.concept_diff_counts[concept][rec["difficulty"]] += 1
        self.qtype_counts[rec["qtype"]] += 1
        for opt in rec["options"]:
            mid = opt.get("misconception_id")
            if mid:
                self.used_misconceptions.add(mid)

        return True

    def process_file(self, file_path: Path):
        """Process a single .jsonl file."""
        if not file_path.exists():
            print(f"Error: file not found: {file_path}")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                try:
                    rec = json.loads(raw)
                except Exception as exc:
                    self.rejected.append({"raw": raw, "reason": f"Invalid JSON syntax at line {line_no}: {exc}"})
                    self.reject_reasons["Invalid JSON syntax"] += 1
                    continue

                self.validate_and_add(rec, raw_line=raw)

    def process_input(self, input_target: str):
        """Process either a file or a folder of .jsonl files."""
        p = Path(input_target)
        if not p.exists():
            print(f"Error: path does not exist: {p}")
            sys.exit(1)

        if p.is_file():
            self.process_file(p)
        else:
            files = sorted(list(p.glob("*.jsonl")) + list(p.glob("**/*.jsonl")))
            if not files:
                print(f"Warning: No .jsonl files found under {p}")
            for f in files:
                self.process_file(f)

    def write_outputs(self):
        """Write accepted.jsonl and rejected.jsonl to out_dir."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        acc_path = self.out_dir / "accepted.jsonl"
        rej_path = self.out_dir / "rejected.jsonl"

        with open(acc_path, "w", encoding="utf-8") as f:
            for item in self.accepted:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        with open(rej_path, "w", encoding="utf-8") as f:
            for item in self.rejected:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        return acc_path, rej_path

    def print_summary(self):
        """Print comprehensive summary tables."""
        total_accepted = len(self.accepted)
        total_rejected = len(self.rejected)
        total_records = total_accepted + total_rejected

        print("\n" + "=" * 70)
        print("  EduGen Question Validation Summary")
        print("=" * 70)
        print(f"Total processed: {total_records}  |  Accepted: {total_accepted}  |  Rejected: {total_rejected}")

        # 1. Counts per Concept x Difficulty
        print("\n--- Question Counts per Concept x Difficulty ---")
        header = f"{'Concept':<35} | {'Easy':<6} | {'Medium':<6} | {'Hard':<6} | {'Total':<6}"
        print(header)
        print("-" * len(header))
        all_concepts = list(CONCEPTS.keys())
        for c in all_concepts:
            counts = self.concept_diff_counts[c]
            easy = counts.get("Easy", 0)
            med = counts.get("Medium", 0)
            hard = counts.get("Hard", 0)
            tot = easy + med + hard
            if tot > 0:
                print(f"{c:<35} | {easy:<6} | {med:<6} | {hard:<6} | {tot:<6}")
        print("-" * len(header))

        # 2. Counts per Question Type
        print("\n--- Question Counts per Type (qtype) ---")
        for qt in sorted(VALID_QTYPES):
            print(f"  {qt:<15}: {self.qtype_counts.get(qt, 0)}")

        # 3. Misconception Catalog Coverage
        all_misconceptions = set(MISCONCEPTIONS.keys())
        unused_misconceptions = sorted(list(all_misconceptions - self.used_misconceptions))
        used_count = len(self.used_misconceptions & all_misconceptions)
        total_misconceptions = len(all_misconceptions)
        coverage_pct = (used_count / total_misconceptions * 100) if total_misconceptions > 0 else 0.0

        print("\n--- Misconception Catalog Coverage ---")
        print(f"  Catalog total  : {total_misconceptions}")
        print(f"  Targeted by Qs : {used_count} ({coverage_pct:.1f}%)")
        print(f"  Never used     : {len(unused_misconceptions)}")
        if unused_misconceptions:
            print("  Unused misconception IDs (sample / total):")
            sample = unused_misconceptions[:10]
            for m in sample:
                print(f"    - {m}")
            if len(unused_misconceptions) > 10:
                print(f"    ... and {len(unused_misconceptions) - 10} more.")

        # 4. Reject Reasons Breakdown
        if total_rejected > 0:
            print("\n--- Reject Reasons Breakdown ---")
            for reason, cnt in self.reject_reasons.most_common():
                print(f"  [{cnt:>3}] {reason}")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Validate EduGen JSON Lines question bank files.")
    parser.add_argument("input_target", help="File (.jsonl) or directory containing .jsonl files to validate.")
    parser.add_argument("--out", default="rag/corpus/questions_validated", help="Output directory for accepted.jsonl and rejected.jsonl.")
    args = parser.parse_args()

    validator = QuestionValidator(out_dir=args.out)
    validator.process_input(args.input_target)
    acc_path, rej_path = validator.write_outputs()
    validator.print_summary()
    print(f"Accepted records written to: {acc_path}")
    print(f"Rejected records written to: {rej_path}")


if __name__ == "__main__":
    main()
