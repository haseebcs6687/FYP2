# EduGen Project Status & TODO (FYP-2)

This document reflects the real, verified implementation state of the EduGen multi-agent tutoring system as of Phase 12. Every item under **Done** is backed by passing automated tests and live database records.

---

## Done

### 1. Multi-Agent Pedagogical Architecture
- **Coordinator Agent (`agents/coordinator_agent.py`)**:
  - Pure control-flow routing without direct LLM calls or pedagogy leakage.
  - Implements the complete autonomous learning loop: Diagnostic Assessment $\rightarrow$ Performance Analysis $\rightarrow$ Adaptive Content Planning $\rightarrow$ Concept Clarification / Lesson Delivery $\rightarrow$ "I'm ready" $\rightarrow$ Diagnostic Check / Probe $\rightarrow$ Closing Reevaluation $\rightarrow$ Course Completion.
  - Emits structured domain events with monotonic sequence IDs consumed by the Evaluator Activity Window and pipeline telemetry.
  - Supports non-blocking background lesson prefetching during active study steps.
- **Performance Analysis Agent (`agents/performance_analysis_agent.py`)**:
  - Bayesian Knowledge Tracing (BKT) engine tracking concept-level masteries ($P(L_t)$) with display clamping ($[2.0\%, 98.0\%]$).
  - Recency-weighted mastery using Exponentially Weighted Moving Average (EWMA, $\alpha = 0.35$).
  - Granular misconception diagnosis extracting distractor misconceptions (`active`, `suspected`, `resolved`) with severity decay.
  - Prerequisite root-cause analysis tracing observed weaknesses backward through the directed acyclic prerequisite graph.
  - Skill profiling categorizing performance across question formats (`concept`, `code_output`, `bug_find`).
- **Adaptive Content Agent (`agents/adaptive_content_agent.py`)**:
  - Deterministic 6-rule policy engine (R1–R6) mapping diagnostic signals to targeted pedagogical actions.
  - Prerequisite-closed study plan generator using Kahn's topological sort algorithm, ensuring strict prerequisite ordering.
  - Generates diagnostic `check` steps for unproven prerequisites and `probe` steps for sweeping untargeted catalog misconceptions.
  - Formal plan invariant verifier guaranteeing 100% prerequisite closure, topological validity, and frontier advancement.
- **Concept Clarifier Agent (`agents/concept_clarifier_agent.py`)**:
  - The single agent authorized to interact with external LLMs (Groq / LLaMA 3.3 70B Versatile).
  - Generates plan-driven interactive lessons in dual styles: `simplified` ($\le 400$ words) and `detailed` ($400\text{--}900$ words).
  - Grounded RAG synthesis retrieving relevant textbook excerpts against the retrieval brief contract.
  - Deterministic Java compilation gate (`javac`) executing code snippets against OpenJDK 21.
  - Pedagogical misconception refutation gate detecting whether explanations inadvertently validate false student beliefs.
  - Injection-safe sanitization isolating untrusted student notes from system instructions.
  - SHA-1 lesson caching keyed on concept, style, prerequisite context, and RAG index signature.

### 2. Knowledge Base & RAG Subsystem
- **44 Canonical Concept Taxonomy & Graph (`core/concepts.py`)**:
  - 44 canonical concepts grouped across 8 Java OOP modules (`oo_basics`, `classes_objects`, `inheritance`, `polymorphism`, `interfaces_abstract`, `exceptions`, `collections`, `advanced_oop`).
  - Formally defined directed acyclic prerequisite graph.
- **Granular Misconception Catalog (`core/misconceptions.py`)**:
  - 187 fine-grained cataloged student misconceptions with descriptive names, underlying flawed mental models, and targeted refutation strategies.
- **RAG Hybrid Retrieval Pipeline (`rag/`)**:
  - 7,333 heading-aware chunks indexed across 3 open-licensed Java textbooks (*Think Java 2e*, *Introduction to Programming in Java*, *Java Programming Language*).
  - Hybrid scoring combining cosine similarity on Ollama `nomic-embed-text` dense embeddings, BM25 lexical ranking, and exact concept tag boosts.
  - Evaluated retrieval precision: 95.8% Hit@3 and 0.819 MRR across canonical benchmark queries.
  - Degraded mode fallback: Automatic graceful degradation to BM25 lexical search over memory-cached chunks when the Ollama embedding service is unreachable.

### 3. Question Bank & Verified Active Pool
- **Verified Active Question Pool (`data/edugen.db`)**:
  - 703 verified active questions across all 44 canonical concepts and 3 difficulty tiers (350 Easy, 217 Medium, 105 Hard).
  - Zero concepts with Easy deficits (all 44 concepts have $\ge 4$ Easy questions, meeting target).
  - Question pool misconception distractor tags (computed strictly from `questions.tags_json`): 373 of 703 active questions (53.1%) carry $\ge 1$ tagged distractor, with 584 total distractor misconception tags across all 44 concepts (42 of 44 concepts have $\ge 3$ tagged questions; only `inheritance-hierarchy` and `null-pointer-exception` have 2; unverified verifier label guesses are kept separate).
  - Seeded from verified textbook question banks (642 questions from 74 batches) and vetted live additions (61 questions).
  - Dual-layer bias audit: All 7 blind test-wise heuristic strategies score $\le 27.2\%$ accuracy on newly seeded questions (target $\le 35.0\%$, random baseline $25.0\%$), with zero questions requiring bias quarantine.
  - Strict length and letter bias admission gates during generation.

### 4. Platform, Security & User Experience
- **Server-Rendered Multi-Page Application (`routes/`, `templates/`, `static/`)**:
  - 12 Jinja2 server-rendered pages (Dashboard, Learn, Quiz, Analysis, History, Library, Pipeline, Plan, Lesson Step, Login, Signup).
  - Persistent **Evaluator Activity Window** capsule pill: 2-state UI model (`open` / `minimized`), continuous background event polling, inspects live multi-agent handoffs, cosine similarity scores, and LLM telemetry without disrupting the student workflow.
  - Comprehensive JavaScript error handling and syntax validation (`scripts/test_js.py`).
  - Automated Playwright browser smoke test suite (`scripts/test_browser.py`) capturing clean screenshots across all core student pages.
- **Application Security & Hardening (`core/security.py`, `core/auth.py`)**:
  - Per-session cryptographically secure CSRF token protection with constant-time verification (`hmac.compare_digest`) and token rotation on authentication state changes.
  - Thread-safe, injectable-clock rate limiting defending login and registration endpoints against brute-force attacks.
  - Defensive HTTP security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`).
  - Sanitized global 500 error handler suppressing internal stack traces.
  - System health check endpoint (`GET /api/health`) exposing database status, Ollama reachability, Groq availability, and pool statistics with zero credentials.
- **Student Performance Reporting (`core/report.py`)**:
  - Publication-grade PDF performance report generation (`/report.pdf`) via ReportLab with clean typography, executive summaries, curriculum mastery status tables, and plain-English pedagogical recommendations.
- **Comprehensive Test Suite & Verification (`scripts/run_all_tests.py`)**:
  - Unified runner orchestrating 23 distinct test suites in isolated subprocesses with timeout protection, enforcing 100% test passing before code promotion.
- **Automated Report Asset Generation (`scripts/make_report_assets.py`)**:
  - Automated pipeline producing reproducible CSV datasets, 150 DPI publication charts, Mermaid architecture diagrams, and a data provenance manifest (`docs/report_assets/MANIFEST.md`).

---

## Remaining

### 1. Demonstration & Viva Walkthrough Rehearsal
- Execute and rehearse the 5-minute click-by-click viva demonstration script in `docs/DEMO.md`.
- Validate that the seed student profile (`demo@edugen.local`) correctly demonstrates the 5/6 completed study plan and the final reevaluation quiz transition.
- Ensure the Evaluator Activity Window displays real-time agent handoffs cleanly during the live presentation.

### 2. Final Report Document Asset Integration
- Embed the generated 150 DPI figures from `docs/report_assets/` into the final dissertation document:
  - `architecture.mmd`: Figure 3.1 (Multi-Agent System Architecture).
  - `pool_by_concept.png` & `pool_by_origin.png`: Figures 4.1 & 4.2 (Question Pool Distribution).
  - `question_bank_by_pdf.png`: Figure 4.3 (Textbook Bank Ingestion Yield).
  - `bias_audit.png`: Figure 4.4 (Blind Heuristic Bias Resistance).
  - `tag_coverage.png`: Figure 4.5 (Misconception Distractor Tag Coverage).
  - `test_summary.png`: Figure 5.1 (Automated Test Suite Coverage).
  - `journey_metrics.png`: Figure 5.2 (Coordinator Autonomous Loop Efficiency).
  - `rag_eval.png` & `performance_eval.png`: Figures 5.3 & 5.4 (RAG and PA Simulation Benchmarks).

### 3. Thesis Prose Alignment with Empirical Data
- Align text in Chapters 4 (Implementation) and 5 (Evaluation) with the exact numbers documented in `docs/report_assets/MANIFEST.md` (e.g. 703 active pool questions, 23 test suites, 68.4% honest automation ratio).

---

## Deferred

### 1. Ethics and Pedagogical Fairness Evaluation
- **Deliberate Decision for the Final Report Author**: Ethical impact assessment, pedagogical fairness, socioeconomic accessibility of generative AI in education, and algorithmic bias framing are academic research and authorial responsibilities. They require contextual normative arguments, literature comparison, and student privacy policy synthesis that belong in the written dissertation rather than being performed by automated code agents.

### 2. Groq Production API Key Rotation
- Secrets lifecycle management and key rotation policies are deferred to production deployment infrastructure.

### 3. Local LLaMA Offline Lesson Generation Fallback
- Serving a local 70B parameter LLM via Ollama for full lesson synthesis offline requires dedicated high-end GPU hardware (VRAM $\ge 40$ GB) not assumed on demo machines. When Groq is unreachable, the system gracefully falls back to verified structured local concept notes.

### 4. Optional Hard Question Pool Top-Up
- The 24 concepts identified in `docs/POOL_STATUS.md` with Hard-tier deficits (e.g., `< 3` Hard questions) are sufficient for demonstration and core assessment. A targeted generation run can top them up post-viva if deeper Hard-tier question bank density is desired.
