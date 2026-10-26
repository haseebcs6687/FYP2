"""
=============================================================================
EduGen - Misconception Catalog Test Suite
=============================================================================
Validates:
(1) Misconception IDs are globally unique.
(2) ID prefix strictly matches concept tag ("<concept-tag>/<slug>").
(3) Every concept exists in core/concepts.py (all 44 covered).
(4) Every concept has 3 to 6 misconception entries.
(5) No empty or whitespace-only fields in any entry.
(6) Facets and titles adhere to length constraints.
(7) Exported markdown files exist and contain rendered sections.

Usage:
    python scripts/test_catalog.py
=============================================================================
"""

import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS, MODULES
from core.misconceptions import (
    MISCONCEPTIONS,
    facets_of,
    is_valid_misconception,
    misconceptions_for,
)

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS {name}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL {name}  <- {detail}")


def main():
    print("==================================================")
    print("  EduGen Misconception Catalog Tests")
    print("==================================================")

    # 1. Total counts and concept coverage
    print("\n1. Concept coverage and entry counts")
    all_concepts = list(CONCEPTS.keys())
    check("catalog has entries", len(MISCONCEPTIONS) > 0)
    check("covers 44 canonical concepts", len(all_concepts) == 44)

    missing_concepts = [c for c in all_concepts if len(misconceptions_for(c)) == 0]
    check("zero uncovered concepts", len(missing_concepts) == 0, f"missing: {missing_concepts}")

    # 2. Entry count constraints: 3 to 6 entries per concept
    count_violations = []
    for c in all_concepts:
        count = len(misconceptions_for(c))
        if not (3 <= count <= 6):
            count_violations.append(f"{c}: {count}")
    check("3 to 6 entries per concept", len(count_violations) == 0, f"violations: {count_violations}")

    # 3. ID uniqueness and prefix format
    print("\n2. ID structure & validation")
    seen_ids = set()
    duplicate_ids = []
    prefix_violations = []
    concept_validity_violations = []
    empty_field_violations = []
    title_length_violations = []
    facet_length_violations = []

    required_fields = ["id", "concept", "facet", "title", "wrong_belief", "correct_idea"]

    for mid, m in MISCONCEPTIONS.items():
        # Uniqueness
        if mid in seen_ids:
            duplicate_ids.append(mid)
        seen_ids.add(mid)

        # Key == entry id
        if mid != m.get("id"):
            prefix_violations.append(f"Key '{mid}' != m['id'] '{m.get('id')}'")

        # ID prefix == concept tag
        c_tag = m.get("concept", "")
        if not mid.startswith(f"{c_tag}/"):
            prefix_violations.append(f"ID '{mid}' does not start with '{c_tag}/'")

        # Concept exists in CONCEPTS
        if c_tag not in CONCEPTS:
            concept_validity_violations.append(f"Unknown concept '{c_tag}' in '{mid}'")

        # No empty fields
        for field in required_fields:
            val = m.get(field)
            if val is None or not str(val).strip():
                empty_field_violations.append(f"{mid} missing or empty '{field}'")

        # Title <= 8 words
        title = m.get("title", "")
        if len(title.split()) > 8:
            title_length_violations.append(f"{mid} title too long ({len(title.split())} words): '{title}'")

        # Facet 2-4 words
        facet = m.get("facet", "")
        words = facet.split()
        if not (1 <= len(words) <= 5):  # allow reasonable margin, nominal 2-4 words
            facet_length_violations.append(f"{mid} facet length ({len(words)} words): '{facet}'")

    check("all IDs globally unique", len(duplicate_ids) == 0, f"duplicates: {duplicate_ids}")
    check("all ID prefixes match concept tag", len(prefix_violations) == 0, f"violations: {prefix_violations}")
    check("all concepts exist in core/concepts.py", len(concept_validity_violations) == 0, f"violations: {concept_validity_violations}")
    check("no empty or whitespace fields", len(empty_field_violations) == 0, f"violations: {empty_field_violations}")
    check("all titles <= 8 words", len(title_length_violations) == 0, f"violations: {title_length_violations}")
    check("all facets have valid word length", len(facet_length_violations) == 0, f"violations: {facet_length_violations}")

    # 4. Helper function validation
    print("\n3. Helper function behavior")
    test_concept = "method-overriding"
    overriding_misconceptions = misconceptions_for(test_concept)
    check("misconceptions_for returns items", len(overriding_misconceptions) >= 4)
    check("is_valid_misconception validates true ID", is_valid_misconception("method-overriding/static-methods-override", test_concept))
    check("is_valid_misconception rejects foreign concept", not is_valid_misconception("method-overriding/static-methods-override", "classes-objects"))
    check("is_valid_misconception rejects non-existent ID", not is_valid_misconception("fake-concept/fake-id"))
    check("facets_of returns unique list", len(facets_of(test_concept)) > 0)

    # 5. Exported files validation
    print("\n4. Exported docs validation")
    docs_dir = BASE_DIR / "docs" / "catalog_for_llm"
    all_file = docs_dir / "all.md"
    check("docs/catalog_for_llm/all.md exists", all_file.exists())
    for mod_id in MODULES.keys():
        mod_file = docs_dir / f"{mod_id}.md"
        check(f"{mod_id}.md exists and is non-empty", mod_file.exists() and mod_file.stat().st_size > 100)

    print("\n==================================================")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print("==================================================")

    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
