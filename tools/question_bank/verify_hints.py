"""
=============================================================================
EduGen - Question Bank Hint Verification Tool (Phase 2D-fix-7)
=============================================================================
Automatically verifies curated human page hints in tools/question_bank/page_hints.json
against raw extracted pages in data/bank_work/<pdf>/pages.jsonl.

Rules:
  - Checks each (pdf, page, expected_text) assertion.
  - Normalizes text: lower-case, collapse whitespace/newlines to single spaces,
    map ligatures (ﬁ->fi, ﬂ->fl, ﬀ->ff).
  - If a check fails, any hint range containing that check's page is DROPPED.
  - Any range with start > end or outside PDF page count is DROPPED.
  - Writes data/bank_work/hint_check.txt with pass/fail and dropped ranges.
  - Never modifies page_hints.json automatically.

Usage:
    python tools/question_bank/verify_hints.py
=============================================================================
"""

import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HINTS_FILE = BASE_DIR / "tools" / "question_bank" / "page_hints.json"
BANK_WORK_DIR = BASE_DIR / "data" / "bank_work"
REPORT_FILE = BANK_WORK_DIR / "hint_check.txt"

PDF_CODE_TO_NAME = {
    "JN": "JavaNotesForProfessionals",
    "JE": "javanotes9",
    "TJ": "thinkjava2",
}

PDF_NAME_TO_CODE = {v: k for k, v in PDF_CODE_TO_NAME.items()}

RAW_CHECKS = """
JN|37|instantiating a reference type
JN|249|default constructor
JN|250|call parent constructor
JN|251|constructor with arguments
JN|261|clone() method
JN|279|immutable class
JN|281|defensive copying
JN|304|overloading methods
JN|305|method overloading and overriding
JN|309|basic object construction
JN|322|default methods
JN|324|multiple inheritance collision
JN|329|inheritance
JN|330|abstract classes
JN|334|is-a
JN|338|programming to an interface
JN|340|overriding in inheritance
JN|399|super keyword
JN|418|catching an exception with try-catch
JN|419|try-with-resources
JN|422|custom exceptions
JN|427|exception hierarchy
JN|433|throwing an exception
JN|436|try-finally
JN|467|finally
JN|493|implementing multiple interfaces
JN|497|default methods
JN|502|implementing interfaces in an abstract class
JN|521|deep copy
JN|641|method overriding
JN|643|types of overriding
JN|646|virtual functions
JN|649|encapsulation to maintain invariants
JN|34|getter
JN|763|overloading instead of overriding
JN|773|unexpected nulls
JN|856|dynamic method dispatch
JN|881|inheritance vs composition
JN|852|try-with-resources
JN|587|functional interfaces
JN|457|functional interface
JN|288|class member access
JE|223|objects, instance methods, and instance variables
JE|231|getters and setters
JE|233|constructors and object initialization
JE|235|constructors
JE|240|garbage collection
JE|257|inheritance, polymorphism, and abstract classes
JE|258|extending existing classes
JE|259|protected
JE|260|inheritance and class hierarchy
JE|263|polymorphism
JE|266|abstract classes
JE|269|this and super
JE|271|the special variable super
JE|272|super and this as constructors
JE|273|interfaces
JE|276|default methods
JE|163|black boxes and procedural abstraction
JE|136|try..catch
JE|177|overloading
JE|182|throwing exceptions
JE|182|global and local variables
JE|189|first-class functions
JE|190|functional interfaces
JE|433|exceptions and try..catch
JE|438|finally
JE|439|throwing exceptions
JE|725|mvc pattern
JE|565|generic functional interfaces
TJ|205|designing classes
TJ|206|the time class
TJ|207|constructors
TJ|208|value constructors
TJ|210|getters and setters
TJ|171|strings are immutable
TJ|198|garbage collection
TJ|199|mutable vs immutable
TJ|229|cards are immutable
TJ|258|inheritance
TJ|293|abstract classes
TJ|310|interfaces
TJ|213|tostring
TJ|280|interruptedexception
""".strip().splitlines()

_PAGE_TEXT_CACHE = {}


def normalize_text(text: str) -> str:
    """Normalizes text: lowercase, single spaces, ligature conversion."""
    if not text:
        return ""
    t = text.lower()
    t = t.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def get_pdf_page_text(pdfshort: str, page_num: int, work_dir: Path = None) -> str:
    """Returns normalized text of a specific page from pages.jsonl."""
    global _PAGE_TEXT_CACHE
    if work_dir is None:
        work_dir = BANK_WORK_DIR
    else:
        work_dir = Path(work_dir)

    key = (pdfshort, str(work_dir))
    if key not in _PAGE_TEXT_CACHE:
        pages_file = work_dir / pdfshort / "pages.jsonl"
        page_map = {}
        if pages_file.exists():
            with open(pages_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line)
                        page_map[item["page"]] = normalize_text(item.get("text", ""))
        _PAGE_TEXT_CACHE[key] = page_map

    return _PAGE_TEXT_CACHE[key].get(page_num, "")


def get_pdf_max_page(pdfshort: str, work_dir: Path = None) -> int:
    """Returns the maximum page number in the pages.jsonl file."""
    global _PAGE_TEXT_CACHE
    if work_dir is None:
        work_dir = BANK_WORK_DIR
    key = (pdfshort, str(work_dir))
    if key not in _PAGE_TEXT_CACHE:
        get_pdf_page_text(pdfshort, 1, work_dir)
    return max(_PAGE_TEXT_CACHE.get(key, {}).keys()) if _PAGE_TEXT_CACHE.get(key) else 0


def verify_hints_data(
    hints_path: Path = None,
    work_dir: Path = None,
    checks_list: list[str] = None,
) -> tuple[dict, list[dict], list[dict]]:
    """
    Verifies all hint ranges against the checks.
    Returns:
      - verified_hints: dict matching page_hints.json structure with dropped ranges omitted.
      - check_results: list of {pdf, page, expected, status: PASS/FAIL}
      - dropped_ranges: list of {pdf, concept, range, reason}
    """
    p_file = hints_path or HINTS_FILE
    w_dir = work_dir or BANK_WORK_DIR
    checks = checks_list or RAW_CHECKS

    if not p_file.exists():
        return {}, [], []

    with open(p_file, "r", encoding="utf-8") as f:
        hints = json.load(f)

    # 1. Run all checks
    check_results = []
    failed_checks = []  # list of (pdf_name, page_num, expected)

    for c_line in checks:
        c_line = c_line.strip()
        if not c_line:
            continue
        parts = c_line.split("|")
        code, page_str, expected = parts[0], parts[1], parts[2]
        pdf_name = PDF_CODE_TO_NAME.get(code, code)
        page_num = int(page_str)
        norm_expected = normalize_text(expected)
        page_text = get_pdf_page_text(pdf_name, page_num, w_dir)

        passed = norm_expected in page_text
        status = "PASS" if passed else "FAIL"
        entry = {
            "code": code,
            "pdf": pdf_name,
            "page": page_num,
            "expected": expected,
            "status": status,
        }
        check_results.append(entry)
        if not passed:
            failed_checks.append((pdf_name, page_num, expected))

    # 2. Check each hint range in page_hints.json
    verified_hints = {}
    dropped_ranges = []

    for pdf_name, concepts in hints.items():
        verified_hints[pdf_name] = {}
        max_page = get_pdf_max_page(pdf_name, w_dir)
        for concept, ranges in concepts.items():
            valid_for_concept = []
            for r in ranges:
                start, end = r[0], r[1]
                # Bound checks
                if start > end:
                    dropped_ranges.append({
                        "pdf": pdf_name,
                        "concept": concept,
                        "range": r,
                        "reason": f"start ({start}) > end ({end})",
                    })
                    continue
                if start < 1 or (max_page > 0 and end > max_page):
                    dropped_ranges.append({
                        "pdf": pdf_name,
                        "concept": concept,
                        "range": r,
                        "reason": f"range [{start}, {end}] exceeds PDF bounds [1, {max_page}]",
                    })
                    continue

                # Check if any failing check falls inside this range
                failed_inside = [
                    fc for fc in failed_checks
                    if fc[0] == pdf_name and (start <= fc[1] <= end)
                ]
                if failed_inside:
                    reasons = [f"page {fc[1]} failed '{fc[2]}'" for fc in failed_inside]
                    dropped_ranges.append({
                        "pdf": pdf_name,
                        "concept": concept,
                        "range": r,
                        "reason": f"Failing check inside range: {'; '.join(reasons)}",
                    })
                    continue

                valid_for_concept.append(r)

            verified_hints[pdf_name][concept] = valid_for_concept

    return verified_hints, check_results, dropped_ranges


def write_verification_report(
    check_results: list[dict],
    dropped_ranges: list[dict],
    out_file: Path = None,
):
    """Writes data/bank_work/hint_check.txt report."""
    if out_file is None:
        out_file = REPORT_FILE
    out_file.parent.mkdir(parents=True, exist_ok=True)

    passed_count = sum(1 for c in check_results if c["status"] == "PASS")
    failed_count = sum(1 for c in check_results if c["status"] == "FAIL")

    lines = []
    lines.append("=" * 70)
    lines.append("EduGen - Curated Hint Verification Report (Phase 2D-fix-7)")
    lines.append("=" * 70)
    lines.append(f"Total Checks : {len(check_results)}")
    lines.append(f"PASS         : {passed_count}")
    lines.append(f"FAIL         : {failed_count}")
    lines.append(f"Dropped Ranges: {len(dropped_ranges)}")
    lines.append("=" * 70)
    lines.append("")

    lines.append("--- Check Results ---")
    for c in check_results:
        lines.append(f"[{c['status']}] {c['code']}|{c['page']}|{c['expected']} ({c['pdf']})")
    lines.append("")

    lines.append("--- Dropped Ranges ---")
    if not dropped_ranges:
        lines.append("None. All hint ranges passed validation.")
    else:
        for d in dropped_ranges:
            lines.append(f"- {d['pdf']} | {d['concept']} | {d['range']}: {d['reason']}")

    lines.append("")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    print("Running automatic hint verification...")
    verified, check_results, dropped_ranges = verify_hints_data()
    write_verification_report(check_results, dropped_ranges)
    passed_cnt = sum(1 for c in check_results if c["status"] == "PASS")
    failed_cnt = sum(1 for c in check_results if c["status"] == "FAIL")

    print(f"Hint verification complete:")
    print(f"  Checks: {len(check_results)} total | {passed_cnt} PASS | {failed_cnt} FAIL")
    print(f"  Dropped ranges: {len(dropped_ranges)}")
    if dropped_ranges:
        for d in dropped_ranges:
            print(f"    - {d['pdf']} | {d['concept']} | {d['range']}: {d['reason']}")
    print(f"Report written to {REPORT_FILE}")


if __name__ == "__main__":
    main()
