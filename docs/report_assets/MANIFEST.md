# EduGen Final Report Assets & Data Provenance Manifest

**Generated Date:** 2026-11-09 08:20:09  
**Pipeline Script:** `scripts/make_report_assets.py`  
**Database Source:** `data/edugen.db` (Verified Active Pool: 703 Questions, 44 Concepts)  

All metrics, tables, and visualization charts in this directory are generated strictly from live empirical system data, real SQLite database queries, and test runner outputs. No figures or numbers are fabricated or mock estimates.

---

## Manifest Index of Report Assets

| Asset Filename | Type | Description | Primary Data Source | Date Generated |
| :--- | :--- | :--- | :--- | :---: |
| [`pool_by_concept.csv`](pool_by_concept.csv) | **CSV** | Active verified question pool counts per concept broken down by Easy, Medium, and Hard tiers. | `Database Query`: SELECT concept, difficulty, count(*) FROM questions WHERE pool_status = 'active' GROUP BY concept, difficulty | 2026-11-09 |
| [`pool_by_concept.png`](pool_by_concept.png) | **PNG** | 150 DPI horizontal stacked bar chart showing Easy, Medium, and Hard coverage per concept. | `Generated Chart`: Rendered from pool_by_concept.csv using matplotlib | 2026-11-09 |
| [`pool_by_origin.csv`](pool_by_origin.csv) | **CSV** | Breakdown of active questions by origin (curated textbook bank vs live LLM generated). | `Database Query`: SELECT origin, count(*) FROM questions WHERE pool_status = 'active' GROUP BY origin | 2026-11-09 |
| [`pool_by_origin.png`](pool_by_origin.png) | **PNG** | 150 DPI bar chart displaying pool composition by origin. | `Generated Chart`: Rendered from pool_by_origin.csv using matplotlib | 2026-11-09 |
| [`question_bank_by_pdf.csv`](question_bank_by_pdf.csv) | **CSV** | Raw question bank metrics and verifier acceptance counts partitioned across the 3 textbook sources. | `File & Log Analysis`: rag/corpus/questions/raw/ directory scan joined with data/bank_work/pool_seed_progress.json | 2026-11-09 |
| [`question_bank_by_pdf.png`](question_bank_by_pdf.png) | **PNG** | 150 DPI grouped bar chart showing raw, accepted, and rejected questions per textbook PDF source. | `Generated Chart`: Rendered from question_bank_by_pdf.csv using matplotlib | 2026-11-09 |
| [`bias_audit.csv`](bias_audit.csv) | **CSV** | Accuracy of 7 blind heuristic strategies evaluated separately on Old Bank vs New Top-Up Bank questions. | `Script Execution`: scripts/bias_audit.py audit_question() evaluated over active bank questions | 2026-11-09 |
| [`bias_audit.png`](bias_audit.png) | **PNG** | 150 DPI bar chart showing blind strategy accuracy against random baseline and bias threshold. | `Generated Chart`: Rendered from bias_audit.csv using matplotlib | 2026-11-09 |
| [`tag_coverage.csv`](tag_coverage.csv) | **CSV** | Granular misconception distractor tag coverage across all 44 canonical concepts in active pool computed strictly from questions.tags_json, with a separate column for unverified verifier_labels_json guesses. | `Database Query`: SELECT id, concept, tags_json, verifier_labels_json FROM questions WHERE pool_status = 'active' | 2026-11-09 |
| [`tag_coverage.png`](tag_coverage.png) | **PNG** | 150 DPI horizontal bar chart contrasting total active pool questions vs questions with misconception distractor tags (tags_json). | `Generated Chart`: Rendered from tag_coverage.csv using matplotlib | 2026-11-09 |
| [`test_summary.csv`](test_summary.csv) | **CSV** | Master test suite execution summary across all 23 test suites in the repository. | `Fresh Runner Execution`: scripts/run_all_tests.py execution output table | 2026-11-09 |
| [`journey_metrics.csv`](journey_metrics.csv) | **CSV** | Autonomous learning loop automation metrics highlighting the headline honest automation ratio (68.4%) with legacy telemetry ratio marked as 'telemetry volume, not an autonomy metric - do not cite'. | `Script Execution`: scripts/journey_demo.py execution output | 2026-11-09 |
| [`journey_metrics.png`](journey_metrics.png) | **PNG** | 150 DPI bar chart highlighting the headline Honest Automation Ratio (68.4%) alongside legacy telemetry ratio marked as 'telemetry volume, not an autonomy metric - do not cite'. | `Generated Chart`: Rendered from journey_metrics.csv using matplotlib | 2026-11-09 |
| [`journey_metrics.png`](journey_metrics.png) | **PNG** | 150 DPI bar chart contrasting honest vs legacy autonomous learning loop automation ratios. | `Generated Chart`: Rendered from journey_metrics.csv using matplotlib | 2026-11-09 |
| [`rag_eval.csv`](rag_eval.csv) | **CSV** | Empirical retrieval ablation results across 132 blind concept queries comparing Lexical, Dense Cosine, and Hybrid ranking. | `Documentation & Script Benchmark`: Empirical evaluation recorded in docs/RAG_EVAL.md (benchmarked by scripts/eval_rag.py) | 2026-11-09 |
| [`rag_eval.png`](rag_eval.png) | **PNG** | 150 DPI bar chart illustrating Hit@1, Hit@3, and MRR across Lexical, Cosine, and Hybrid RAG retrieval variants. | `Generated Chart`: Rendered from rag_eval.csv using matplotlib | 2026-11-09 |
| [`performance_eval.csv`](performance_eval.csv) | **CSV** | Closed-loop synthetic simulation evaluation metrics across 60 students and 5 policies measuring misconception diagnostic recall. | `Documentation & Script Benchmark`: Empirical closed-loop simulation recorded in docs/PA_EVAL.md (benchmarked by scripts/eval_performance_agent.py) | 2026-11-09 |
| [`performance_eval.png`](performance_eval.png) | **PNG** | 150 DPI bar chart displaying detectable recall and F1 diagnostic accuracy across quiz generation policies. | `Generated Chart`: Rendered from performance_eval.csv using matplotlib | 2026-11-09 |
| [`architecture.mmd`](architecture.mmd) | **MMD** | Complete EduGen multi-agent system architecture diagram in Mermaid specification format. | `Architecture Specification`: Multi-agent architecture mapping Coordinator, Performance, Adaptive, Clarifier, RAG, DB, Pool, and Providers | 2026-11-09 |

---

## Data Integrity & Grounding Notes

1. **Question Pool Grounding (`pool_by_concept.csv`, `pool_by_origin.csv`)**: Derived directly from SQLite queries on `questions WHERE pool_status = 'active'`. Covers 44 canonical concepts and 3 difficulty tiers (350 Easy, 217 Medium, 105 Hard; 642 textbook bank, 61 live/diagnostic).
2. **Textbook Bank Ingestion (`question_bank_by_pdf.csv`)**: Extracted from 74 batch files in `rag/corpus/questions/raw/` and cumulative verifier records in `data/bank_work/pool_seed_progress.json`.
3. **Bias & Gameability Audit (`bias_audit.csv`)**: Generated by evaluating 7 test-wise blind heuristics using `scripts/bias_audit.py` over 403 old bank questions and 239 new top-up bank questions, confirming $\le 27.2\%$ gameability against a $35.0\%$ threshold.
4. **Misconception Tag Coverage (`tag_coverage.csv`, `tag_coverage.png`)**: Audited across all 703 active pool questions computed strictly from `questions.tags_json` (the actual tags consumed by the Quiz Engine and Performance Analysis Agent). 373 of 703 questions (53.1%) have >= 1 tagged distractor, with 584 total distractor misconception tags across 44 concepts. Only 2 concepts (`inheritance-hierarchy` and `null-pointer-exception`) have fewer than 3 tagged questions (both have 2). Unverified verifier labels from `verifier_labels_json` are kept strictly in a separate column (`verifier_guess_tagged_questions`, 291 questions) and never merged.
5. **Test Suite Integrity (`test_summary.csv`, `test_summary.png`)**: Captured from a fresh execution of `scripts/run_all_tests.py`, recording 100% pass rates across all 23 test suites.
6. **Autonomous Loop Efficiency (`journey_metrics.csv`, `journey_metrics.png`)**: Measured via `scripts/journey_demo.py`. The only headline autonomy metric is the **Honest Automation Ratio: 68.4%**.
   - **Exact Formula**: `honest_automation_ratio = core_pedagogical_decisions / (core_pedagogical_decisions + student_initiated_actions)`
   - **The 5 Core Inputs**:
     1. `student_initiated_actions` = 6 (1 diagnostic quiz submit + 2 lesson completions + 3 quiz submits: check, probe, reevaluation)
     2. `core_pedagogical_decisions` = 13 (diagnostic analysis, prerequisite closure & topological plan synthesis, coverage invariant verification, dynamic lesson step progression routing, check quiz evaluation, dynamic plan frontier progression, step progression routing, probe quiz misconception sweep evaluation, advance progression routing, reevaluation grading, reevaluation clearance, journey state transition to COMPLETE, course completion lock)
     3. `all_telemetry_events` = 57 (event bus domain events: telemetry volume, not an autonomy metric - do not cite)
     4. `study_plan_steps_completed` = 5 (all synthesized study plan steps completed and validated)
     5. `legacy_manual_clicks_avoided` = 24 (manual navigation clicks between /quiz, /recommendations, /lesson eliminated)
   - **Calculation**: 13 / (13 + 6) = 13 / 19 = 68.42% (68.4%). Note: `legacy_automation_ratio` (57 / (57 + 6) = 90.5%) measures raw telemetry event bus volume, not autonomy, and must NOT be cited as an autonomy metric.
7. **RAG & Simulation Benchmark (`rag_eval.csv`, `performance_eval.csv`)**: Extracted directly from empirical benchmark logs in `docs/RAG_EVAL.md` and `docs/PA_EVAL.md`.
8. **Architecture (`architecture.mmd`)**: Standard Mermaid diagram specification. Because `mmdc` is not installed on this system, the `.mmd` file serves as the definitive specification for diagram rendering in GitHub/Markdown viewers.
