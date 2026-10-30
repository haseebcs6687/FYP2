"""
=============================================================================
EduGen RAG - Chunk Level Classification Heuristic
=============================================================================
Deterministic heuristic for classifying lesson/book/note chunks into one of
three pedagogical levels:

  'basic'    : Introductory definitions, overview prose, short explanations,
               little to no code. Contains phrases like "is a", "means",
               "introduction", "defined as", "overview", "basics".
  'advanced' : Mentions of pitfalls, edge cases, subtle behaviors, exceptions,
               caveats, performance, or chunks containing substantial code.
               Contains phrases like "however", "note that", "pitfall",
               "edge case", "caveat", "careful", "subtle", "exception".
  'standard' : Balanced explanatory text and code walkthroughs that are
               neither introductory definitions nor edge-case warnings.
=============================================================================
"""

import re

BASIC_KEYWORDS = (
    "is a",
    "is an",
    "means",
    "meaning",
    "introduction",
    "defined as",
    "refers to",
    "overview",
    "basics",
    "what is",
    "fundamental",
    "concept of",
)

ADVANCED_KEYWORDS = (
    "pitfall",
    "edge case",
    "edge cases",
    "however",
    "note that",
    "notice that",
    "caveat",
    "subtle",
    "careful",
    "beware",
    "gotcha",
    "exception",
    "exceptions",
    "memory leak",
    "performance",
    "trade-off",
    "tradeoff",
    "internally",
    "under the hood",
    "dangerous",
    "anti-pattern",
    "overhead",
)

CODE_FENCE_RE = re.compile(r"```(?:java)?(.*?)```", re.DOTALL | re.IGNORECASE)


def infer_level(text: str, heading: str = "", code: str = "") -> str:
    """
    Classify a chunk text and optional heading/code into 'basic', 'standard', or 'advanced'.
    Deterministic, case-insensitive heuristic.
    """
    combined = " ".join([heading or "", text or "", code or ""]).lower()
    total_len = len(text or "")

    # Count code lines / blocks
    code_matches = CODE_FENCE_RE.findall(text or "")
    total_code_chars = sum(len(c) for c in code_matches) + len(code or "")

    # Advanced signals
    has_advanced_kw = any(kw in combined for kw in ADVANCED_KEYWORDS)
    has_long_code = total_code_chars > 350 or (text or "").count(";\n") >= 6

    # Basic signals: intro/definition style words and little code
    has_basic_kw = any(kw in combined for kw in BASIC_KEYWORDS)
    has_little_code = total_code_chars < 80

    # Decision logic
    if has_advanced_kw or has_long_code:
        return "advanced"

    if has_basic_kw and has_little_code:
        return "basic"

    return "standard"
