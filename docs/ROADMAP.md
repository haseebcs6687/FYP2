# EduGen Project Requirement Tracker & Roadmap

## Done
- **DB foundation**: SQLite schema, schema migrations framework (1-5), repository layer with resilient CRUD (`core/db_repo.py`).
- **Misconception catalog**: 187 granular misconceptions spanning 44 canonical concept tags across 8 Java OOP modules (`core/misconceptions.py`, `docs/catalog_for_llm/`).
- **Question bank**: 600 verified Java questions (`rag/corpus/questions/raw/`).
- **RAG subsystem**: Hybrid vector + BM25 + tag ranking, Ollama embeddings (`nomic-embed-text`), 7,333 chunks, blind evaluation hit@3 95.8%.
- **Misconception-first quiz engine**: Live generation with independent verifier, deterministic JDK compiler/runner gate (`core/java_check.py`), semantic and hash deduplication.
- **Verified question pool**: 441 active verified questions with 3-way tag voting consensus (`data/bank_work/raw_before_2Ec`, raw bank, independent verifier).
- **Token budget management**: Daily limit enforcement, automatic model fallback, reasoning effort tuning (`core/token_budget.py`).
- **Prebuilt diagnostic sets**: Instant zero-latency diagnostic evaluation sets (`rag/corpus/diagnostic/`).
- **Unified test runner**: `scripts/run_all_tests.py` executing all 13 repository test suites with isolated subprocesses and timeout protection.
- **Phase 5 — Performance Analysis Agent**: Bayesian Knowledge Tracing (BKT) mastery estimation, misconception-level tracking (`active`, `suspected`, `resolved`), severity decay scoring, facet error mapping, skill profile by question type (`concept`, `code_output`, `bug_find`).
- **Phase 5B — Simulation & Display Clamping**: Honest synthetic simulation harness, display mastery clamping ($[2.0\%, 98.0\%]$), baseline comparison.
- **Phase 5C — Probe Quizzes & Closed-Loop Simulation**: Targeted `probe` quiz kind sweeping untargeted catalog misconceptions with relaxed difficulty, dual student response models (Model A & Model B), 81.2%–100.0% detectable recall (`docs/PA_EVAL.md`).
- **Phase 6 — Adaptive Content Agent**: Full ordered study plan generation (weak concepts + prerequisite closure, topological sort via Kahn's algorithm, calibrated difficulty and lesson style per step, editable prompt per step with student notes, formal coverage checker validating no prerequisite or active misconception is missed).
- **Phase 6B — Planner Refinements & Evaluation**: Frontier-based real advance progression along `learning_order()`, fast diagnostic `check` quiz steps for unproven prerequisites with dynamic runtime adaptation (`plan_after_check`), difficulty cap (`Medium`) for skill gaps, sentinel cleanup (`plan_step_concepts`), 100% topological validity, 100% prerequisite closure, 100% check precedence, 0 false negatives, honest evaluation wording (`docs/STUDY_PLANNER.md`, `docs/PLAN_EXAMPLES.md`).

- **Phase 7 — Concept Clarifier Agent**: Plan-driven interactive lessons per study plan step (simplified <= 400w and detailed 400-900w styles), SHA-1 lesson cache with index signature invalidation, deterministic Java compilation gate (`javac`), independent pedagogical verifier gate (`states_wrong_belief_as_true`), injection-safe student notes, fallback ladder, and `/lesson-step/<id>` interactive UI (`core/lesson_engine.py`, `docs/LESSON_ENGINE.md`).

---

## In Progress
- **Phase 8 (Next) — Coordinator Agent**: Autonomous state machine orchestration (quiz -> analysis -> plan -> lessons -> "I'm ready" -> re-quiz loop) + event bus with real structured event emission.

---

## Pending (by Phase)
- **Phase 8 — Coordinator Agent**: Autonomous state machine orchestration (quiz -> analysis -> plan -> lessons -> "I'm ready" -> re-quiz loop) + event bus with real structured event emission.
- **Phase 9 — UI Cleanup & Evaluator Activity Window**: Clean student experience (student sees only lesson/quiz/plan/progress; unreadable lesson text/backgrounds fixed) + Evaluator Activity window (opens on click, minimize button top-right, keeps updating while minimized, displays live agent events, RAG retrieval passages with cosine scores and chunks).
- **Phase 10 — Demo Seed Student, PDF Report & Security**: Seed student profile, downloadable PDF performance summary report, CSRF protection, login rate limiting, final integration verification.
- **End / Submission**: Ethics section with supervisor, comprehensive review of chat requirements, optional question pool top-up, Llama offline lesson generation fallback, Groq key rotation.

