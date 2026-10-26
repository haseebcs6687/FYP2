# What is left for you

The system runs end to end. This is the remaining work, in the order I would
do it.

## Before the next supervisor meeting

**1. Add your own source material** *(30 minutes)*
Drop the OOP PDFs you want into `rag/corpus/books/` and run
`python -m rag.ingest --rebuild`. Or run `python scripts/fetch_books.py` for
three open-licence textbooks. More sources means better grounding, and
`/library` will show the coverage per concept.

**2. Switch to real embeddings** *(10 minutes + one download)*
`pip install sentence-transformers`, set
`EDUGEN_EMBEDDING_BACKEND=sentence-transformers`, then
`python -m rag.ingest --rebuild`. On an M-series Mac it uses MPS automatically.
The hashing backend is only there so the project boots anywhere.

**3. Generate real data** *(1–2 hours)*
Take 15–20 quizzes across different concepts, deliberately failing some
prerequisite concepts. This is what makes rules R2 and R4 fire in a live demo,
and it gives you numbers for the evaluation chapter.

## For the final report

**4. Evaluation chapter**
The hooks are already in the code — see section 8 of `docs/ARCHITECTURE.md`.
The most convincing experiments:
- Adaptive accuracy: `scripts/test_adaptivity.py` output goes straight in as a table
- Grounding rate: count `generated_by == "llm+rag"` vs `"llm"` in `quiz_sessions`
- Acceptance rate: already computed, shown on `/history`
- Retrieval precision: pick 10 concepts, search each on `/library`, judge the
  top 5 by hand. Report precision@5 with the three score components.

**5. Threshold sensitivity**
`WEAK_THRESHOLD`, `STRONG_THRESHOLD`, `EWMA_ALPHA` and `REVIEW_AFTER_DAYS` are
constants at the top of `agents/performance_analysis_agent.py`. Vary them,
re-run `test_adaptivity.py`, and report how the classification shifts. This is
cheap and it looks rigorous.

**6. Update the report figures**
The FYP-1 architecture diagram no longer matches. It needs:
- the RAG block between Adaptive Content and Concept Clarifier
- the retrieval brief as a labelled arrow
- `quiz_sessions`, `recommendations` and `lesson_views` in the schema diagram
- Random Forest removed — the Performance Analysis Agent is now a concept-graph
  evidence classifier, and the synthetic 300-row dataset is gone

**7. Keep architecture docs aligned**
Keep `AGENTS.md` and `docs/ARCHITECTURE.md` updated as agent behaviour evolves.

## Nice to have, not required

- **Question quality review.** Read 20 generated questions and note how many are
  good. Cheap to do and gives you an honest number for the limitations section.
- **Retry on rate limit.** Groq's free tier will throttle during a long demo.
  One exponential backoff in `_call_llm` would smooth that over.
- **Concept graph visualisation.** The data is already in
  `core/concepts.py`; a D3 force graph on `/learn` would demo well.
- **Export a student report as PDF** for the supervisor.

## Known limitations — state these in the report, do not hide them

1. **No human validation of generated questions yet.** The validator checks
   structure, not correctness. Say so and report a manual sample.
2. **Single-user SQLite.** Fine for a demo, not for a class of 40.
3. **Concept tags on generated questions come from the LLM.** Constrained to the
   44-tag vocabulary, but not independently verified.
4. **Rules are hand-tuned, not learned.** That is a deliberate trade for
   explainability, and it is worth defending rather than apologising for.
5. **Response time is a weak signal on its own.** A student who walks away
   mid-quiz looks identical to one who is thinking hard.
