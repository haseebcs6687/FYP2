import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict, Counter

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import core.misconceptions as cm

RAW_DIR = REPO_ROOT / "rag" / "corpus" / "questions" / "raw"
AUDIT_DIR = REPO_ROOT / "data" / "bank_work" / "tagaudit"


def cmd_export(args):
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(RAW_DIR.glob("*.jsonl"))
    print(f"Exporting blind audit files for {len(raw_files)} batches...")

    for fpath in raw_files:
        batch_name = fpath.stem
        md_path = AUDIT_DIR / f"{batch_name}.blind.md"
        labels_path = AUDIT_DIR / f"{batch_name}.labels.json"

        questions = []
        with open(fpath, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if line:
                    questions.append(json.loads(line))

        if not questions:
            continue

        concept = questions[0]["concept"]
        catalog = cm.misconceptions_for(concept)

        # Build blind markdown
        md_lines = []
        md_lines.append(f"# Blind Tag Audit: {batch_name}")
        md_lines.append(f"**Concept:** `{concept}`\n")

        md_lines.append("## Concept Catalog")
        for m in catalog:
            md_lines.append(f"- **`{m['id']}`**: {m['wrong_belief']}")
        md_lines.append("\n---\n")

        md_lines.append("## Questions")
        labels_dict = {}

        for q_idx, q in enumerate(questions, 1):
            qid = q["question_id"]
            c_idx = q["correct_index"]
            md_lines.append(f"### Q{q_idx}: `{qid}` ({q['difficulty']} | {q['qtype']})")
            md_lines.append(f"{q['question']}\n")

            q_labels = {}
            for opt_idx, opt in enumerate(q["options"]):
                if opt_idx == c_idx:
                    md_lines.append(f"- `[{opt_idx}]` **[CORRECT]** {opt['text']}")
                else:
                    md_lines.append(f"- `[{opt_idx}]` {opt['text']}")
                    q_labels[str(opt_idx)] = None

            labels_dict[qid] = q_labels
            md_lines.append("")

        with open(md_path, "w", encoding="utf-8") as mdfp:
            mdfp.write("\n".join(md_lines) + "\n")

        # Write labels.json if it doesn't exist yet
        if not labels_path.exists() or args.overwrite_labels:
            with open(labels_path, "w", encoding="utf-8") as lfp:
                json.dump(labels_dict, lfp, indent=2, ensure_ascii=False)

    print(f"Export complete. Markdown and empty labels written to {AUDIT_DIR}")


def cmd_merge(args):
    raw_files = sorted(RAW_DIR.glob("*.jsonl"))
    total_wrong_options = 0
    agreed_count = 0
    concept_totals = defaultdict(int)
    concept_agreed = defaultdict(int)
    null_counts_per_question = Counter()
    verified_catalog_counts = Counter()

    for fpath in raw_files:
        batch_name = fpath.stem
        labels_path = AUDIT_DIR / f"{batch_name}.labels.json"
        if not labels_path.exists():
            print(f"Error: Missing labels file {labels_path}")
            sys.exit(1)

        with open(labels_path, "r", encoding="utf-8") as lfp:
            labels_data = json.load(lfp)

        updated_records = []
        with open(fpath, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                qid = rec["question_id"]
                concept = rec["concept"]
                c_idx = rec["correct_index"]
                q_labels = labels_data.get(qid, {})

                q_null_wrong = 0
                for opt_idx, opt in enumerate(rec["options"]):
                    if opt_idx == c_idx:
                        opt["misconception_id"] = None
                    else:
                        total_wrong_options += 1
                        concept_totals[concept] += 1
                        existing_mid = opt.get("misconception_id")
                        blind_mid = q_labels.get(str(opt_idx))

                        if blind_mid is not None and blind_mid == existing_mid:
                            agreed_count += 1
                            concept_agreed[concept] += 1
                            opt["misconception_id"] = existing_mid
                            verified_catalog_counts[existing_mid] += 1
                        else:
                            opt["misconception_id"] = None
                            q_null_wrong += 1

                null_counts_per_question[q_null_wrong] += 1
                updated_records.append(rec)

        if not args.dry_run:
            with open(fpath, "w", encoding="utf-8") as fp:
                for rec in updated_records:
                    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Print summary statistics
    agree_pct = (agreed_count / total_wrong_options * 100) if total_wrong_options > 0 else 0.0
    print("=" * 70)
    print("EduGen - Blind Tag Audit Results")
    print("=" * 70)
    print(f"Total wrong options audited : {total_wrong_options}")
    print(f"Agreed tags count          : {agreed_count} ({agree_pct:.1f}%)")
    print(f"Non-agreed (cleared to null): {total_wrong_options - agreed_count}")
    print("-" * 70)

    print("\n--- Per-Concept Agreement Table ---")
    header = f"{'Concept':<35} | {'Wrong Opts':<10} | {'Agreed':<8} | {'Agreement %':<10}"
    print(header)
    print("-" * len(header))
    concept_rows = []
    for concept in sorted(concept_totals.keys()):
        tot = concept_totals[concept]
        agr = concept_agreed[concept]
        pct = (agr / tot * 100) if tot > 0 else 0.0
        concept_rows.append((concept, tot, agr, pct))

    for c, tot, agr, pct in concept_rows:
        print(f"{c:<35} | {tot:<10} | {agr:<8} | {pct:>9.1f}%")

    print("\n--- Distribution of Null Wrong Options per Question ---")
    total_qs = sum(null_counts_per_question.values())
    for k in sorted(null_counts_per_question.keys()):
        cnt = null_counts_per_question[k]
        pct = (cnt / total_qs * 100) if total_qs > 0 else 0.0
        print(f"  {k} null wrong options: {cnt:>3} questions ({pct:>5.1f}%)")

    # Catalog IDs with fewer than 3 verified uses
    all_catalog_ids = [m["id"] for m in cm.MISCONCEPTIONS.values()]
    low_use_ids = [cid for cid in sorted(all_catalog_ids) if verified_catalog_counts[cid] < 3]

    print(f"\n--- Catalog IDs with Fewer than 3 Verified Uses ({len(low_use_ids)} total) ---")
    for cid in low_use_ids:
        print(f"  [{verified_catalog_counts[cid]} uses] {cid}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Blind tag audit tooling for EduGen")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_p = subparsers.add_parser("export", help="Export blind audit markdown and blank labels.json")
    export_p.add_argument("--overwrite-labels", action="store_true", help="Overwrite existing labels.json files")

    merge_p = subparsers.add_parser("merge", help="Merge blind labels with raw question bank")
    merge_p.add_argument("--dry-run", action="store_true", help="Calculate stats without writing to disk")

    args = parser.parse_args()
    if args.command == "export":
        cmd_export(args)
    elif args.command == "merge":
        cmd_merge(args)


if __name__ == "__main__":
    main()
