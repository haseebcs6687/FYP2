"""
=============================================================================
EduGen RAG - Retriever
=============================================================================
The bridge between the agent pipeline and the vector store.

The Adaptive Content Agent does not send a bare string to the LLM. It sends a
RETRIEVAL BRIEF:

    {
      "concept":     "constructor-chaining",
      "difficulty":  "Medium",
      "mode":        "lesson" | "quiz",
      "query":       "constructor chaining this() super() delegate ...",
      "concept_tags":["constructor-chaining", "super-keyword"],
      "top_k":       6
    }

The retriever expands that brief with the concept's own vocabulary from
core/concepts.py, runs the hybrid search, de-duplicates near-identical
passages, and returns grounded context plus citations. If the index is empty
it returns `ready=False` and the Concept Clarifier falls back to ungrounded
generation - the system degrades, it does not break.
=============================================================================
"""

import threading

from core.concepts import CONCEPTS, prerequisites_of, search_text_for
from rag.embedder import get_embedder
from rag.vector_store import VectorStore

MAX_CONTEXT_CHARS = 6000

_lock = threading.Lock()


class Retriever(object):
    def __init__(self, index_dir=None, backend=None, lazy=True):
        self.store = VectorStore(index_dir)
        self._embedder = None
        self._backend = backend
        self._loaded = False
        self._load_error = None
        if not lazy:
            self.ensure_loaded()

    # ── lifecycle ────────────────────────────────────────────
    def ensure_loaded(self):
        """Load the index and embedder once, on first use."""
        if self._loaded:
            return self.store.chunks != []
        with _lock:
            if self._loaded:
                return self.store.chunks != []
            try:
                ok = self.store.load()
                if ok and self.store.chunks:
                    self._embedder = get_embedder(self._backend, quiet=True)
                    self._verify_signature()
                self._loaded = True
                return ok and bool(self.store.chunks)
            except Exception as exc:                       # noqa: BLE001
                self._load_error = str(exc)
                self._loaded = True
                return False

    def _verify_signature(self):
        """Warn loudly if the index was built with a different embedder."""
        indexed = self.store.meta.get("embedder", "")
        current = self._embedder.signature() if self._embedder else ""
        if indexed and current and indexed != current:
            self._load_error = (
                "Index was built with '{}' but the active embedder is '{}'. "
                "Run: python -m rag.ingest --rebuild".format(indexed, current)
            )
            print("[RAG] WARNING: " + self._load_error)

    def is_ready(self):
        return self.ensure_loaded() and bool(self.store.chunks)

    def status(self):
        self.ensure_loaded()
        stats = self.store.stats()
        stats["error"] = self._load_error
        stats["index_dir"] = str(self.store.index_dir)
        return stats

    # ── query building ───────────────────────────────────────
    @staticmethod
    def build_brief(concept, difficulty, mode="lesson", extra_terms=None, top_k=6):
        """
        Construct the retrieval brief. This is the object the Adaptive Content
        Agent hands to the Concept Clarifier Agent, and it is logged verbatim
        in the agent activity console so the hand-off is visible.
        """
        meta = CONCEPTS.get(concept)
        tags = [concept] if concept in CONCEPTS else []
        tags += [p for p in prerequisites_of(concept)][:2]

        parts = [search_text_for(concept)] if meta else [(concept or "").replace("-", " ")]
        if mode == "quiz":
            parts.append("example code output common mistake pitfall")
        if difficulty == "Hard":
            parts.append("edge case subtle behaviour advanced")
        elif difficulty == "Easy":
            parts.append("definition simple example basics")
        if extra_terms:
            parts.append(" ".join(extra_terms))

        return {
            "concept": concept,
            "difficulty": difficulty,
            "mode": mode,
            "query": " ".join(p for p in parts if p).strip(),
            "concept_tags": tags,
            "top_k": top_k,
        }

    # ── retrieval ────────────────────────────────────────────
    def retrieve(self, brief):
        """Run a retrieval brief. Always returns a dict, never raises."""
        result = {
            "ready": False,
            "passages": [],
            "context": "",
            "citations": [],
            "brief": brief,
            "error": None,
        }

        if not self.is_ready():
            result["error"] = self._load_error or "RAG index is empty. Run: python -m rag.ingest"
            return result

        try:
            query_vector = self._embedder.embed_one(brief.get("query", ""))
            passages = self.store.search(
                query_vector,
                query_text=brief.get("query", ""),
                concept_tags=brief.get("concept_tags"),
                top_k=int(brief.get("top_k", 6)) * 2,
            )
        except Exception as exc:                            # noqa: BLE001
            result["error"] = "Retrieval failed: {}".format(exc)
            return result

        passages = _dedupe(passages)[: int(brief.get("top_k", 6))]

        result["ready"] = True
        result["passages"] = passages
        result["context"] = _format_context(passages)
        result["citations"] = [
            {
                "n": i + 1,
                "source": p["source"],
                "section": p.get("section") or p.get("title"),
                "score": p["score"],
            }
            for i, p in enumerate(passages)
        ]
        return result

    def search_raw(self, query, top_k=8, concept_tags=None):
        """Plain search used by the Library page so students can explore the corpus."""
        if not self.is_ready():
            return {"ready": False, "results": [], "error": self._load_error}
        vector = self._embedder.embed_one(query)
        results = _dedupe(self.store.search(
            vector, query_text=query, concept_tags=concept_tags, top_k=top_k * 2
        ))[:top_k]
        return {"ready": True, "results": results, "error": None}


def _dedupe(passages, threshold=0.82):
    """Drop passages whose token sets overlap heavily with a higher-ranked one."""
    kept = []
    seen_sets = []
    for p in passages:
        tokens = set(p["text"].lower().split())
        duplicate = False
        for prior in seen_sets:
            if not tokens or not prior:
                continue
            overlap = len(tokens & prior) / float(min(len(tokens), len(prior)))
            if overlap >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(p)
            seen_sets.append(tokens)
    return kept


def _format_context(passages):
    """Numbered, citable context block injected into the LLM prompt."""
    blocks, total = [], 0
    for i, p in enumerate(passages, start=1):
        header = "[{}] {}".format(i, p.get("heading") or p["source"])
        body = p["text"].strip()
        block = "{}\n{}".format(header, body)
        if total + len(block) > MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n---\n\n".join(blocks)


# Process-wide singleton so the model is loaded once per Flask process
_retriever = None


def get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
