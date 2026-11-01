# EduGen Project Requirement Tracker & Roadmap

## Done
- **DB foundation**: SQLite schema, schema migrations framework (1-4), repository layer with resilient CRUD (`core/db_repo.py`).
- **Misconception catalog**: 187 granular misconceptions spanning 44 canonical concept tags across 8 Java OOP modules (`core/misconceptions.py`, `docs/catalog_for_llm/`).
- **Question bank**: 600 verified Java questions (`rag/corpus/questions/raw/`).
- **RAG subsystem**: Hybrid vector + BM25 + tag ranking, Ollama embeddings (`nomic-embed-text`), 7,333 chunks, blind evaluation hit@3 95.8%.
- **Misconception-first quiz engine**: Live generation with independent verifier, deterministic JDK compiler/runner gate (`core/java_check.py`), semantic and hash deduplication.
- **Verified question pool**: 431 active verified questions with 3-way tag voting consensus (`data/bank_work/raw_before_2Ec`, raw bank, independent verifier).
- **Token budget management**: Daily limit enforcement, automatic model fallback, reasoning effort tuning (`core/token_budget.py`).
- **Prebuilt diagnostic sets**: Instant zero-latency diagnostic evaluation sets (`rag/corpus/diagnostic/`).
- **Unified test runner**: `scripts/run_all_tests.py` executing all repository test suites with isolated subprocesses and timeout protection.

---

## Pending (by Phase)
- **Phase 5 (Current) — Performance Analysis Agent**: Bayesian Knowledge Tracing (BKT) mastery estimation, misconception-level tracking (`active`, `suspected`, `resolved`), severity scoring, facet error mapping, skill profile by question type (`concept`, `code_output`, `bug_find`), simulation-based evaluation (`docs/PA_EVAL.md`).
- **Phase 6 — Adaptive Content Agent**: Full ordered study plan generation (weak concepts + prerequisites, topological sort, calibrated difficulty per step, editable prompt per step that the student can extend, coverage checker validating no prerequisite is missed).
- **Phase 7 — Concept Clarifier Agent**: Interactive lesson generation per study plan step, offering simplified and detailed versions grounded in RAG corpus passages.
- **Phase 8 — Coordinator Agent**: Autonomous state machine orchestration (quiz -> analysis -> plan -> lessons -> "I'm ready" -> re-quiz loop) + event bus with real structured event emission.
- **Phase 9 — UI Cleanup & Evaluator Activity Window**: Clean student experience (student sees only lesson/quiz/plan/progress; unreadable lesson text/backgrounds fixed) + Evaluator Activity window (opens on click, minimize button top-right, keeps updating while minimized, displays live agent events, RAG retrieval passages with cosine scores and chunks).
- **Phase 10 — Demo Seed Student, PDF Report & Security**: Seed student profile, downloadable PDF performance summary report, CSRF protection, login rate limiting, final integration verification.
- **End / Submission**: Ethics section with supervisor, comprehensive review of chat requirements, optional question pool top-up, Llama offline lesson generation fallback, Groq key rotation.

