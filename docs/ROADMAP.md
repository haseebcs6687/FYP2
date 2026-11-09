# EduGen Project Requirement Tracker & Roadmap

## Done
- **DB foundation**: SQLite schema, schema migrations framework (1-5), repository layer with resilient CRUD (`core/db_repo.py`).
- **Misconception catalog**: 187 granular misconceptions spanning 44 canonical concept tags across 8 Java OOP modules (`core/misconceptions.py`, `docs/catalog_for_llm/`).
- **Question bank**: 600 verified Java questions (`rag/corpus/questions/raw/`).
- **RAG subsystem**: Hybrid vector + BM25 + tag ranking, Ollama embeddings (`nomic-embed-text`), 7,333 chunks, blind evaluation hit@3 95.8%.
- **Misconception-first quiz engine**: Live generation with independent verifier, deterministic JDK compiler/runner gate (`core/java_check.py`), semantic and hash deduplication.
- **Verified question pool**: seeded from the bank (431) plus live additions; run scripts/pool_status.py for the current number.
- **Token budget management**: Daily limit enforcement, automatic model fallback, reasoning effort tuning (`core/token_budget.py`).
- **Prebuilt diagnostic sets**: Instant zero-latency diagnostic evaluation sets (`rag/corpus/diagnostic/`).
- **Unified test runner**: `scripts/run_all_tests.py` executing all 13 repository test suites with isolated subprocesses and timeout protection.
- **Phase 5 — Performance Analysis Agent**: Bayesian Knowledge Tracing (BKT) mastery estimation, misconception-level tracking (`active`, `suspected`, `resolved`), severity decay scoring, facet error mapping, skill profile by question type (`concept`, `code_output`, `bug_find`).
- **Phase 5B — Simulation & Display Clamping**: Honest synthetic simulation harness, display mastery clamping ($[2.0\%, 98.0\%]$), baseline comparison.
- **Phase 5C — Probe Quizzes & Closed-Loop Simulation**: Targeted `probe` quiz kind sweeping untargeted catalog misconceptions with relaxed difficulty, dual student response models (Model A & Model B), 81.2%–100.0% detectable recall (`docs/PA_EVAL.md`).
- **Phase 6 — Adaptive Content Agent**: Full ordered study plan generation (weak concepts + prerequisite closure, topological sort via Kahn's algorithm, calibrated difficulty and lesson style per step, editable prompt per step with student notes, formal coverage checker validating no prerequisite or active misconception is missed).
- **Phase 6B — Planner Refinements & Evaluation**: Frontier-based real advance progression along `learning_order()`, fast diagnostic `check` quiz steps for unproven prerequisites with dynamic runtime adaptation (`plan_after_check`), difficulty cap (`Medium`) for skill gaps, sentinel cleanup (`plan_step_concepts`), 100% topological validity, 100% prerequisite closure, 100% check precedence, 0 false negatives, honest evaluation wording (`docs/STUDY_PLANNER.md`, `docs/PLAN_EXAMPLES.md`).

- **Phase 7 — Concept Clarifier Agent**: Plan-driven interactive lessons per study plan step (simplified <= 400w and detailed 400-900w styles), SHA-1 lesson cache with index signature invalidation, deterministic Java compilation gate (`javac`), independent pedagogical verifier gate (`states_wrong_belief_as_true`), injection-safe student notes, fallback ladder, and `/lesson-step/<id>` interactive UI (`core/lesson_engine.py`, `docs/LESSON_ENGINE.md`).
- **Phase 8 — Coordinator Agent**: Autonomous learning loop orchestration (quiz -> analysis -> plan -> lessons -> "I'm ready" -> closing quizzes -> completion), state machine (`core/journey.py`), centralized structured event bus (`core/event_bus.py`) with contextvars-driven pipeline runs, background thread context propagation, in-memory ring buffer, non-blocking lesson prefetching, fail-safe SQLite persistence, 91.7% automation ratio, and 100% test coverage across all 17 test suites (`docs/COORDINATOR.md`, `docs/EVENT_BUS.md`).

- **Phase 9 — UI Cleanup & Evaluator Activity Window**: Clean student experience + Evaluator Activity window (capsule on click, minimize button top-right, continuous background polling, displays live agent events, pipeline runs, RAG retrieval passages with cosine scores, agent decisions with coverage invariants, and quiz build telemetry).
- **Phase 9B — Journey Real-Path Submission & Quarantine**: Current-plan completion invariant, Coordinator marks check and probe steps done on passing, quarantine tool for biased live questions, test registry.
- **Phase 9C — Permanent Evaluator Capsule, Tighter Bias Gate & Pass Threshold**: Removed Close (x) button and closed state (2-state model: open/minimized, persistent polling, stored state normalization), tightened live question length bias gate from 1.10x to 1.03x with strictly longest condition, standardized passing accuracy threshold (`PASS_ACCURACY = 70.0%`).
- **Phase 9D — JS Syntax Fix & Browser Smoke Tests**: Removed duplicated block in `static/js/edugen.js`, added syntax checker test suite (`scripts/test_js.py`) with injection proof, added full Playwright browser smoke test suite (`scripts/test_browser.py`) covering all 6 student pages with screenshot captures (`docs/ui_check/`), expanded unified test runner to 20 test suites.
- **Phase 10 — Demo Seed Student, PDF Report & Security**: Seed student profile (`demo@edugen.local` / `demo-pass`), downloadable PDF performance summary report (`/report.pdf`, ReportLab, publication quality, zero technical jargon), per-session CSRF protection (`hmac.compare_digest`, token rotation on login/logout, zero bypass), thread-safe in-memory login & signup rate limiting with injectable clock, production security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`), sanitized generic 500 error handler, updated browser test suite with real quiz attempt submission, 22 test suites passing.
- **Phase 11a — Question Bank Top-Up Generation**: Gap-driven targeted question generation planning (`tools/question_bank/gen_gap_plan.py`) addressing cell deficits (targets: Easy >= 4, Medium >= 3, Hard >= 3 across all 44 concepts), generating 288 high-quality questions across 24 batches in `rag/corpus/questions/raw/` with structural validation, compiler checks, and deduplication (`docs/MCQ_GENERATION.md`).
- **Phase 11b — Question Pool Seeding & Status Measurement**: Seeded 24 new batches (288 questions, 239 accepted with 83.0% pass rate, 54 relabeled, 49 rejected, 42,548 verifier tokens) into active verified question pool reaching 703 active pool questions (350 Easy, 217 Medium, 105 Hard) across all 44 concepts. Zero concepts with Easy deficits (all $\ge 4$). Blind heuristic bias audit confirmed all 7 test-wise strategies $\le 27.2\%$ accuracy on new questions (target $\le 35.0\%$, random baseline 25.0%), requiring 0 questions quarantined; all 22 test suites passing (402/402 tests) (`docs/POOL_STATUS.md`, `docs/POOL_SEEDING.md`).
- **Phase 12 — Report Assets Pipeline, Resilience Fallbacks & Documentation Refresh**:
  - **Misconception Tag Coverage Audit**: Audited all 703 active pool questions; confirmed 100% of concepts (44/44) have questions with validated misconception distractor tags (zero zero-tag concepts). Empirically verified Performance Analysis agent downward BKT mastery update on untagged questions.
  - **Graceful Resilience Fallbacks**: Handled Ollama outage with seamless in-memory BM25 lexical retrieval fallback; handled Groq downtime with structured 503 JSON events for quizzes and verified local concept note synthesis for lessons; implemented `/api/health` monitoring endpoint (zero credentials leaked).
  - **Automated Report Assets Pipeline (`scripts/make_report_assets.py`)**: Produced reproducible CSV datasets and 150 DPI publication charts in `docs/report_assets/` (pool distribution, textbook bank ingestion, blind heuristic bias resistance, tag coverage, test suite summary, autonomous journey efficiency, RAG/PA evaluation benchmarks, and complete Mermaid architecture specification `architecture.mmd` with provenance manifest `MANIFEST.md`).
  - **Expanded Unified Test Runner**: Expanded to 23 distinct test suites (adding `tests/test_resilience.py` with 13 resilience scenarios), maintaining 100% passing test execution.

---

## In Progress
- **Project Completion & Final Verification**: Comprehensive review of system requirements, documentation alignment, final integration.

---

## Pending (by Phase)
- **End / Submission**: Ethics section with supervisor, comprehensive review of chat requirements, optional question pool top-up, Llama offline lesson generation fallback, Groq key rotation.

