"""
=============================================================================
EduGen - Question Bank Generation Reviewer (Phase 2E-a)
=============================================================================
Renders all installed batches into human-readable markdown at
data/bank_work/pilot_review.md and prints summary statistics to the console.

Usage:
    python tools/question_bank/gen_review.py
=============================================================================
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PLAN_FILE = BASE_DIR / "data" / "bank_work" / "gen_plan.json"
RAW_DIR = BASE_DIR / "rag" / "corpus" / "questions" / "raw"
REVIEW_FILE = BASE_DIR / "data" / "bank_work" / "pilot_review.md"

OPTION_LETTERS = ["A", "B", "C", "D"]


def load_plan(plan_path: Path = None) -> list[dict]:
    p_file = plan_path or PLAN_FILE
    if not p_file.exists():
        raise FileNotFoundError(f"Plan file not found: {p_file}. Run gen_plan.py first.")
    with open(p_file, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_review(plan_path: Path = None, review_path: Path = None) -> tuple[int, int, Counter, Counter, Counter]:
    plan = load_plan(plan_path)
    out_file = review_path or REVIEW_FILE
    out_file.parent.mkdir(parents=True, exist_ok=True)

    done_entries = [e for e in plan if e.get("status") == "done"]

    total_questions = 0
    diff_counter = Counter()
    qtype_counter = Counter()
    pos_counter = Counter()

    lines = []
    lines.append("# EduGen Question Bank - Generation Review Report")
    lines.append("")
    lines.append(f"> Auto-generated review of installed question batches. Total installed batches: **{len(done_entries)}**")
    lines.append("")

    for entry in done_entries:
        plan_id = entry["plan_id"]
        pdf = entry["pdf"]
        concept = entry["concept"]
        batch_idx = entry["batch_idx"]

        raw_filename = f"{pdf}__{concept}__b{batch_idx:02d}.jsonl"
        raw_path = RAW_DIR / raw_filename

        if not raw_path.exists():
            lines.append(f"## [{plan_id}] {concept} ({pdf})")
            lines.append(f"⚠️ *File missing at `{raw_path}`*\n")
            continue

        questions = []
        with open(raw_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    questions.append(json.loads(line))

        total_questions += len(questions)

        lines.append(f"## [{plan_id}] `{concept}` | {pdf} (Batch {batch_idx:02d})")
        lines.append(f"- **Source File:** `rag/corpus/questions/raw/{raw_filename}`")
        lines.append(f"- **Total Questions:** {len(questions)}")
        lines.append("")

        for q_idx, q in enumerate(questions, 1):
            diff = q.get("difficulty", "Unknown")
            qtype = q.get("qtype", "concept")
            c_idx = q.get("correct_index", 0)
            src = q.get("source", {})
            src_str = f"{src.get('pdf', pdf)}, p.{src.get('page', '?')}"

            diff_counter[diff] += 1
            qtype_counter[qtype] += 1
            pos_counter[c_idx] += 1

            lines.append(f"### Q{q_idx}. [{diff} | {qtype}] ({src_str})")
            lines.append("")
            lines.append(q.get("question", "").strip())
            lines.append("")

            lines.append("**Options:**")
            for opt_idx, opt in enumerate(q.get("options", [])):
                letter = OPTION_LETTERS[opt_idx] if opt_idx < 4 else str(opt_idx)
                opt_text = opt.get("text", "").strip()
                if opt_idx == c_idx:
                    lines.append(f"- **{letter})** {opt_text} ✅ **[CORRECT]**")
                else:
                    m_id = opt.get("misconception_id")
                    m_str = f" *(Misconception: `{m_id}`)*" if m_id else " *(careless / distractor)*"
                    lines.append(f"- **{letter})** {opt_text}{m_str}")
            lines.append("")

            explanation = q.get("explanation", "").strip()
            lines.append(f"**Explanation:** {explanation}")
            lines.append("")
            lines.append("---")
            lines.append("")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return len(done_entries), total_questions, diff_counter, qtype_counter, pos_counter


def print_stats_table(done_count: int, total_plan: int, total_q: int, diff: Counter, qtypes: Counter, pos: Counter):
    print("=" * 70)
    print("EduGen - Question Bank Review Summary (Phase 2E-a)")
    print("=" * 70)
    print(f"Batches Completed  : {done_count} / {total_plan} ({done_count / total_plan * 100:.1f}%)")
    print(f"Total Questions    : {total_q}")
    print("-" * 70)
    print("Difficulty Split   :")
    print(f"  Easy   : {diff.get('Easy', 0):3d} ({diff.get('Easy', 0) / max(1, total_q) * 100:.1f}%)")
    print(f"  Medium : {diff.get('Medium', 0):3d} ({diff.get('Medium', 0) / max(1, total_q) * 100:.1f}%)")
    print(f"  Hard   : {diff.get('Hard', 0):3d} ({diff.get('Hard', 0) / max(1, total_q) * 100:.1f}%)")
    print("-" * 70)
    print("Question Types     :")
    print(f"  concept     : {qtypes.get('concept', 0):3d}")
    print(f"  code_output : {qtypes.get('code_output', 0):3d}")
    print(f"  bug_find    : {qtypes.get('bug_find', 0):3d}")
    print("-" * 70)
    print("Answer Positions   :")
    for i in range(4):
        print(f"  Option {OPTION_LETTERS[i]} (index {i}) : {pos.get(i, 0):3d}")
    print("=" * 70)
    print(f"Full markdown review saved to: {REVIEW_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Render installed batches into markdown review and print stats.")
    args = parser.parse_args()

    plan = load_plan()
    done_count, total_q, diff, qtypes, pos = generate_review()
    print_stats_table(done_count, len(plan), total_q, diff, qtypes, pos)


if __name__ == "__main__":
    main()
