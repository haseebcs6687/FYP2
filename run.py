"""
EduGen entry point.

    python run.py      ->  http://localhost:5000

Before the first run:
    pip install -r requirements.txt
    cp .env.example .env         # then add your GROQ_API_KEY
    python scripts/build_corpus.py
    python -m rag.ingest
"""
import os

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=port,
        debug=os.environ.get("EDUGEN_DEBUG", "1") == "1",
    )
