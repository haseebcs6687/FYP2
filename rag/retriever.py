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

import collections
import concurrent.futures
import logging
import threading
import time

from core.concepts import CONCEPTS, prerequisites_of, search_text_for
from rag.embedder import get_embedder
from rag.vector_store import VectorStore

MAX_CONTEXT_CHARS = 6000

logger = logging.getLogger("rag.retriever")
_lock = threading.Lock()
_warn_lock = threading.Lock()
_last_warn_time = 0.0


def _log_degraded_warning(msg):
    global _last_warn_time
    with _warn_lock:
        now = time.time()
        if now - _last_warn_time >= 60.0:
            _last_warn_time = now
            logger.warning("[RAG DEGRADED] %s", msg)
            try:
                from core.agent_log import add_log
                add_log("Retriever", msg, "warning")
            except Exception:
                pass


class Retriever(object):
    def __init__(self, index_dir=None, backend=None, lazy=True):
        self.store = VectorStore(index_dir)
        self._embedder = None
        self._backend = backend
        self._loaded = False
        self._load_error = None
        self._query_cache = collections.OrderedDict()
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
        t0 = time.time()
        result = {
            "ready": False,
            "passages": [],
            "context": "",
            "citations": [],
            "brief": brief,
            "error": None,
            "trace": None,
        }

        if not self.is_ready():
            result["error"] = self._load_error or "RAG index is empty. Run: python -m rag.ingest"
            return result

        concept = brief.get("concept")
        difficulty = brief.get("difficulty", "Medium")
        mode = brief.get("mode", "lesson")
        include_prereqs = bool(brief.get("include_prereqs", False))

        # Collection filter: Lesson retrieval must NEVER return 'question' chunks unless asked
        if "collections" in brief and brief["collections"]:
            collections = brief["collections"]
        elif mode == "question" or brief.get("collection") == "question":
            collections = ["question"]
        else:
            collections = ["book", "note"]

        # Concept filtering
        if concept:
            tags = [concept]
            if include_prereqs:
                tags += [p for p in prerequisites_of(concept)]
        else:
            tags = brief.get("concept_tags")

        # Types filter
        types = brief.get("types")

        # Target level soft boost for lesson retrieval
        level_map = {"Easy": "basic", "Medium": "standard", "Hard": "advanced"}
        target_level = level_map.get(difficulty, "standard") if mode == "lesson" else None

        query_text = brief.get("query", "")

        try:
            query_vector, query_cache_hit = self._embed_query(query_text)
            top_k_req = int(brief.get("top_k", 6))
            passages = self.store.search(
                query_vector,
                query_text=query_text,
                concept_tags=tags,
                top_k=top_k_req * 2,
                collections=collections,
                types=types,
                difficulty=brief.get("difficulty") if "question" in collections else None,
                target_level=target_level,
                exclude_ids=brief.get("exclude_ids"),
                near_duplicate_threshold=0.90 if ("question" in collections and query_vector is not None) else None,
            )
            candidates_count = self.store.last_candidates_count
        except Exception as exc:                            # noqa: BLE001
            result["error"] = "Retrieval failed: {}".format(exc)
            return result

        passages = _dedupe(passages)[:top_k_req]
        latency_ms = round((time.time() - t0) * 1000.0, 2)

        top_trace = [
            {
                "chunk_id": p.get("chunk_id") or p.get("id"),
                "source": p.get("source"),
                "page": p.get("page", 1),
                "concept": p.get("concept") or (p.get("concept_tags", [""])[0] if p.get("concept_tags") else ""),
                "collection": p.get("collection"),
                "level": p.get("level"),
                "difficulty": p.get("difficulty"),
                "cosine": p.get("cosine", p.get("vector_score", 0.0)),
                "lexical": p.get("lexical", p.get("lexical_score", 0.0)),
                "final": p.get("final", p.get("score", 0.0)),
            }
            for p in passages
        ]

        trace = {
            "query": query_text,
            "filters": {
                "collections": collections,
                "concept": concept,
                "include_prereqs": include_prereqs,
                "types": types,
                "difficulty": difficulty,
                "target_level": target_level,
            },
            "embedder": self._embedder.signature() if self._embedder else "none",
            "candidates": candidates_count,
            "latency_ms": latency_ms,
            "query_cache_hit": query_cache_hit,
            "top": top_trace,
        }
        if query_vector is None:
            trace["degraded"] = "lexical_only"

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
        result["trace"] = trace
        return result

    def _embed_query(self, query_text):
        """
        Embed a query string with an in-memory LRU cache (256 entries)
        keyed by (embedder signature, query text).
        Returns (query_vector, query_cache_hit).
        Falls back to None if embedder is unavailable, signature mismatches,
        times out (>10s), or fails.
        """
        if not self._embedder:
            _log_degraded_warning("No embedder available. Falling back to lexical-only ranking.")
            return None, False

        index_sig = self.store.meta.get("embedder", "")
        current_sig = self._embedder.signature()
        if index_sig and current_sig and index_sig != current_sig:
            _log_degraded_warning(
                "Embedder signature mismatch ('{}' != '{}'). Never embedding query with mismatched signature; falling back to lexical-only.".format(
                    current_sig, index_sig
                )
            )
            return None, False

        key = (current_sig, query_text)
        if key in self._query_cache:
            self._query_cache.move_to_end(key)
            return self._query_cache[key], True

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._embedder.embed_one, query_text)
                vec = future.result(timeout=10.0)
            self._query_cache[key] = vec
            if len(self._query_cache) > 256:
                self._query_cache.popitem(last=False)
            return vec, False
        except concurrent.futures.TimeoutError:
            _log_degraded_warning("Query embedder timed out after 10 s. Falling back to lexical-only ranking.")
            return None, False
        except Exception as exc:
            _log_degraded_warning("Query embedder failed ({}). Falling back to lexical-only ranking.".format(exc))
            return None, False

    def retrieve_reference_questions(self, concept, difficulty, k=3, exclude_ids=()):
        """
        Stage 1: filter collection='question', concept=concept, strict difficulty, exclude_ids.
        Stage 2: 0.7*cosine + 0.3*lexical with near-duplicate rejection (cosine >= 0.90).
        Returns list of full question records (raw_record) annotated with scores.
        """
        if not self.is_ready():
            return []

        meta = CONCEPTS.get(concept)
        query_text = search_text_for(concept) if meta else (concept or "").replace("-", " ")
        query_vector, _ = self._embed_query(query_text)

        passages = self.store.search(
            query_vector,
            query_text=query_text,
            concept_tags=[concept],
            top_k=k,
            collections=["question"],
            types=["mcq"],
            difficulty=difficulty,
            exclude_ids=set(exclude_ids or []),
            near_duplicate_threshold=0.90 if query_vector is not None else None,
        )

        records = []
        for p in passages:
            rec = dict(p.get("raw_record") or {})
            rec["retrieval_score"] = p.get("score")
            rec["cosine"] = p.get("cosine")
            rec["lexical"] = p.get("lexical")
            rec["chunk_id"] = p.get("chunk_id")
            records.append(rec)
        return records

    def search_raw(self, query, top_k=8, concept_tags=None):
        """Plain search used by the Library page so students can explore the corpus."""
        if not self.is_ready():
            return {"ready": False, "results": [], "error": self._load_error}
        vector, _ = self._embed_query(query)
        results = _dedupe(self.store.search(
            vector, query_text=query, concept_tags=concept_tags, collections=["book", "note"], top_k=top_k * 2
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
