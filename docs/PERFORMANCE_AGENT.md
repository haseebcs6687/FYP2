# EduGen Performance Analysis Agent Architecture (Phase 5)

## 1. Role & Responsibility

The **Performance Analysis Agent** (`agents/performance_analysis_agent.py`) is the cognitive diagnostic engine of the EduGen multi-agent system.
- **Single Responsibility Principle**: Measure **WHAT** the student knows, which specific misconceptions they exhibit, and where their skill gaps lie.
- **Strict Boundary**: The agent **never decides what to teach or which action to take**—that responsibility belongs entirely to the Adaptive Content Agent.
- **Execution Model**: Purely deterministic, statistical, and graph-based. **No external LLM calls are made** in this agent.

---

## 2. Core Diagnostic Models (`core/pa_model.py`)

### 2.1 Bayesian Knowledge Tracing (BKT)
Concept mastery is estimated using standard Bayesian Knowledge Tracing grounded in cognitive tutoring literature (*Corbett & Anderson, 1995*) extended with item-difficulty parameterization (*Pardos & Heffernan, 2011*).

#### Parameters
- Prior Probability ($P_{init}$): `0.25`
- Transition Probability ($P_{learn}$): `0.15`
- Baseline Guess ($P_{guess}$): `0.25` (4-option multiple choice)
- Item Difficulty Parameterization:
  - **Easy**: $P_{slip} = 0.05$, $P_{guess} = 0.25$
  - **Medium**: $P_{slip} = 0.10$, $P_{guess} = 0.20$
  - **Hard**: $P_{slip} = 0.15$, $P_{guess} = 0.15$

#### Update Dynamics
For prior probability $P = P(L_{t-1})$:
1. **Posterior Belief Given Observation**:
   $$\text{If correct } (obs=1): \quad P(L_t | obs=1) = \frac{P \cdot (1 - P_{slip})}{P \cdot (1 - P_{slip}) + (1 - P) \cdot P_{guess}}$$
   $$\text{If incorrect } (obs=0): \quad P(L_t | obs=0) = \frac{P \cdot P_{slip}}{P \cdot P_{slip} + (1 - P) \cdot (1 - P_{guess})}$$

2. **Learning Transition Between Opportunities**:
   $$P(L_{t+1}) = P(L_t | obs) + (1 - P(L_t | obs)) \cdot P_{learn}$$

3. **Mastery Score, Display Clamping & Confidence**:
   - Underlying probabilistic belief is preserved raw as `p_known` $= P(L_t | obs) \in [0.0, 1.0]$.
   - Displayed concept and module mastery is clamped:
     $$\text{Mastery} = \text{clamp}(100 \times P(L_t | obs), 2.0, 98.0) \in [2.0, 98.0]$$
     This prevents misleading 0.0% or 100.0% saturation (e.g. after consecutive correct streaks) while ensuring adaptive rule thresholds (`WEAK_THRESHOLD = 50.0`, `STRONG_THRESHOLD = 80.0`) remain fully responsive.
   - Confidence levels: `low` (< 3 attempts), `medium` (3–5 attempts), `high` ($\ge 6$ attempts).

#### Monotonicity Properties
- A correct answer strictly increases $P(known)$.
- An incorrect answer strictly decreases $P(known)$.
- Correctly solving a **Hard** question yields higher posterior mastery than solving an **Easy** question ($70.6\%$ vs $62.5\%$).
- Failing a **Hard** question penalizes the student less than failing an **Easy** question.

---

### 2.2 Misconception Lifecycle Tracker
Tracks every misconception offered to the student in chronological order:
- `chosen`: Number of times the student selected the tagged distractor.
- `offered`: Total opportunities where this distractor was presented among options.
- `avoided_streak`: Consecutive opportunities where the distractor was offered and **NOT** chosen since it was last selected.

#### State Transitions
```
              ┌─────────────────────────┐
              │  Offered to Student     │
              └────────────┬────────────┘
                           │
             chosen == 1   ▼
        ┌──────────────────────────────────┐
        │  'suspected' (avoided_streak < 2)│
        └───────┬───────────────────┬──────┘
                │                   │
    chosen >= 2 │                   │ avoided_streak >= 2
                ▼                   ▼
    ┌──────────────────────┐  ┌───────────────────────┐
    │ 'active'             │  │ 'resolved'            │
    │ (avoided_streak < 2) │  │ (avoided_streak >= 2) │
    └───────────┬──────────┘  └───────────────────────┘
                │ avoided_streak >= 2
                ▼
    ┌──────────────────────┐
    │ 'resolved'           │
    └──────────────────────┘
```

#### Severity Scoring & Evidence
$$\text{severity} = \text{chosen} \times 0.9^{\text{avoided\_streak}}$$
- Higher frequency increases severity.
- Each consecutive time a student avoids a previously chosen trap decays its severity by $10\%$.
- Enriched with catalog titles, wrong beliefs, correct ideas, and human-readable evidence sentences:
  > *"Chose this option in 3 of the 4 questions where it appeared (most recently in current quiz)."*

---

### 2.3 Facet Mapping
Measures error rates per concept and facet:
- `offered`: Questions presented for that facet.
- `chosen`: Questions answered incorrectly in that facet.
- `error_rate`: $\text{chosen} / \text{offered}$.
- `weak`: Flagged when $\text{chosen} \ge 2$ and $\text{error\_rate} \ge 0.50$.

---

### 2.4 Question Type Skill Profiling
Measures accuracy across question types (`concept`, `code_output`, `bug_find`):
- Overall and per-module breakdown.
- **Skill Gap Detection**: Fires when accuracy on one question type is $\ge 25$ percentage points below another (minimum 4 attempts each):
  > *"Knows the theory (concept: 100.0%) but fails code tracing (code_output: 25.0%)"*

---

## 3. Data Schema & Persistence (Migration 5)

### Database Changes
1. `question_attempts`:
   - `offered_misconceptions` TEXT (JSON list of non-null misconception IDs among options)
   - `qtype` TEXT (`concept`, `code_output`, `bug_find`)
   - `facet` TEXT
   - `difficulty` TEXT
2. `student_misconceptions` table:
   - `(student_id, misconception_id, concept, facet, chosen, offered, avoided_streak, status, first_seen, last_seen, updated_at)`
   - Primary key: `(student_id, misconception_id)`
   - Index on `(student_id, status)`

---

## 4. Report Output Contract (Backward Compatible)

The agent produces a comprehensive dictionary maintaining 100% backward compatibility with all FYP-1 and FYP-2 keys while introducing structured Phase 5 keys:

```json
{
  "student_id": 1,
  "generated_at": "2026-11-02 04:00:00",
  "overall_performance": 62.5,
  "total_quizzes_taken": 3,
  "total_questions_attempted": 25,
  "total_questions_correct": 15,
  "weak_topics": [...],
  "moderate_topics": [...],
  "strong_topics": [...],
  "insufficient_data": [...],
  "root_causes": [...],
  "due_for_review": [...],
  "module_breakdown": [...],
  "concept_stats": {
    "method-overriding": {
      "concept_tag": "method-overriding",
      "attempts": 10,
      "correct": 3,
      "accuracy": 30.0,
      "mastery": 28.5,
      "p_known": 0.2854,
      "ewma_accuracy": 34.2,
      "confidence": "high",
      "trend": "improving",
      "facets": {...},
      "untagged_errors": 2,
      "active_misconceptions": [...]
    }
  },
  "misconceptions": {
    "active": [...],
    "suspected": [...],
    "resolved": [...]
  },
  "facet_map": {...},
  "skill_profile": {
    "overall": {...},
    "by_module": {...},
    "skill_gaps": [...]
  },
  "recommendation_input": {
    "primary_weak_topic": "method-overriding",
    "weak_topic_count": 1,
    "overall_performance": 62.5,
    "root_causes": [...],
    "due_for_review": [...],
    "trend_summary": {...},
    "concepts_seen": 4,
    "active_misconceptions": ["method-overriding/static-methods-override"],
    "weak_facets": [...],
    "skill_gaps": [...]
  }
}
```

---

## 5. Verification & Tests

- **Unit & Integration Suite**: `scripts/test_performance_agent.py` (16 tests, 100% passing).
- **Interactive Profile Demo**: `scripts/pa_demo.py` demonstrating 4 distinct profiles (persistent misconception, remediated misconception, theory vs tracing gap, random guesser).
- **Simulation Evaluation**: `scripts/eval_performance_agent.py` evaluating 60 students over 5 quizzes with documentation in `docs/PA_EVAL.md`.

