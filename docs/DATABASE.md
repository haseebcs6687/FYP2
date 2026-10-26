# Database Architecture & Schema Reference — EduGen (FYP-2)

## Architectural Principle: Database vs. RAG Knowledge Base

> **Core Rule:** The relational database stores student state, generated questions, and multi-agent system evidence only. Book text, curriculum concept notes, and rendered lesson text belong strictly to the RAG knowledge base files (`rag/corpus/` and `data/rag_index/`).

| Data Type | Storage Location | Rationale |
| :--- | :--- | :--- |
| **Course Texts / Textbook Passages** | RAG File Index (`data/rag_index/`) | High-dimensional embeddings, BM25 indices, chunk boundaries. |
| **Generated Questions & Options** | `questions` table | Deduplication via SHA-256 text hashes, quality verification, item analysis. |
| **Student Performance & Mastery** | `concept_mastery`, `mastery_history`, `quiz_results` | Relational tracking, EWMA temporal progression, audit trails. |
| **Agent Execution & Retrieval Evidence** | `llm_calls`, `rag_retrievals`, `agent_events` | Granular telemetry and observability without bloating student logs. |

---

## Connection Configuration & Pragmas

SQLite connections in `core/db.py` enforce these settings upon every connection:
- `PRAGMA foreign_keys = ON;` — Ensures relational integrity across user, session, and question attempts.
- `PRAGMA journal_mode = WAL;` — Write-Ahead Logging allows concurrent readers alongside writers, avoiding lockups during agent execution.
- `PRAGMA busy_timeout = 5000;` — Waits up to 5 seconds if another transaction is writing before returning a busy error.

---

## Migrations & Backups

Forward migrations are managed by `core/migrations.py`:
- Tracked in `schema_migrations(version, name, applied_at)`.
- Each migration runs inside an isolated transaction.
- **Automated Backup:** Before applying any pending migration to an existing database file, a copy is automatically created in `data/backups/edugen_<timestamp>.db`. The system retains the 5 most recent backups and automatically prunes older ones.

---

## Schema Reference

### 1. System & Migrations
- **`schema_migrations`**: Tracks applied database versions and migration names.

### 2. Identity & Students
- **`users`**: Authentication credentials, secure password hashes, and `last_login_at` timestamp.
- **`students`**: Pedagogical profile linked to `users.id`, tracking preferred `lesson_style` and `total_study_seconds`.

### 3. Quiz Sessions & Assessment
- **`quiz_sessions`**: Ephemeral server-side storage of newly generated quizzes with unrevealed answers. Enables server-side grading without exposing solutions to the client.
- **`quiz_results`**: Graded quiz submissions detailing total score, difficulty, targeted concept, duration in ms, and attempt ordinal.
- **`question_attempts`**: Individual student answers per question, concept tags, accuracy, response time, and selected distractor text.

### 4. Question Bank Repository & Item Analysis
- **`questions`**: Canonical repository of generated questions. Deduplicated using SHA-256 `text_hash`. Tracks question type (`concept`, `code_output`, `bug_find`), difficulty, options JSON, verification status, and serving statistics (`times_served`, `times_correct`).
- **`student_question_history`**: Audit log linking individual students to questions they have tackled across quizzes, tracking question-level correctness and elapsed time.

### 5. Concept Mastery & Longitudinal Progress
- **`concept_mastery`**: Current mastery status per student per concept (composite primary key `student_id, concept`). Maintains EWMA recency-weighted mastery score, total attempts, correct count, trend (`improving`, `declining`, `stable`), and `last_seen` timestamp.
- **`mastery_history`**: Append-only longitudinal snapshots of mastery scores recorded after every quiz submission.

### 6. Adaptivity & Study Planning
- **`recommendations`**: Audit trail of every Adaptive Content Agent decision (rule fired, recommended concept, target difficulty, pedagogy reasoning, and student acceptance/override).
- **`lesson_views`**: Log of lessons viewed by students, providing an adaptivity signal to distinguish unread concepts from struggled ones.
- **`study_plans`**: Multi-step learning paths generated for students, recording target objectives and status (`active`, `completed`, `superseded`).
- **`study_plan_steps`**: Individual ordered steps within a study plan (position, concept, difficulty, step kind: `prerequisite`, `weak`, `review`, `advance`).

### 7. Multi-Agent Observability & Telemetry
- **`pipeline_runs`**: Orchestrated coordinator pipeline executions, tracking execution trigger and duration.
- **`agent_events`**: Granular inter-agent communication and diagnostic event stream (agent, action, level, input payload, output payload, execution duration).
- **`rag_retrievals`**: Telemetry for RAG retrievals against the knowledge base. Stores query, embedder, and top chunk IDs with ranking scores (`cosine`, `lexical`, `tag_score`, `final`). Passages and book text are never copied here.
- **`llm_calls`**: Direct telemetry for external LLM invocations (model, agent, purpose, latency in ms, token usage, success indicator, and error message).

### 8. Feedback
- **`feedback`**: Student ratings and qualitative remarks on specific lessons or generated questions.
