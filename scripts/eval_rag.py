"""
=============================================================================
EduGen RAG - Honest Retrieval Evaluation & Ablation (Phase 3B)
=============================================================================
Evaluates retrieval performance across all 44 canonical concepts using 3 queries
per concept (132 total queries):
  1. Concept title (e.g. "Defining a Class")
  2. Question-style query synthesized from concept summary
  3. Misconception wrong-belief statement from catalog

Modes:
  1. BLIND MODE (real measurement):
     - NO concept filtering; only collection filtering (lessons: book+note, questions: question)
     - Embeds each query ONCE in batch and re-ranks in memory
     - Metrics: Hit@1, Hit@3, Hit@5, MRR (overall and per module)
     - Ablation: Lexical-only vs Cosine-only vs Hybrid (0.7 cosine + 0.3 lexical)
     - Identifies the 5 weakest concepts (lowest blind Hit@3)
  2. SANITY CHECK (filtered):
     - Filters by concept_tags (100% by construction, retained as sanity check only)

Usage:
  python scripts/eval_rag.py [--backend ollama|hashing] [--sanity-only]
=============================================================================
"""

import argparse
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from core.concepts import CONCEPTS, MODULES
from core.misconceptions import misconceptions_for
from rag.retriever import Retriever
from rag.vector_store import tokenize, _cosine


def build_concept_queries(concept: str) -> list[tuple[str, str]]:
    """Return [(query_type, query_text)] for a concept (3 queries)."""
    meta = CONCEPTS[concept]
    title = meta["title"]
    summary = meta.get("summary", "")

    # Query 1: Concept title
    q1 = title

    # Query 2: Question-style query from summary
    first_sentence = summary.split(".")[0].strip() if summary else title
    q2 = f"How does {title} work in Java? {first_sentence}"

    # Query 3: Misconception wrong-belief
    m_list = misconceptions_for(concept)
    if m_list and m_list[0].get("wrong_belief"):
        q3 = m_list[0]["wrong_belief"]
    else:
        q3 = f"Why is {title} misunderstood in Java?"

    return [("title", q1), ("question", q2), ("misconception", q3)]


def evaluate_filtered_sanity(retriever: Retriever, precomputed_items: list = None) -> dict:
    """
    Sanity check (filtered): retrieve() filters by concept, so hit@k is 100%
    by construction. Retained purely as a wiring sanity check.
    """
    retriever.ensure_loaded()
    if not retriever.is_ready():
        return None

    module_stats = defaultdict(lambda: {"queries": 0, "lesson_h1": 0, "lesson_h3": 0, "lesson_h5": 0})
    overall = {"queries": 0, "lesson_h1": 0, "lesson_h3": 0, "lesson_h5": 0}

    t0 = time.time()
    for concept, mod, q_type, q_text, _ in precomputed_items:
        brief = {
            "concept": concept,
            "difficulty": "Medium",
            "mode": "lesson",
            "query": q_text,
            "top_k": 5,
        }
        res = retriever.retrieve(brief)
        passages = res.get("passages", [])
        h1 = 1 if passages and concept in passages[0].get("concept_tags", []) else 0
        h3 = 1 if any(concept in p.get("concept_tags", []) for p in passages[:3]) else 0
        h5 = 1 if any(concept in p.get("concept_tags", []) for p in passages[:5]) else 0

        module_stats[mod]["queries"] += 1
        module_stats[mod]["lesson_h1"] += h1
        module_stats[mod]["lesson_h3"] += h3
        module_stats[mod]["lesson_h5"] += h5

        overall["queries"] += 1
        overall["lesson_h1"] += h1
        overall["lesson_h3"] += h3
        overall["lesson_h5"] += h5

    elapsed = round(time.time() - t0, 2)
    return {
        "module_stats": module_stats,
        "overall": overall,
        "elapsed_sec": elapsed,
        "embedder": retriever.status().get("embedder", "unknown"),
    }


def evaluate_blind_and_ablation(retriever: Retriever, precomputed_items: list, embedding_time: float) -> dict:
    """
    Blind evaluation & ablation:
      - NO concept filter; only collection filter (lesson: book+note, question: question)
      - Queries: 3 per concept (132 total)
      - Embeds each query ONCE in batch and evaluates 3 variants in memory:
          1. Lexical-only (BM25 token overlap)
          2. Cosine-only (vector similarity)
          3. Hybrid (0.7 cosine + 0.3 lexical)
      - Metrics: Hit@1, Hit@3, Hit@5, MRR per module and overall
      - Identifies the 5 weakest concepts by blind Hit@3
    """
    retriever.ensure_loaded()
    if not retriever.is_ready():
        return None

    store = retriever.store
    t0 = time.time()

    # Pre-compute candidate indices for lesson (book+note) and question
    lesson_indices = [
        i for i, c in enumerate(store.chunks)
        if c.get("collection") in ("book", "note")
    ]
    question_indices = [
        i for i, c in enumerate(store.chunks)
        if c.get("collection") == "question"
    ]

    variants = ("lexical", "cosine", "hybrid")

    ablation_overall = {
        v: {
            "lesson": {"queries": 0, "h1": 0, "h3": 0, "h5": 0, "mrr": 0.0},
            "question": {"queries": 0, "h1": 0, "h3": 0, "h5": 0, "mrr": 0.0},
            "combined": {"queries": 0, "h1": 0, "h3": 0, "h5": 0, "mrr": 0.0},
        }
        for v in variants
    }

    module_stats = defaultdict(lambda: {
        "queries": 0, "h1": 0, "h3": 0, "h5": 0, "mrr": 0.0
    })

    concept_stats = defaultdict(lambda: {
        "queries": 0, "h1": 0, "h3": 0, "h5": 0, "mrr": 0.0, "module": ""
    })

    for concept, mod, q_type, q_text, query_vector in precomputed_items:
        query_tokens = tokenize(q_text)

        # Compute cosine against all chunks
        if HAS_NUMPY and store.vectors is not None and len(store.vectors):
            qv = np.asarray(query_vector, dtype="float32")
            norm = float(np.linalg.norm(qv)) or 1.0
            sims = np.asarray(store.vectors) @ (qv / norm)
        else:
            sims = [_cosine(query_vector, v) for v in (store.vectors or [])]

        # Evaluate for both lesson (book+note) and question (question) collections
        for mode, cand_indices in (("lesson", lesson_indices), ("question", question_indices)):
            if not cand_indices:
                continue

            candidates = []
            for idx in cand_indices:
                chunk = store.chunks[idx]
                vec_score = float(sims[idx]) if idx < len(sims) else 0.0
                cos_score = max(0.0, min(1.0, (vec_score + 1.0) / 2.0 if vec_score < 0 else vec_score))
                lex_score = store._lexical_score(query_tokens, idx)
                hyb_score = 0.7 * cos_score + 0.3 * lex_score

                candidates.append({
                    "idx": idx,
                    "chunk": chunk,
                    "cosine": cos_score,
                    "lexical": lex_score,
                    "hybrid": hyb_score,
                })

            for v in variants:
                ranked = sorted(candidates, key=lambda c: c[v], reverse=True)[:5]

                hit_ranks = []
                for rank_idx, cand in enumerate(ranked, start=1):
                    chk = cand["chunk"]
                    tags = chk.get("concept_tags") or []
                    c_val = chk.get("concept")
                    if concept in tags or c_val == concept:
                        hit_ranks.append(rank_idx)

                h1 = 1 if hit_ranks and hit_ranks[0] == 1 else 0
                h3 = 1 if hit_ranks and hit_ranks[0] <= 3 else 0
                h5 = 1 if hit_ranks and hit_ranks[0] <= 5 else 0
                mrr = (1.0 / hit_ranks[0]) if hit_ranks else 0.0

                ablation_overall[v][mode]["queries"] += 1
                ablation_overall[v][mode]["h1"] += h1
                ablation_overall[v][mode]["h3"] += h3
                ablation_overall[v][mode]["h5"] += h5
                ablation_overall[v][mode]["mrr"] += mrr

                ablation_overall[v]["combined"]["queries"] += 1
                ablation_overall[v]["combined"]["h1"] += h1
                ablation_overall[v]["combined"]["h3"] += h3
                ablation_overall[v]["combined"]["h5"] += h5
                ablation_overall[v]["combined"]["mrr"] += mrr

                if v == "hybrid" and mode == "lesson":
                    module_stats[mod]["queries"] += 1
                    module_stats[mod]["h1"] += h1
                    module_stats[mod]["h3"] += h3
                    module_stats[mod]["h5"] += h5
                    module_stats[mod]["mrr"] += mrr

                    concept_stats[concept]["queries"] += 1
                    concept_stats[concept]["h1"] += h1
                    concept_stats[concept]["h3"] += h3
                    concept_stats[concept]["h5"] += h5
                    concept_stats[concept]["mrr"] += mrr
                    concept_stats[concept]["module"] = mod

    rerank_elapsed = round(time.time() - t0, 2)
    total_elapsed = round(embedding_time + rerank_elapsed, 2)

    # 5 weakest concepts in hybrid lesson retrieval
    weak_concepts = []
    for c, s in concept_stats.items():
        q_count = s["queries"] or 1
        h3_pct = (s["h3"] / q_count) * 100.0
        mrr_val = s["mrr"] / q_count
        weak_concepts.append((h3_pct, mrr_val, c, s["module"]))
    weak_concepts.sort(key=lambda x: (x[0], x[1]))
    lowest_5 = weak_concepts[:5]

    return {
        "ablation_overall": ablation_overall,
        "module_stats": module_stats,
        "concept_stats": concept_stats,
        "lowest_5_concepts": lowest_5,
        "total_queries": len(precomputed_items),
        "embedding_time_sec": embedding_time,
        "rerank_time_sec": rerank_elapsed,
        "total_elapsed_sec": total_elapsed,
        "embedder": retriever.status().get("embedder", "unknown"),
    }


def print_ablation_table(metrics: dict):
    if not metrics:
        return

    abl = metrics["ablation_overall"]
    embedder = metrics["embedder"]

    print("\n" + "=" * 94)
    print(f"  BLIND RETRIEVAL ABLATION RESULTS (No concept filter)  |  Embedder: {embedder}")
    print("=" * 94)
    print(f"{'Target Collection':<18} | {'Variant':<12} | {'Hit@1':<8} | {'Hit@3':<8} | {'Hit@5':<8} | {'MRR':<8} | {'Queries':<8}")
    print("-" * 94)

    for mode_label, mode_key in (("Lessons (book+note)", "lesson"), ("Questions (MCQ)", "question"), ("Combined Overall", "combined")):
        for variant_name in ("lexical", "cosine", "hybrid"):
            s = abl[variant_name][mode_key]
            q = s["queries"] or 1
            h1 = (s["h1"] / q) * 100
            h3 = (s["h3"] / q) * 100
            h5 = (s["h5"] / q) * 100
            mrr = s["mrr"] / q
            v_disp = "Hybrid (0.7+0.3)" if variant_name == "hybrid" else variant_name.capitalize()
            print(f"{mode_label:<18} | {v_disp:<12} | {h1:>6.1f}% | {h3:>6.1f}% | {h5:>6.1f}% | {mrr:>8.4f} | {q:>7}")
        print("-" * 94)

    print(f"Total Queries: {metrics['total_queries']} embedded once in {metrics['embedding_time_sec']}s, in-memory re-ranked in {metrics['rerank_time_sec']}s (Total: {metrics['total_elapsed_sec']}s)")


def print_module_table(metrics: dict):
    mod_stats = metrics["module_stats"]
    print("\n" + "=" * 80)
    print("  BLIND HYBRID EVALUATION BY MODULE (Lessons: book+note, no concept filter)")
    print("=" * 80)
    print(f"{'Module':<20} | {'Queries':<8} | {'Hit@1':<8} | {'Hit@3':<8} | {'Hit@5':<8} | {'MRR':<8}")
    print("-" * 80)

    tot_q = tot_h1 = tot_h3 = tot_h5 = 0
    tot_mrr = 0.0

    for mod, _ in MODULES.items():
        s = mod_stats.get(mod)
        if not s or s["queries"] == 0:
            continue
        q = s["queries"]
        h1 = (s["h1"] / q) * 100
        h3 = (s["h3"] / q) * 100
        h5 = (s["h5"] / q) * 100
        mrr = s["mrr"] / q

        tot_q += q
        tot_h1 += s["h1"]
        tot_h3 += s["h3"]
        tot_h5 += s["h5"]
        tot_mrr += s["mrr"]

        print(f"{mod:<20} | {q:>8} | {h1:>6.1f}% | {h3:>6.1f}% | {h5:>6.1f}% | {mrr:>8.4f}")

    print("-" * 80)
    o_h1 = (tot_h1 / tot_q) * 100 if tot_q else 0
    o_h3 = (tot_h3 / tot_q) * 100 if tot_q else 0
    o_h5 = (tot_h5 / tot_q) * 100 if tot_q else 0
    o_mrr = tot_mrr / tot_q if tot_q else 0
    print(f"{'OVERALL (44 concepts)':<20} | {tot_q:>8} | {o_h1:>6.1f}% | {o_h3:>6.1f}% | {o_h5:>6.1f}% | {o_mrr:>8.4f}")
    print("=" * 80)


def print_weak_concepts(metrics: dict):
    lowest = metrics["lowest_5_concepts"]
    print("\n" + "=" * 80)
    print("  WEAKEST CONCEPTS IN BLIND RETRIEVAL (Lowest Blind Hit@3 in Hybrid)")
    print("=" * 80)
    print(f"{'Concept':<28} | {'Module':<18} | {'Blind Hit@3':<12} | {'MRR':<8}")
    print("-" * 80)
    for h3, mrr, concept, mod in lowest:
        print(f"{concept:<28} | {mod:<18} | {h3:>10.1f}% | {mrr:>8.4f}")
    print("=" * 80)


def print_sanity_table(sanity_metrics: dict):
    if not sanity_metrics:
        return
    overall = sanity_metrics["overall"]
    q = overall["queries"] or 1
    h1 = (overall["lesson_h1"] / q) * 100
    h3 = (overall["lesson_h3"] / q) * 100
    h5 = (overall["lesson_h5"] / q) * 100
    print("\n" + "=" * 80)
    print("  SANITY CHECK (FILTERED) - NOT A QUALITY METRIC")
    print("  (retrieve() filters by concept_tags, so Hit@k is 100% by construction)")
    print("=" * 80)
    print(f"  Lesson Queries : {q}")
    print(f"  Hit@1          : {h1:.1f}%")
    print(f"  Hit@3          : {h3:.1f}%")
    print(f"  Hit@5          : {h5:.1f}%")
    print(f"  Evaluation Time: {sanity_metrics['elapsed_sec']}s")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Evaluate EduGen RAG retrieval performance")
    parser.add_argument("--backend", default=None, help="Force backend (ollama, hashing)")
    parser.add_argument("--sanity-only", action="store_true", help="Run only filtered sanity check")
    args = parser.parse_args()

    retriever = Retriever(backend=args.backend, lazy=False)
    retriever.ensure_loaded()
    embedder = retriever._embedder

    # 1. Assemble 132 queries
    raw_query_items = []
    for concept, meta in sorted(CONCEPTS.items()):
        mod = meta.get("module", "other")
        for q_type, q_text in build_concept_queries(concept):
            raw_query_items.append((concept, mod, q_type, q_text))

    # 2. Batch-embed all 132 queries ONCE
    print(f"Embedding {len(raw_query_items)} queries once in batches...")
    t_emb0 = time.time()
    query_texts = [item[3] for item in raw_query_items]
    query_vectors = []
    batch_size = 32
    for b in range(0, len(query_texts), batch_size):
        query_vectors.extend(embedder.embed(query_texts[b:b + batch_size]))
    emb_time = round(time.time() - t_emb0, 2)
    print(f"Done embedding in {emb_time}s.")

    # Prime retriever query cache so any subsequent call hits LRU cache
    sig = embedder.signature()
    for text, vec in zip(query_texts, query_vectors):
        retriever._query_cache[(sig, text)] = vec

    precomputed = [
        (raw_query_items[i][0], raw_query_items[i][1], raw_query_items[i][2], raw_query_items[i][3], query_vectors[i])
        for i in range(len(raw_query_items))
    ]

    print("\nRunning filtered sanity check...")
    sanity_metrics = evaluate_filtered_sanity(retriever, precomputed)
    print_sanity_table(sanity_metrics)

    if not args.sanity_only:
        print("\nRunning blind evaluation & in-memory ablation (132 queries)...")
        blind_metrics = evaluate_blind_and_ablation(retriever, precomputed, emb_time)
        print_ablation_table(blind_metrics)
        print_module_table(blind_metrics)
        print_weak_concepts(blind_metrics)


if __name__ == "__main__":
    main()
