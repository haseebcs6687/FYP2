"""
=============================================================================
EduGen - Build Prebuilt Diagnostic Sets (Phase 4B)
=============================================================================
Builds prebuilt diagnostic quiz sets through the full quality pipeline:
  - Generates diagnostic blueprint (12 foundational concept slots).
  - Verifier, Java check (if available), deduplication across sets.
  - Writes to rag/corpus/diagnostic/set_A.json, set_B.json, etc.
  - Reports any set that ended with fewer than 12 verified questions.
=============================================================================
"""

import argparse
from datetime import datetime
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Ensure stdout is UTF-8 encoded and unbuffered
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from app import create_app
from core.quiz_engine import build_blueprint


def build_sets(num_sets=3):
    app = create_app()
    with app.app_context():
        clarifier = app.extensions["edugen"]["cc"]
        diag_dir = BASE_DIR / "rag" / "corpus" / "diagnostic"
        diag_dir.mkdir(parents=True, exist_ok=True)

        print("=" * 70)
        print(f"Building {num_sets} Prebuilt Diagnostic Sets (Phase 4B Quality Pipeline)")
        print(f"Target directory: {diag_dir}")
        print("=" * 70)

        all_prior_questions = []
        shortfall_sets = []

        for i in range(num_sets):
            letter = chr(ord("A") + i)
            set_name = f"set_{letter}"
            print(f"\n[Set {letter}] Generating 12-question diagnostic blueprint...")

            slots = build_blueprint(kind="diagnostic")
            payload = clarifier.generate_quiz_from_blueprint(
                slots,
                prior_questions=all_prior_questions,
                allow_partial=True,
            )

            questions = list(payload.get("questions") or [])
            build_report = payload.get("build_report") or {}
            accepted_count = len(questions)

            # Targeted completion if any concept slots were missing
            if accepted_count < 12:
                accepted_concepts = {q.get("concept") for q in questions if q.get("concept")}
                missing_slots = [s for s in slots if s.get("concept") not in accepted_concepts]
                if missing_slots:
                    print(f"  >>> Attempting targeted completion for {len(missing_slots)} missing slot(s)...")
                    retry_payload = clarifier.generate_quiz_from_blueprint(
                        missing_slots,
                        prior_questions=all_prior_questions + questions,
                        allow_partial=True,
                    )
                    extra_qs = retry_payload.get("questions") or []
                    for eq in extra_qs:
                        if eq.get("concept") not in accepted_concepts:
                            questions.append(eq)
                            accepted_concepts.add(eq.get("concept"))
                            if len(questions) >= 12:
                                break
                    accepted_count = len(questions)
                    # Merge report
                    retry_rep = retry_payload.get("build_report") or {}
                    build_report["accepted"] = accepted_count
                    for rk, rv in (retry_rep.get("rejected_by_reason") or {}).items():
                        build_report["rejected_by_reason"][rk] = build_report["rejected_by_reason"].get(rk, 0) + rv
                    build_report["verifier_tags_removed"] = build_report.get("verifier_tags_removed", 0) + retry_rep.get("verifier_tags_removed", 0)
                    for tk, tv in (retry_rep.get("stage_timings_ms") or {}).items():
                        build_report["stage_timings_ms"][tk] = round(build_report["stage_timings_ms"].get(tk, 0.0) + tv, 2)

            output_record = {
                "set_name": set_name,
                "concept": "diagnostic",
                "difficulty": "diagnostic",
                "questions": questions,
                "total_generated": accepted_count,
                "grounded": payload.get("grounded", False),
                "sources": payload.get("sources", []),
                "model": payload.get("model"),
                "generated_by": payload.get("generated_by", "llm_rag"),
                "build_report": build_report,
                "created_at": datetime.now().isoformat(),
            }

            out_path = diag_dir / f"{set_name}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output_record, f, indent=2, ensure_ascii=False)

            print(f"[Set {letter}] Saved to {out_path} ({accepted_count}/12 questions verified).")
            print(f"  Stage Timings: {build_report.get('stage_timings_ms')}")
            print(f"  Rejections: {build_report.get('rejected_by_reason')}")
            print(f"  Verifier Tags Removed: {build_report.get('verifier_tags_removed', 0)}")
            print(f"  Java Check: {build_report.get('java_check')}")

            if accepted_count < 12:
                shortfall_msg = f"WARNING: {set_name} ended with {accepted_count} verified questions (< 12)!"
                print(f"  >>> {shortfall_msg}")
                shortfall_sets.append((set_name, accepted_count))
            else:
                print(f"  >>> {set_name} successfully verified 12/12 questions.")

            all_prior_questions.extend(questions)

        print("\n" + "=" * 70)
        print("Diagnostic Sets Build Summary")
        print("=" * 70)
        if shortfall_sets:
            print("[REPORT] The following sets ended with fewer than 12 verified questions:")
            for sname, count in shortfall_sets:
                print(f"  - {sname}: {count}/12 verified questions")
        else:
            print(f"[REPORT] All {num_sets} sets completed with 12/12 fully verified questions!")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Build prebuilt diagnostic sets through Phase 4B pipeline.")
    parser.add_argument("--sets", type=int, default=3, help="Number of diagnostic sets to build (default: 3)")
    args = parser.parse_args()

    build_sets(num_sets=args.sets)


if __name__ == "__main__":
    main()

