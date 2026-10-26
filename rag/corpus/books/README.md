# Books folder

Drop any `.pdf`, `.txt` or `.md` file in here and run:

    python -m rag.ingest --rebuild

The ingestion pipeline picks it up automatically, chunks it on headings,
tags every chunk against the 44 canonical concepts, and adds it to the index.
No code changes are needed.

To download three open-licence Java textbooks automatically:

    python scripts/fetch_books.py --list
    python scripts/fetch_books.py

Attribution for whatever you add is written to `SOURCES.md`.
