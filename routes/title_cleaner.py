"""
=============================================================================
EduGen - Passage Title & Sources Cleaner (routes/title_cleaner.py)
=============================================================================
Formats passage and textbook titles cleanly for student display:
- Strips file paths and .pdf extensions
- Cleans and humanizes book titles
- Detects garbled or corrupted section titles (letter ratio < 60% or noisy fragments like '$%')
- Formats clean 'Sources: <book title>, <chapter/section>' lines
=============================================================================
"""

import os
import re
from typing import Any, List, Optional


def is_title_garbled(title: Optional[str]) -> bool:
    """
    Returns True if a passage or section title is garbled:
    - letters constitute < 60% of non-space characters
    - contains corrupted fragments like '$%' or stray '&' fragments (e.g. '$% &outines nested in')
    """
    if not title:
        return True
    s = str(title).strip()
    non_space = [c for c in s if not c.isspace()]
    if not non_space:
        return True
    letters = [c for c in non_space if c.isalpha()]
    if (len(letters) / len(non_space)) < 0.60:
        return True
    if "$%" in s:
        return True
    if re.search(r"&[a-zA-Z]", s):
        return True
    return False


def clean_book_title(book: Optional[str]) -> str:
    """Strip .pdf extensions, directory paths, and format cleanly."""
    if not book:
        return "Java Reference"
    b = os.path.basename(str(book))
    if b.lower().endswith(".pdf"):
        b = b[:-4]
    b = b.replace("_", " ").replace("-", " ").strip()
    return b or "Java Reference"


def clean_passage_title(book_title: str, section_title: Optional[str] = None) -> str:
    """
    Format a clean passage citation title.
    If section_title is garbled (letters < 60% of non-space, or contains '$%' / '&' fragments),
    shows only the book title. Otherwise shows '<book title>, <chapter/section>'.
    """
    book = clean_book_title(book_title)
    if not section_title:
        return book
    s = str(section_title).strip()
    if is_title_garbled(s):
        return book
    if s.lower().endswith(".pdf"):
        s = s[:-4].strip()
    return f"{book}, {s}"


def format_clean_sources_line(sources: List[Any]) -> str:
    """
    Format sources list into a clean student-facing string:
    'Sources: <book title>, <chapter/section>'
    """
    if not sources:
        return ""
    cleaned = []
    seen = set()
    for item in sources:
        if isinstance(item, dict):
            book = item.get("source") or item.get("file") or item.get("book") or ""
            sec = item.get("section") or item.get("title") or ""
        else:
            book = str(item)
            sec = ""
        line = clean_passage_title(book, sec)
        if line and line not in seen:
            seen.add(line)
            cleaned.append(line)
    if not cleaned:
        return ""
    return "Sources: " + "; ".join(cleaned)
