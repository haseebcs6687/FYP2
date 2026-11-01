"""
=============================================================================
EduGen - Verified Question Pool Status & Catalog Coverage (Phase 4C)
=============================================================================
Generates a table of Concept x Difficulty with counts of verified active
questions plus number of distinct catalog misconceptions covered per concept.
Writes output to docs/POOL_STATUS.md and lists the 10 emptiest cells.
=============================================================================
"""

import json
import sqlite3
import sys
from pathlib import Path

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS, concept_title
from core.db import get_db
from core.misconceptions import misconceptions_for


def analyze_pool():
    conn = get_db()
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, concept, difficulty, tags_json
        FROM questions
        WHERE pool_status = 'active' AND verified = 1
    """).fetchall()
    conn.close()

    # Aggregate counts by (concept, difficulty) and extract covered misconceptions
    counts = {}
    covered_mids = {c: set() for c in CONCEPTS}

    for c in CONCEPTS:
        for d in ("Easy", "Medium", "Hard"):
            counts[(c, d)] = 0

    for r in rows:
        c = r["concept"]
        d = r["difficulty"]
        if (c, d) in counts:
            counts[(c, d)] += 1

        t_data = {}
        try:
            t_data = json.loads(r["tags_json"] or "{}")
        except Exception:
            pass

        mids = t_data.get("option_misconception_ids") or []
        for m in mids:
            if m and c in covered_mids:
                covered_mids[c].add(m)

    # Prepare markdown table
    md_lines = [
        "# EduGen - Verified Question Pool Status",
        "",
        "This document tracks the verified active question pool across all 44 canonical concepts",
        "and 3 difficulty tiers (Easy, Medium, Hard), alongside catalog misconception coverage.",
        "",
        "| Concept | Easy | Medium | Hard | Total | Misconceptions Covered |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    total_easy = sum(counts[(c, "Easy")] for c in CONCEPTS)
    total_med = sum(counts[(c, "Medium")] for c in CONCEPTS)
    total_hard = sum(counts[(c, "Hard")] for c in CONCEPTS)
    total_all = total_easy + total_med + total_hard

    cell_list = []

    for c in sorted(CONCEPTS):
        e = counts[(c, "Easy")]
        m = counts[(c, "Medium")]
        h = counts[(c, "Hard")]
        tot = e + m + h
        cat = misconceptions_for(c)
        cat_len = len(cat)
        cov_len = len(covered_mids[c])
        cov_str = f"{cov_len}/{cat_len}"

        md_lines.append(f"| `{c}` | {e} | {m} | {h} | **{tot}** | {cov_str} |")

        cell_list.append((c, "Easy", e))
        cell_list.append((c, "Medium", m))
        cell_list.append((c, "Hard", h))

    md_lines.append(f"| **TOTAL** | **{total_easy}** | **{total_med}** | **{total_hard}** | **{total_all}** | - |")
    md_lines.append("")

    # Identify 10 emptiest concept/difficulty cells
    cell_list.sort(key=lambda item: (item[2], item[0], item[1]))
    emptiest_10 = cell_list[:10]

    md_lines.append("## Top 10 Emptiest Concept/Difficulty Cells")
    md_lines.append("")
    md_lines.append("The following cells have the lowest coverage and should be prioritized for generation:")
    md_lines.append("")
    for rank, (c, d, cnt) in enumerate(emptiest_10, 1):
        md_lines.append(f"{rank}. `{c}` ({d}) — **{cnt}** verified question(s)")

    md_content = "\n".join(md_lines) + "\n"

    # Write to docs/POOL_STATUS.md
    docs_dir = BASE_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_file = docs_dir / "POOL_STATUS.md"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    print("=" * 80)
    print("VERIFIED QUESTION POOL STATUS")
    print(f"Total verified active questions in pool: {total_all}")
    print(f"Pool status documentation written to: {out_file}")
    print("=" * 80)
    print("Top 10 Emptiest Concept / Difficulty Cells:")
    for rank, (c, d, cnt) in enumerate(emptiest_10, 1):
        print(f"  {rank:>2}. {c:<28} [{d:<6}] : {cnt} questions")
    print("=" * 80)


if __name__ == "__main__":
    analyze_pool()

