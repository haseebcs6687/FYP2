"""
=============================================================================
EduGen RAG - Embedding Backends
=============================================================================
Three interchangeable backends behind one interface, chosen with the
EDUGEN_EMBEDDING_BACKEND environment variable:

  sentence-transformers  local model, runs fine on Apple Silicon  (recommended)
  ollama                 local Ollama server, e.g. nomic-embed-text
  hashing                dependency-free fallback, no model download needed

`auto` (the default) tries them in that order. The hashing backend exists so
the whole system boots and can be demonstrated on a machine with no ML stack
installed - quality is lower, but nothing crashes.

IMPORTANT: the index stores which backend + model produced it. If you switch
backends you must re-run `python -m rag.ingest --rebuild`, because vectors
from different models are not comparable.
=============================================================================
"""

import hashlib
import math
import os
import re

DEFAULT_ST_MODEL = os.environ.get("EDUGEN_ST_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
DEFAULT_OLLAMA_MODEL = os.environ.get("EDUGEN_OLLAMA_MODEL", "nomic-embed-text")
DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower())


class BaseEmbedder(object):
    name = "base"
    model_name = ""
    dim = 0

    def embed(self, texts):
        """texts: list[str] -> list[list[float]] (L2-normalised)."""
        raise NotImplementedError

    def embed_one(self, text):
        return self.embed([text])[0]

    def signature(self):
        return "{}:{}:{}".format(self.name, self.model_name, self.dim)


# ─────────────────────────────────────────────────────────────
# 1. sentence-transformers (recommended on a MacBook)
# ─────────────────────────────────────────────────────────────
class SentenceTransformerEmbedder(BaseEmbedder):
    name = "sentence-transformers"

    def __init__(self, model_name=None):
        from sentence_transformers import SentenceTransformer  # noqa: F401
        import torch

        self.model_name = model_name or DEFAULT_ST_MODEL
        device = "cpu"
        try:
            if torch.backends.mps.is_available():
                device = "mps"          # Apple Silicon GPU
            elif torch.cuda.is_available():
                device = "cuda"
        except Exception:
            pass
        self.device = device
        self._model = SentenceTransformer(self.model_name, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts):
        vectors = self._model.encode(
            list(texts),
            batch_size=32,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]


# ─────────────────────────────────────────────────────────────
# 2. Ollama (matches the reference RAG repo: nomic-embed-text)
# ─────────────────────────────────────────────────────────────
class OllamaEmbedder(BaseEmbedder):
    name = "ollama"

    def __init__(self, model_name=None, host=None):
        import requests  # noqa: F401
        self.model_name = model_name or DEFAULT_OLLAMA_MODEL
        self.host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")
        probe = self.embed(["dimension probe"])[0]
        self.dim = len(probe)

    def embed(self, texts):
        import requests
        texts = list(texts)
        if not texts:
            return []
        out = []
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            chunk_batch = texts[i:i + batch_size]
            try:
                resp = requests.post(
                    self.host + "/api/embed",
                    json={"model": self.model_name, "input": chunk_batch},
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings") or []
                    if len(embeddings) == len(chunk_batch):
                        for vec in embeddings:
                            out.append(_l2(vec))
                        continue
            except Exception:
                pass

            # Fallback to single-item /api/embeddings
            for text in chunk_batch:
                resp = requests.post(
                    self.host + "/api/embeddings",
                    json={"model": self.model_name, "prompt": text},
                    timeout=120,
                )
                resp.raise_for_status()
                vec = resp.json().get("embedding") or []
                out.append(_l2(vec))
        return out


# ─────────────────────────────────────────────────────────────
# 3. Hashing fallback - zero dependencies, deterministic
# ─────────────────────────────────────────────────────────────
class HashingEmbedder(BaseEmbedder):
    """
    Feature-hashed bag of unigrams + bigrams with sub-linear term weighting.
    Not a neural embedding: it captures lexical overlap only. Good enough to
    prove the pipeline end to end, and it never needs a download.
    """
    name = "hashing"

    def __init__(self, dim=768):
        self.model_name = "feature-hash-{}".format(dim)
        self.dim = dim

    def _features(self, text):
        toks = _tokens(text)
        feats = {}
        for t in toks:
            feats[t] = feats.get(t, 0) + 1
        for a, b in zip(toks, toks[1:]):
            bg = a + "_" + b
            feats[bg] = feats.get(bg, 0) + 1
        return feats

    def embed(self, texts):
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for term, count in self._features(text).items():
                h = int(hashlib.md5(term.encode("utf-8")).hexdigest()[:8], 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 16) % 2 == 0 else -1.0
                vec[idx] += sign * (1.0 + math.log(count))
            out.append(_l2(vec))
        return out


def _l2(vec):
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return [0.0] * len(vec)
    return [v / norm for v in vec]


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────
def get_embedder(backend=None, quiet=False):
    env_backend = os.environ.get("EDUGEN_EMBEDDING_BACKEND")
    if backend is None:
        # If ollama with nomic-embed-text works, use it as active backend
        try:
            emb = OllamaEmbedder()
            if not quiet:
                print("[RAG] Embedder: {} ({}d, model='{}')".format(emb.name, emb.dim, emb.model_name))
            return emb
        except Exception:
            backend = (env_backend or "auto").lower()
    else:
        backend = backend.lower()

    attempts = {
        "auto": ["sentence-transformers", "ollama", "hashing"],
        "sentence-transformers": ["sentence-transformers"],
        "st": ["sentence-transformers"],
        "ollama": ["ollama"],
        "hashing": ["hashing"],
    }.get(backend, ["hashing"])

    errors = []
    for choice in attempts:
        try:
            if choice == "sentence-transformers":
                emb = SentenceTransformerEmbedder()
            elif choice == "ollama":
                emb = OllamaEmbedder()
            else:
                emb = HashingEmbedder()
            if not quiet:
                print("[RAG] Embedder: {} ({}d, model='{}')".format(emb.name, emb.dim, emb.model_name))
            return emb
        except Exception as exc:  # noqa: BLE001 - deliberate: fall through
            errors.append("{}: {}".format(choice, exc))

    raise RuntimeError("No embedding backend available -> " + " | ".join(errors))

