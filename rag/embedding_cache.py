"""
=============================================================================
EduGen RAG - Embedding Cache
=============================================================================
Caches computed embedding vectors by (embedder signature, sha1(chunk text))
in SQLite under data/rag_cache/embedding_cache.db (git-ignored).
Prevents re-embedding unchanged corpus chunks during index rebuilds.
=============================================================================
"""

import hashlib
import json
import sqlite3
from pathlib import Path

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "rag_cache"


class EmbeddingCache:
    def __init__(self, db_path=None):
        if db_path is None:
            DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self.db_path = DEFAULT_CACHE_DIR / "embedding_cache.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS embeddings (
                    sig TEXT,
                    sha1 TEXT,
                    vector_json TEXT,
                    PRIMARY KEY (sig, sha1)
                )"""
            )
            conn.commit()

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha1((text or "").encode("utf-8")).hexdigest()

    def get_many(self, sig: str, sha1_list: list) -> dict:
        """Return dict of {sha1: vector} for all hits found in cache."""
        if not sha1_list:
            return {}
        found = {}
        # Query in chunks of 500 to stay well under SQLite parameter limits
        with sqlite3.connect(str(self.db_path)) as conn:
            for i in range(0, len(sha1_list), 500):
                batch = sha1_list[i:i + 500]
                placeholders = ",".join("?" for _ in batch)
                cur = conn.execute(
                    f"SELECT sha1, vector_json FROM embeddings WHERE sig = ? AND sha1 IN ({placeholders})",
                    [sig] + batch,
                )
                for h, v_json in cur.fetchall():
                    found[h] = json.loads(v_json)
        return found

    def put_many(self, sig: str, items: list):
        """Store list of (sha1, vector) in cache."""
        if not items:
            return
        records = [(sig, h, json.dumps(v)) for h, v in items]
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO embeddings (sig, sha1, vector_json) VALUES (?, ?, ?)",
                records,
            )
            conn.commit()

    def seed_from_store(self, store, sig: str):
        """Seed cache from an existing loaded VectorStore if not already present."""
        if not store or not store.chunks or store.vectors is None or len(store.chunks) != len(store.vectors):
            return 0
        items_to_put = []
        for chunk, vec in zip(store.chunks, store.vectors):
            h = self.hash_text(chunk.get("text", ""))
            v_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
            items_to_put.append((h, v_list))
        self.put_many(sig, items_to_put)
        return len(items_to_put)
