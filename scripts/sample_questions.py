"""
=============================================================================
EduGen - Question Bank Sampling Tool
=============================================================================
Usage:
    python scripts/sample_questions.py <accepted.jsonl or folder> --n 10 [--concept TAG] [--qtype code_output]

Displays N questions in an inspectable, human-readable format:
  - Concept, Difficulty, Question Type
  - Question text (including Java code fences)
  - Options labeled A-D with correct option marked
  - Misconception title for each distractor
  - Pedagogical explanation
  - Source provenance (PDF & page)
=============================================================================
"""

import argparse
import json
import random
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS
from core.misconceptions import MISCONCEPTIONS


def load_questions_from_path(target_path: Path) -> list[dict]:
    """Load JSON lines questions from a single file or directory of .jsonl files."""
    questions = []
    if target_path.is_file():
        files = [target_path]
    elif target_path.is_dir():
        files = sorted(list(target_path.glob("*.jsonl")) + list(target_path.glob("**/*.jsonl")))
    else:
        print(f"Error: Path does not exist: {target_path}")
        sys.exit(1)

    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                try:
                    data = json.loads(raw)
                    # If this came from a rejected file with embedded original, unwrap it
                    if "record" in data and isinstance(data["record"], dict):
                        data = data["record"]
                    questions.append(data)
                except Exception as exc:
                    continue
    return questions


def format_question_human_readable(q: dict, index: int, total: int) -> str:
    """Format a single question record into a clear, human-readable string."""
    concept = q.get("concept", "unknown")
    difficulty = q.get("difficulty", "unknown")
    qtype = q.get("qtype", "unknown")
    c_index = q.get("correct_index", -1)
    source = q.get("source") or {}
    pdf = source.get("pdf", "N/A")
    page = source.get("page", "N/A")

    c_title = CONCEPTS.get(concept, {}).get("title", concept)

    lines = [
        "=" * 80,
        f"[{index}/{total}] Concept: {concept} ({c_title}) | Difficulty: {difficulty} | Type: {qtype}",
        f"Source: {pdf} (Page/Ref: {page})",
        "-" * 80,
        q.get("question", "").strip(),
        "",
        "Options:",
    ]

    labels = ["A", "B", "C", "D"]
    options = q.get("options") or []
    for idx, opt in enumerate(options):
        label = labels[idx] if idx < len(labels) else f"({idx})"
        if isinstance(opt, dict):
            opt_text = opt.get("text", "")
            mid = opt.get("misconception_id")
        else:
            opt_text = str(opt)
            mid = None

        if idx == c_index:
            lines.append(f"  [X] {label}) {opt_text}  <-- [CORRECT ANSWER]")
        else:
            if mid and mid in MISCONCEPTIONS:
                m_info = MISCONCEPTIONS[mid]
                m_label = f"--> Misconception: \"{m_info['title']}\" ({mid})"
            elif mid:
                m_label = f"--> Misconception: {mid}"
            else:
                m_label = "--> [Careless / Unrelated Distractor]"
            lines.append(f"  [ ] {label}) {opt_text}  {m_label}")

    lines.append("")
    lines.append("Explanation:")
    lines.append(f"  {q.get('explanation', '').strip()}")
    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Sample and inspect questions from EduGen question bank.")
    parser.add_argument("path", help="Path to a .jsonl file or folder containing .jsonl question banks.")
    parser.add_argument("--n", type=int, default=10, help="Number of questions to sample (default: 10).")
    parser.add_argument("--concept", default=None, help="Optional concept tag filter.")
    parser.add_argument("--qtype", default=None, choices=["concept", "code_output", "bug_find"], help="Optional question type filter.")
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed.")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    target_path = Path(args.path)
    all_questions = load_questions_from_path(target_path)
    if not all_questions:
        print(f"No questions found under: {target_path}")
        return

    # Filter
    filtered = all_questions
    if args.concept:
        filtered = [q for q in filtered if q.get("concept") == args.concept]
    if args.qtype:
        filtered = [q for q in filtered if q.get("qtype") == args.qtype]

    total_matching = len(filtered)
    print(f"\nLoaded {len(all_questions)} total question(s). Matching filters: {total_matching}")
    if total_matching == 0:
        print("No questions match the specified criteria.")
        return

    sample_size = min(args.n, total_matching)
    sampled = random.sample(filtered, sample_size)

    for i, q in enumerate(sampled, start=1):
        print("\n" + format_question_human_readable(q, i, sample_size))


if __name__ == "__main__":
    main()
