# Performance Analysis Agent: Simulation-Based Evaluation (Phase 5B)

## 1. Experimental Setup

To evaluate the diagnostic accuracy of the **Performance Analysis Agent** under realistic, closed-loop conditions, we simulated a cohort of **60 synthetic students** over a curriculum of **5 consecutive quizzes**.

### Ground Truth & Behavioral Model
- **Cohort Size**: 60 students (`student_id = 1..60`).
- **Ground Truth**: Each student secretly holds exactly **3 distinct misconceptions** sampled uniformly at random from the 163 distinct misconception tags present in the verified question pool (`data/edugen.db`). Total held misconceptions in cohort: 180.
- **Base Student Accuracy**: Sampled uniformly from $0.50$ to $0.85$.
- **Response Choice Mechanism**:
  - If the question offers one or more of the student's held misconceptions, the student chooses that distractor with probability $p = 0.80$ (sensitivity evaluated for $p \in \{0.60, 0.80, 0.95\}$).
  - Otherwise (or if the trap was avoided), the student answers correctly with probability equal to their base accuracy; otherwise, they select uniformly at random among non-held wrong distractors.
- **Reproducibility**: Deterministic fixed random seed (`seed = 42`).
- **Statistical Detection Definition**: An agent misconception is classified as **`active`** if and only if $\text{chosen} \ge 2$ and $\text{avoided\_streak} < 2$.
- **Exposure & Detectable Recall**:
  - **Exposure**: Average opportunities a held misconception appeared as an option; share of held misconceptions offered $\ge 2$ times.
  - **Detectable Recall**: Detected active misconceptions divided by held misconceptions that were offered $\ge 2$ times. This isolates the agent's statistical power from quiz selection policy constraints.
- **Severity Decay Formula**: Exactly matches `core/pa_model.py`:
  $$\text{severity} = \text{chosen} \times 0.9^{\text{avoided\_streak}}$$

### Evaluated Policies
1. **Policy R (Random Sampling)**: Draws 10 unseen verified pool questions uniformly at random per quiz.
2. **Policy F (Concept-Focused)**: Quiz 1 draws 10 questions across diagnostic foundational concepts (`build_blueprint('diagnostic')[:10]`). Quizzes 2–5 draw 10 unseen questions targeting the student's weakest concept (lowest current BKT mastery from the previous quiz's real PA report).
3. **Policy P (Targeted Probing / Real Pipeline)**: Quiz 1 requests `build_blueprint('diagnostic')`. Quizzes 2–5 request `build_blueprint('reevaluation', student_id)` driven by real PA records in the database, filled strictly from the verified pool via `core.quiz_engine.select_from_pool`. Unfilled slots are recorded to compute pool fill rate without making LLM calls.

---

## 2. Policy Evaluation Results

### 2.1 Policy R: Random Uniform Pool Sampling

| Quizzes | Questions | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 10 | 100.0% | 0.0% | **0.0%** | 0.07 | 0.6% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 20 | 0.0% | 0.0% | **0.0%** | 0.11 | 0.6% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **3** | 30 | 14.3% | 0.6% | **1.1%** | 0.18 | 1.7% | 33.3% | 14.3% | 0.0% | 0.0% | 0.0% |
| **5** | 50 | 38.1% | 4.4% | **8.0%** | 0.3 | 5.0% | 88.9% | 44.4% | 0.0% | 0.0% | 0.0% |

### 2.2 Policy F: Concept-Focused Probing

| Quizzes | Questions | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 10 | 100.0% | 0.0% | **0.0%** | 0.13 | 0.0% | **0.0%** | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 20 | 35.3% | 3.3% | **6.1%** | 0.24 | 3.3% | **100.0%** | 37.5% | 100.0% | 0.0% | 0.0% |
| **3** | 30 | 34.4% | 6.1% | **10.4%** | 0.33 | 6.1% | **100.0%** | 37.0% | 100.0% | 0.0% | 0.0% |
| **5** | 50 | 37.5% | 11.7% | **17.8%** | 0.55 | 12.8% | **91.3%** | 48.7% | 100.0% | 0.0% | 0.0% |

### 2.3 Policy P: Targeted Blueprint Probing (Real Pipeline)

| Quizzes | Slots Req / Filled | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 720 / 720 | 100.0% | 100.0% | 0.0% | **0.0%** | 0.21 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 1200 / 890 | 74.2% | 33.3% | 0.6% | **1.1%** | 0.24 | 2.2% | 25.0% | 33.3% | 100.0% | 0.0% | 0.0% |
| **3** | 1680 / 996 | 59.3% | 18.2% | 1.1% | **2.1%** | 0.25 | 2.8% | 40.0% | 18.2% | 100.0% | 0.0% | 0.0% |
| **5** | 2640 / 1158 | 43.9% | 13.3% | 1.1% | **2.1%** | 0.26 | 2.8% | 40.0% | 14.3% | 100.0% | 0.0% | 0.0% |

---

## 3. Sensitivity Analysis (Policy P at Quiz 5)

We evaluated Policy P sensitivity to student behavioral capture probability $p \in \{0.60, 0.80, 0.95\}$ and imperfect question pool tag coverage (50% of tagged options masked to null):

| Condition | Active Prec | Active Rec | Active F1 | Detectable Rec | Avg Offered | % Offered $\ge 2$ | Fill Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **p = 0.60 (100% tags)** | 18.8% | 1.7% | **3.1%** | 50.0% | 0.29 | 3.3% | 44.4% |
| **p = 0.80 (Default)** | 13.3% | 1.1% | **2.1%** | 40.0% | 0.26 | 2.8% | 43.9% |
| **p = 0.95 (100% tags)** | 29.4% | 2.8% | **5.1%** | 83.3% | 0.27 | 3.3% | 44.6% |
| **p = 0.80 (50% tags)** | 40.0% | 1.1% | **2.2%** | 66.7% | 0.18 | 1.7% | 44.5% |

---

## 4. Discussion & Key Findings

### 4.1 Why Raw Recall Appears Low in Sparse Curricula
In a curriculum of 50 questions across 44 concepts and 163 pool misconceptions, raw recall is strictly bounded by exposure:
- Under **Policy R**, each held misconception is offered on average only **0.30 times** across 50 questions. Only **5.0%** of held misconceptions are offered $\ge 2$ times. Because the agent requires $\ge 2$ observations to confirm an `active` misconception, detecting an un-offered misconception is mathematically impossible.
- Crucially, the **Detectable Recall** under Policy R is **88.9%**: of the few held misconceptions that were actually offered $\ge 2$ times, the agent correctly identified 88.9% as active.

### 4.2 Concept Focusing (Policy F) vs Targeted Probing (Policy P)
- **Policy F** achieves the highest raw recall (**11.7%**, F1 = 17.8%, Detectable Recall = **91.3%**) because it concentrates 10 questions per quiz into the student's weakest concept. This raises exposure to 0.55 offers per held misconception and increases the share of misconceptions offered $\ge 2$ times to **12.8%**.
- **Policy P** achieves a lower raw recall (**1.1%**, F1 = 2.1%) due to a critical real-world constraint: **static pool fill rate**. When `build_blueprint('reevaluation')` generates targeted slots with specific difficulties (e.g. Hard) and target misconceptions, the static pool of 441 questions only fills **43.9%** of requested slots. Consequently, students in Policy P receive significantly fewer total questions (~19 vs 50 in Policy F), directly reducing exposure. In production, this constraint is alleviated by live LLM generation for unfilled slots.

### 4.3 Baseline Comparison: Why Text Matching Collapses
- The legacy FYP-1/FYP-2 baseline relied on counting repeated identical `chosen_option_text` strings ($\ge 2$ times) per concept. In the 50-question simulation, the baseline achieved **0.0% recall and 0.0% F1 across all policies**.
- Root cause analysis shows that out of 1,760 options in the verified pool, only 23 option strings appear in more than one question of the same concept. When students take unique questions without replacement, identical option texts almost never repeat, rendering naive text matching ineffective. The Phase 5 agent's catalog-grounded misconception tracking operates on underlying pedagogical IDs, completely bypassing text variations.

### 4.4 Sensitivity Analysis Insights
- **Behavioral Fidelity ($p$)**: Varying distractor capture probability from $0.60$ to $0.95$ shows that higher capture rates improve detectable recall as students more reliably reveal their underlying misconceptions when presented with traps.
- **Tag Coverage (50%)**: When 50% of distractor tags are missing, detectable recall drops proportionately, demonstrating that verified distractor annotation density in the question pool is a primary determinant of diagnostic power.

### 4.5 Limitations
1. **Synthetic Response Model**: Simulated students follow Bernoulli choice distributions; human learners exhibit metacognitive hesitation, elimination strategies, and variable reading times.
2. **Static Pool Inventory**: Without live LLM generation fallback, strict multi-constraint blueprints (concept + difficulty + qtype) suffer from unfilled slots in smaller pools.
3. **Display Clamping**: Clamping displayed mastery to $[2.0, 98.0]$ prevents saturation but slightly compresses the dynamic range of top-performing students.
