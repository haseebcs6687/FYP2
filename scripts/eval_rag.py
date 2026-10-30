"""
=============================================================================
EduGen RAG - Retrieval Evaluation (Phase 3)
=============================================================================
Evaluates retrieval performance across all 44 canonical concepts using 3 queries
per concept:
  1. Concept title (e.g. "Defining a Class")
  2. Question-style query synthesized from concept summary
  3. Misconception wrong-belief statement from catalog

Measures:
  - Lesson retrieval: Hit@1, Hit@3, Hit@5 (returned passage tagged with concept)
  - Question retrieval: Hit@1, Hit@3, Hit@5 (concept match) + Strict Difficulty accuracy

Aggregates:
  - Overall (44 concepts, 132 queries)
  - Per module (8 modules)

Usage:
  python scripts/eval_rag.py [--backend ollama|hashing] [--compare]
=============================================================================
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.concepts import CONCEPTS, MODULES
from core.misconceptions import misconceptions_for
from rag.retriever import Retriever


def build_concept_queries(concept: str) -> list[tuple[str, str]]:
    """Return [(query_type, query_text)] for a concept."""
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
        q3 = f"Common pitfalls and subtle bugs with {title}"

    return [("title", q1), ("question", q2), ("misconception", q3)]


def evaluate_retriever(retriever: Retriever, verbose: bool = False):
    """
    Run evaluation across all 44 concepts and return structured metrics.
    """
    retriever.ensure_loaded()
    if not retriever.is_ready():
        print("Error: Retriever is not ready. Index missing or empty.")
        return None

    # Track metrics per module and overall
    # metrics: { 'lesson_hits': [1, 3, 5], 'q_hits': [1, 3, 5], 'q_diff_ok': int, 'total_q': int }
    module_stats = defaultdict(lambda: {
        "queries": 0,
        "lesson_h1": 0, "lesson_h3": 0, "lesson_h5": 0,
        "q_evals": 0,
        "q_h1": 0, "q_h3": 0, "q_h5": 0,
        "q_diff_ok": 0,
    })

    overall = {
        "queries": 0,
        "lesson_h1": 0, "lesson_h3": 0, "lesson_h5": 0,
        "q_evals": 0,
        "q_h1": 0, "q_h3": 0, "q_h5": 0,
        "q_diff_ok": 0,
    }

    t0 = time.time()
    for concept, meta in sorted(CONCEPTS.items()):
        mod = meta.get("module", "other")
        queries = build_concept_queries(concept)

        # 1. Lesson retrieval eval (3 queries per concept)
        for q_type, q_text in queries:
            brief = {
                "concept": concept,
                "difficulty": "Medium",
                "mode": "lesson",
                "query": q_text,
                "top_k": 5,
            }
            res = retriever.retrieve(brief)
            passages = res.get("passages", [])

            # Check hit@k
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

        # 2. Question retrieval eval (across Easy, Medium, Hard)
        for diff in ("Easy", "Medium", "Hard"):
            q_recs = retriever.retrieve_reference_questions(concept, diff, k=5)
            # Check concept match and difficulty match
            qh1 = 1 if q_recs and q_recs[0].get("concept") == concept else 0
            qh3 = 1 if any(r.get("concept") == concept for r in q_recs[:3]) else 0
            qh5 = 1 if any(r.get("concept") == concept for r in q_recs[:5]) else 0

            # Strict difficulty check
            diff_ok = 1 if q_recs and all(r.get("difficulty") == diff for r in q_recs) else 0

            module_stats[mod]["q_evals"] += 1
            module_stats[mod]["q_h1"] += qh1
            module_stats[mod]["q_h3"] += qh3
            module_stats[mod]["q_h5"] += qh5
            module_stats[mod]["q_diff_ok"] += diff_ok

            overall["q_evals"] += 1
            overall["q_h1"] += qh1
            overall["q_h3"] += qh3
            overall["q_h5"] += qh5
            overall["q_diff_ok"] += diff_ok

    elapsed = round(time.time() - t0, 2)
    return {
        "module_stats": module_stats,
        "overall": overall,
        "elapsed_sec": elapsed,
        "embedder": retriever.status().get("embedder", "unknown"),
    }


def print_eval_table(metrics: dict):
    if not metrics:
        return

    mod_stats = metrics["module_stats"]
    overall = metrics["overall"]
    embedder = metrics["embedder"]

    print("\n" + "=" * 88)
    print(f"  EduGen RAG Evaluation Results  |  Embedder: {embedder}")
    print("=" * 88)

    hdr = f"{'Module':<20} | {'Lesson H@1':<10} | {'Lesson H@3':<10} | {'Lesson H@5':<10} | {'MCQ H@1':<8} | {'MCQ H@3':<8} | {'Diff Match':<10}"
    print(hdr)
    print("-" * 88)

    for mod, _ in MODULES.items():
        s = mod_stats.get(mod)
        if not s or s["queries"] == 0:
            continue
        l_h1 = (s["lesson_h1"] / s["queries"]) * 100
        l_h3 = (s["lesson_h3"] / s["queries"]) * 100
        l_h5 = (s["lesson_h5"] / s["queries"]) * 100

        q_h1 = (s["q_h1"] / s["q_evals"]) * 100 if s["q_evals"] else 0
        q_h3 = (s["q_h3"] / s["q_evals"]) * 100 if s["q_evals"] else 0
        q_diff = (s["q_diff_ok"] / s["q_evals"]) * 100 if s["q_evals"] else 0

        print(f"{mod:<20} | {l_h1:>8.1f}% | {l_h3:>8.1f}% | {l_h5:>8.1f}% | {q_h1:>6.1f}% | {q_h3:>6.1f}% | {q_diff:>9.1f}%")

    print("-" * 88)
    tot_q = overall["queries"]
    tot_qe = overall["q_evals"]
    o_lh1 = (overall["lesson_h1"] / tot_q) * 100 if tot_q else 0
    o_lh3 = (overall["lesson_h3"] / tot_q) * 100 if tot_q else 0
    o_lh5 = (overall["lesson_h5"] / tot_q) * 100 if tot_q else 0
    o_qh1 = (overall["q_h1"] / tot_qe) * 100 if tot_qe else 0
    o_qh3 = (overall["q_h3"] / tot_qe) * 100 if tot_qe else 0
    o_qdiff = (overall["q_diff_ok"] / tot_qe) * 100 if tot_qe else 0

    print(f"{'OVERALL (44 concepts)':<20} | {o_lh1:>8.1f}% | {o_lh3:>8.1f}% | {o_lh5:>8.1f}% | {o_qh1:>6.1f}% | {o_qh3:>6.1f}% | {o_qdiff:>9.1f}%")
    print("=" * 88)
    print(f"Total Queries Evaluated : {tot_q} lesson queries + {tot_qe} MCQ retrievals in {metrics['elapsed_sec']}s")


def main():
    parser = argparse.ArgumentParser(description="Evaluate EduGen RAG retrieval performance")
    parser.add_argument("--backend", default=None, help="Force backend (ollama or hashing)")
    args = parser.parse_args()

    retriever = Retriever(backend=args.backend, lazy=False)
    metrics = evaluate_retriever(retriever)
    if metrics:
        print_eval_table(metrics)


if __name__ == "__main__":
    main()
