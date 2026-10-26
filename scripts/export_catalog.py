"""
=============================================================================
EduGen - Misconception Catalog Export for LLM Grounding
=============================================================================
Exports misconception catalog into compact Markdown files for LLM prompt context:
  docs/catalog_for_llm/<module-id>.md  (one per module)
  docs/catalog_for_llm/all.md          (consolidated catalog across all modules)

Format per concept:
  ## <concept-tag> - <title>
  summary: <one line summary from core/concepts.py>
  - <misconception-id> | <facet> | <wrong_belief>

Usage:
    python scripts/export_catalog.py [--out docs/catalog_for_llm]
=============================================================================
"""

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS, MODULES
from core.misconceptions import MISCONCEPTIONS, misconceptions_for

HEADER_DIRECTIVE = (
    "<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values "
    "for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from "
    "this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->\n"
)


def render_concept_section(concept_tag: str) -> str:
    """Render a single concept section in compact markdown format."""
    c_info = CONCEPTS[concept_tag]
    title = c_info["title"]
    summary = c_info.get("summary", "").strip()
    misconceptions = misconceptions_for(concept_tag)

    lines = [
        f"## {concept_tag} - {title}",
        f"summary: {summary}",
    ]
    for m in misconceptions:
        lines.append(f"- {m['id']} | {m['facet']} | {m['wrong_belief']}")
    lines.append("")  # trailing blank line
    return "\n".join(lines)


def export_catalog(out_dir_path: str = "docs/catalog_for_llm"):
    out_dir = Path(out_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Group concepts by module
    module_concepts = defaultdict(list)
    for c_tag, c_info in CONCEPTS.items():
        module_concepts[c_info["module"]].append(c_tag)

    exported_files = []

    # 1. Export per-module markdown files
    for mod_id, mod_info in MODULES.items():
        mod_file = out_dir / f"{mod_id}.md"
        mod_lines = [
            HEADER_DIRECTIVE,
            f"# Misconception Catalog - {mod_info['title']}",
            f"{mod_info.get('blurb', '')}\n",
        ]
        for c_tag in module_concepts[mod_id]:
            mod_lines.append(render_concept_section(c_tag))

        with open(mod_file, "w", encoding="utf-8") as f:
            f.write("\n".join(mod_lines))
        exported_files.append(mod_file)

    # 2. Export consolidated all.md
    all_file = out_dir / "all.md"
    all_lines = [
        HEADER_DIRECTIVE,
        "# EduGen Canonical Misconception Catalog (All Modules)\n",
    ]
    for mod_id, mod_info in MODULES.items():
        all_lines.append(f"# Module: {mod_info['title']} ({mod_id})\n")
        for c_tag in module_concepts[mod_id]:
            all_lines.append(render_concept_section(c_tag))

    with open(all_file, "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines))
    exported_files.append(all_file)

    return exported_files


def main():
    parser = argparse.ArgumentParser(description="Export misconception catalog into Markdown files for LLM prompt context.")
    parser.add_argument("--out", default="docs/catalog_for_llm", help="Target output directory for exported Markdown files.")
    args = parser.parse_args()

    files = export_catalog(args.out)
    print(f"Exported {len(files)} catalog files to: {args.out}")
    for f in files:
        print(f"  - {f.name}")


if __name__ == "__main__":
    main()
