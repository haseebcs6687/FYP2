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

ALPHA_VECTOR = 0.70
BETA_LEXICAL = 0.30

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
        self.last_candidates_count = 0

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
               collections=None, types=None, difficulty=None, target_level=None,
               exclude_ids=None, near_duplicate_threshold=None, min_score=0.0):
        """
        Two-stage search:
          Stage 1: Metadata filtering (collection, concept_tags, types, difficulty, exclude_ids).
          Stage 2: Hybrid scoring (0.7 * cosine + 0.3 * lexical), soft level boost, near-duplicate rejection.
        """
        if not self.chunks:
            self.last_candidates_count = 0
            return []

        concept_tags = set(concept_tags or [])
        collections_set = set(collections) if collections else None
        types_set = set(types) if types else None
        exclude_set = set(exclude_ids or [])
        query_tokens = tokenize(query_text)

        if query_vector is None:
            sims = [0.0] * len(self.chunks)
        elif HAS_NUMPY and self.vectors is not None and len(self.vectors):
            qv = np.asarray(query_vector, dtype="float32")
            norm = float(np.linalg.norm(qv)) or 1.0
            sims = np.asarray(self.vectors) @ (qv / norm)
        else:
            sims = [_cosine(query_vector, v) for v in (self.vectors or [])]

        candidates = []
        for idx, chunk in enumerate(self.chunks):
            # Stage 1: Collection filter
            if collections_set and chunk.get("collection") not in collections_set:
                continue

            # Stage 1: Type filter
            if types_set and chunk.get("type") not in types_set:
                continue

            # Stage 1: Exclude IDs
            cid = chunk.get("id")
            qid = chunk.get("question_id")
            if exclude_set and (cid in exclude_set or qid in exclude_set):
                continue

            # Stage 1: Concept filter (when concept_tags provided)
            chunk_tags = set(chunk.get("concept_tags", []))
            chunk_concept = chunk.get("concept")
            if concept_tags:
                if chunk_concept:
                    if chunk_concept not in concept_tags and not (chunk_tags & concept_tags):
                        continue
                elif not (chunk_tags & concept_tags):
                    continue

            # Stage 1: Difficulty filter (strict for question collection)
            if difficulty and chunk.get("difficulty") and chunk.get("difficulty") != difficulty:
                continue

            candidates.append(idx)

        self.last_candidates_count = len(candidates)

        scored_results = []
        for idx in candidates:
            chunk = self.chunks[idx]
            vector_score = float(sims[idx]) if idx < len(sims) else 0.0
            cosine_score = max(0.0, min(1.0, (vector_score + 1.0) / 2.0 if vector_score < 0 else vector_score))
            lexical_score = self._lexical_score(query_tokens, idx)

            # Stage 2 hybrid score: 0.7 * cosine + 0.3 * lexical (or purely lexical if query_vector is None)
            if query_vector is None:
                score = lexical_score
            else:
                score = (ALPHA_VECTOR * cosine_score + BETA_LEXICAL * lexical_score)

            # Soft level boost +0.08 for lesson retrieval
            if target_level and chunk.get("level") == target_level:
                score += 0.08

            if score < min_score:
                continue

            scored_results.append({
                "_idx": idx,
                "chunk_id": chunk["id"],
                "id": chunk["id"],
                "text": chunk["text"],
                "source": chunk["source"],
                "page": chunk.get("page", 1),
                "concept": chunk.get("concept") or (chunk.get("concept_tags", [""])[0] if chunk.get("concept_tags") else ""),
                "concept_tags": chunk.get("concept_tags", []),
                "collection": chunk.get("collection", "root"),
                "type": chunk.get("type", "lesson"),
                "level": chunk.get("level", "standard"),
                "difficulty": chunk.get("difficulty"),
                "score": round(score, 4),
                "final": round(score, 4),
                "cosine": round(cosine_score, 4),
                "vector_score": round(cosine_score, 4),
                "lexical": round(lexical_score, 4),
                "lexical_score": round(lexical_score, 4),
                "title": chunk.get("title", ""),
                "section": chunk.get("section", ""),
                "heading": chunk.get("heading", ""),
                "raw_record": chunk.get("raw_record"),
                "question_id": chunk.get("question_id"),
                "qtype": chunk.get("qtype"),
                "correct_index": chunk.get("correct_index"),
                "misconception_ids": chunk.get("misconception_ids", []),
            })

        scored_results.sort(key=lambda r: r["score"], reverse=True)

        # Stage 2: near-duplicate rejection if requested
        if near_duplicate_threshold and self.vectors is not None:
            selected = []
            selected_vecs = []
            for r in scored_results:
                v = self.vectors[r["_idx"]]
                if HAS_NUMPY:
                    v_norm = float(np.linalg.norm(v)) or 1.0
                    v_unit = np.asarray(v, dtype="float32") / v_norm
                    if selected_vecs:
                        cosines = [float(np.dot(v_unit, sv)) for sv in selected_vecs]
                        if any(c >= near_duplicate_threshold for c in cosines):
                            continue
                    selected.append(r)
                    selected_vecs.append(v_unit)
                else:
                    if selected_vecs:
                        cosines = [_cosine(v, sv) for sv in selected_vecs]
                        if any(c >= near_duplicate_threshold for c in cosines):
                            continue
                    selected.append(r)
                    selected_vecs.append(v)

                if len(selected) >= top_k:
                    break
            final_list = selected
        else:
            final_list = scored_results[:top_k]

        for r in final_list:
            r.pop("_idx", None)

        return final_list

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
