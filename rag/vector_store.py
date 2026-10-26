"""
=============================================================================
EduGen RAG - Vector Store
=============================================================================
A small, file-backed vector store. No external database, no server, no
Docker - three files on disk that you can inspect, version and hand to an
examiner:

  data/rag_index/vectors.npy   float32 matrix, one L2-normalised row per chunk
  data/rag_index/chunks.jsonl  the chunk text + metadata, one JSON per line
  data/rag_index/meta.json     backend, model, dimension, build time, counts

Search is HYBRID, which matters a lot on a small academic corpus:

    final = alpha * cosine(query, chunk)
          + beta  * lexical_overlap(query, chunk)
          + gamma * concept_tag_match

Pure cosine on a 100-page corpus tends to return "related-sounding" text;
the lexical term keeps exact Java vocabulary (super(), @Override, finally)
anchored, and the tag term keeps answers inside the concept the agent asked
about.
=============================================================================
"""

import json
import math
import os
import re
import time
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:      # pragma: no cover
    np = None
    HAS_NUMPY = False

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INDEX_DIR = Path(os.environ.get("EDUGEN_RAG_INDEX") or (BASE_DIR / "data" / "rag_index"))

ALPHA_VECTOR = 0.62
BETA_LEXICAL = 0.26
GAMMA_TAGS = 0.12

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOP = {
    "the", "a", "an", "of", "to", "and", "or", "in", "is", "are", "be", "that",
    "this", "it", "for", "on", "as", "with", "by", "from", "at", "we", "you",
    "can", "will", "which", "when", "what", "how", "its", "if", "not", "but",
}


def tokenize(text):
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


class VectorStore(object):
    def __init__(self, index_dir=None):
        self.index_dir = Path(index_dir or DEFAULT_INDEX_DIR)
        self.chunks = []
        self.vectors = None         # numpy array or list[list[float]]
        self.meta = {}
        self._df = {}               # document frequency for lexical scoring
        self._chunk_tokens = []

    # ── persistence ──────────────────────────────────────────
    @property
    def vectors_path(self):
        return self.index_dir / "vectors.npy"

    @property
    def chunks_path(self):
        return self.index_dir / "chunks.jsonl"

    @property
    def meta_path(self):
        return self.index_dir / "meta.json"

    def exists(self):
        return self.chunks_path.exists() and self.meta_path.exists()

    def save(self, chunks, vectors, embedder_signature, extra=None):
        self.index_dir.mkdir(parents=True, exist_ok=True)

        with open(self.chunks_path, "w", encoding="utf-8") as fh:
            for chunk in chunks:
                fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")

        if HAS_NUMPY:
            np.save(str(self.vectors_path), np.asarray(vectors, dtype="float32"))
        else:
            with open(self.index_dir / "vectors.json", "w", encoding="utf-8") as fh:
                json.dump(vectors, fh)

        meta = {
            "embedder": embedder_signature,
            "dimension": len(vectors[0]) if vectors else 0,
            "chunk_count": len(chunks),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sources": sorted({c["source"] for c in chunks}),
            "collections": sorted({c.get("collection", "root") for c in chunks}),
            "numpy": HAS_NUMPY,
        }
        meta.update(extra or {})
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)

        self.chunks, self.vectors, self.meta = chunks, vectors, meta
        self._build_lexical_index()
        return meta

    def load(self):
        if not self.exists():
            return False

        self.chunks = []
        with open(self.chunks_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    self.chunks.append(json.loads(line))

        with open(self.meta_path, "r", encoding="utf-8") as fh:
            self.meta = json.load(fh)

        if HAS_NUMPY and self.vectors_path.exists():
            self.vectors = np.load(str(self.vectors_path))
        else:
            json_vectors = self.index_dir / "vectors.json"
            if json_vectors.exists():
                with open(json_vectors, "r", encoding="utf-8") as fh:
                    self.vectors = json.load(fh)
            else:
                self.vectors = None

        self._build_lexical_index()
        return True

    # ── lexical half of the hybrid score ─────────────────────
    def _build_lexical_index(self):
        self._chunk_tokens = []
        self._df = {}
        for chunk in self.chunks:
            tokens = tokenize(chunk["text"] + " " + chunk.get("heading", ""))
            counts = {}
            for t in tokens:
                counts[t] = counts.get(t, 0) + 1
            self._chunk_tokens.append(counts)
            for t in counts:
                self._df[t] = self._df.get(t, 0) + 1

    def _lexical_score(self, query_tokens, idx):
        counts = self._chunk_tokens[idx] if idx < len(self._chunk_tokens) else {}
        if not counts or not query_tokens:
            return 0.0
        n = max(len(self.chunks), 1)
        score, length = 0.0, sum(counts.values()) or 1
        for token in query_tokens:
            tf = counts.get(token, 0)
            if not tf:
                continue
            idf = math.log(1 + (n / (1 + self._df.get(token, 0))))
            score += (tf / length) * idf * 12.0
        return min(score / max(len(set(query_tokens)), 1) * 4.0, 1.0)

    # ── search ───────────────────────────────────────────────
    def search(self, query_vector, query_text="", concept_tags=None, top_k=5,
               collections=None, min_score=0.0):
        """Return the top_k chunks ranked by the hybrid score."""
        if not self.chunks:
            return []

        concept_tags = set(concept_tags or [])
        query_tokens = tokenize(query_text)
        results = []

        if HAS_NUMPY and self.vectors is not None and len(self.vectors):
            qv = np.asarray(query_vector, dtype="float32")
            norm = float(np.linalg.norm(qv)) or 1.0
            sims = np.asarray(self.vectors) @ (qv / norm)
        else:
            sims = [_cosine(query_vector, v) for v in (self.vectors or [])]

        for idx, chunk in enumerate(self.chunks):
            if collections and chunk.get("collection") not in collections:
                continue

            vector_score = float(sims[idx]) if idx < len(sims) else 0.0
            vector_score = max(0.0, min(1.0, (vector_score + 1.0) / 2.0 if vector_score < 0 else vector_score))
            lexical_score = self._lexical_score(query_tokens, idx)

            chunk_tags = set(chunk.get("concept_tags", []))
            if concept_tags and chunk_tags:
                tag_score = len(concept_tags & chunk_tags) / float(len(concept_tags))
            else:
                tag_score = 0.0

            final = (ALPHA_VECTOR * vector_score
                     + BETA_LEXICAL * lexical_score
                     + GAMMA_TAGS * tag_score)

            if final < min_score:
                continue

            results.append({
                "chunk_id": chunk["id"],
                "text": chunk["text"],
                "source": chunk["source"],
                "collection": chunk.get("collection", "root"),
                "title": chunk.get("title", ""),
                "section": chunk.get("section", ""),
                "heading": chunk.get("heading", ""),
                "concept_tags": chunk.get("concept_tags", []),
                "score": round(final, 4),
                "vector_score": round(vector_score, 4),
                "lexical_score": round(lexical_score, 4),
                "tag_score": round(tag_score, 4),
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def stats(self):
        by_collection, by_source = {}, {}
        tag_counts = {}
        for chunk in self.chunks:
            col = chunk.get("collection", "root")
            by_collection[col] = by_collection.get(col, 0) + 1
            by_source[chunk["source"]] = by_source.get(chunk["source"], 0) + 1
            for tag in chunk.get("concept_tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return {
            "ready": bool(self.chunks),
            "chunk_count": len(self.chunks),
            "embedder": self.meta.get("embedder", "unknown"),
            "dimension": self.meta.get("dimension", 0),
            "built_at": self.meta.get("built_at", ""),
            "collections": by_collection,
            "sources": by_source,
            "covered_concepts": len(tag_counts),
            "tag_counts": tag_counts,
        }


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
