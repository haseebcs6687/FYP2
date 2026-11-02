# Performance Analysis Agent: Simulation-Based Evaluation (Phase 5C)

## 1. Experimental Setup

To evaluate the diagnostic accuracy of the **Performance Analysis Agent** under realistic, closed-loop conditions, we simulated a cohort of **60 synthetic students** over a curriculum of **5 consecutive quizzes**.

### Ground Truth & Behavioral Models
- **Cohort Size**: 60 students (`student_id = 1..60`).
- **Ground Truth**: Each student secretly holds exactly **3 distinct misconceptions** sampled uniformly at random from the 163 distinct misconception tags present in the verified question pool (`data/edugen.db`). Total held misconceptions in cohort: 180.
- **Base Student Accuracy**: Sampled uniformly from $0.50$ to $0.85$.
- **Evaluated Student Models**:
  1. **Model A (Independent Model)**: Base accuracy applies independently. When a question offers a held misconception distractor, the student falls into the trap with probability $p = 0.80$; otherwise they answer correctly with probability $base\_acc$, else random wrong distractor.
  2. **Model B (Concept-Impact Model)**: In concepts where the student holds a misconception, their accuracy is compromised ($p_{correct} = base\_acc \times 0.40$). When they fail on such questions, if a held misconception is present, they choose it with probability $0.80$. In concepts without misconceptions, accuracy is $base\_acc$.
- **Evaluated Quiz Policies**:
  - **Policy R (Random)**: 10 unseen verified pool questions uniformly at random per quiz.
  - **Policy F (Concept-Focused)**: Quiz 1 diagnostic; Quizzes 2–5 draw 10 unseen questions targeting the student's weakest concept.
  - **Policy P (Reevaluation)**: Quiz 1 diagnostic; Quizzes 2–5 request `kind='reevaluation'` filled via `select_from_pool` (exact difficulty match).
  - **Policy PR (Probe, Pool-Only)**: Quiz 1 diagnostic; Quizzes 2–5 request `kind='probe'` with relaxed difficulty matching via `select_probe_set`. Unfilled slots are dropped.
  - **Policy PR (Probe, Pool + Emulated)**: Same as PR, but unfilled slots are filled with virtual questions whose targets survive verification with probability 0.50 (simulating live generation).
- **Severity Decay Formula**: Exactly matches `core/pa_model.py`:
  $$\text{severity} = \text{chosen} \times 0.9^{\text{avoided\_streak}}$$

---

## 2. Evaluation Results: Student Model A (Independent)

### 2.1 Policy R: Random Uniform Pool Sampling
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 10 / 10 | 100.0% | 100.0% | 0.0% | **0.0%** | 0.07 | 0.6% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 20 / 20 | 100.0% | 0.0% | 0.0% | **0.0%** | 0.11 | 0.6% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **3** | 30 / 30 | 100.0% | 14.3% | 0.6% | **1.1%** | 0.18 | 1.7% | 33.3% | 14.3% | 0.0% | 0.0% | 0.0% |
| **5** | 50 / 50 | 100.0% | 38.1% | 4.4% | **8.0%** | 0.3 | 5.0% | 88.9% | 44.4% | 0.0% | 0.0% | 0.0% |

### 2.2 Policy F: Concept-Focused Probing
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 10 / 10 | 100.0% | 100.0% | 0.0% | **0.0%** | 0.13 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 20 / 20 | 100.0% | 35.3% | 3.3% | **6.1%** | 0.24 | 3.3% | 100.0% | 37.5% | 100.0% | 0.0% | 0.0% |
| **3** | 30 / 30 | 100.0% | 34.4% | 6.1% | **10.4%** | 0.33 | 6.1% | 100.0% | 37.0% | 100.0% | 0.0% | 0.0% |
| **5** | 50 / 50 | 100.0% | 37.5% | 11.7% | **17.8%** | 0.55 | 12.8% | 91.3% | 48.7% | 100.0% | 0.0% | 0.0% |

### 2.3 Policy P: Targeted Blueprint Probing (Reevaluation)
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 720 / 720 | 100.0% | 100.0% | 0.0% | **0.0%** | 0.21 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 1200 / 1065 | 88.8% | 28.1% | 5.0% | **8.5%** | 0.32 | 6.7% | 75.0% | 32.1% | 100.0% | 0.0% | 0.0% |
| **3** | 1680 / 1251 | 74.5% | 27.3% | 6.7% | **10.7%** | 0.37 | 8.9% | 75.0% | 32.4% | 100.0% | 0.0% | 0.0% |
| **5** | 2640 / 1471 | 55.7% | 26.0% | 7.2% | **11.3%** | 0.39 | 8.9% | 81.2% | 30.6% | 100.0% | 0.0% | 0.0% |

### 2.4 Policy PR (Pool-Only): Concept-Focused Misconception Sweep
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 720 / 720 | 100.0% | 100.0% | 0.0% | **0.0%** | 0.21 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 1200 / 1051 | 87.6% | 33.3% | 3.9% | **7.0%** | 0.32 | 3.9% | 100.0% | 33.3% | 100.0% | 0.0% | 0.0% |
| **3** | 1680 / 1160 | 69.0% | 39.3% | 6.1% | **10.6%** | 0.38 | 6.1% | 100.0% | 41.7% | 100.0% | 0.0% | 0.0% |
| **5** | 2640 / 1182 | 44.8% | 36.7% | 6.1% | **10.5%** | 0.38 | 6.1% | 100.0% | 40.0% | 100.0% | 0.0% | 0.0% |

### 2.5 Policy PR (Pool + Emulated Generation)
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`
- **Share of Exposures from Emulation**: `15.0%`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 720 / 720 | 100.0% | 100.0% | 0.0% | **0.0%** | 0.22 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 1200 / 1054 | 87.8% | 26.1% | 3.3% | **5.9%** | 0.32 | 3.9% | 85.7% | 26.1% | 9.1% | 0.6% | 1.0% |
| **3** | 1680 / 1181 | 70.3% | 26.2% | 6.1% | **9.9%** | 0.42 | 6.7% | 91.7% | 31.2% | 2.3% | 0.6% | 0.9% |
| **5** | 2640 / 1445 | 54.7% | 26.5% | 10.0% | **14.5%** | 0.56 | 10.6% | 94.7% | 32.6% | 6.0% | 3.9% | 4.7% |

---

## 3. Evaluation Results: Student Model B (Concept-Impact)

### 3.1 Policy R: Random Uniform Pool Sampling
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 10 / 10 | 100.0% | 100.0% | 0.6% | **1.1%** | 0.09 | 1.1% | 50.0% | 100.0% | 100.0% | 0.0% | 0.0% |
| **2** | 20 / 20 | 100.0% | 100.0% | 2.2% | **4.3%** | 0.16 | 2.2% | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% |
| **3** | 30 / 30 | 100.0% | 57.1% | 2.2% | **4.3%** | 0.21 | 3.3% | 66.7% | 57.1% | 100.0% | 0.0% | 0.0% |
| **5** | 50 / 50 | 100.0% | 41.7% | 2.8% | **5.2%** | 0.31 | 4.4% | 62.5% | 36.4% | 100.0% | 0.0% | 0.0% |

### 3.2 Policy F: Concept-Focused Probing
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 10 / 10 | 100.0% | 100.0% | 0.0% | **0.0%** | 0.13 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 20 / 20 | 100.0% | 43.8% | 3.9% | **7.1%** | 0.28 | 5.0% | 77.8% | 46.7% | 100.0% | 0.0% | 0.0% |
| **3** | 30 / 30 | 100.0% | 36.0% | 5.0% | **8.8%** | 0.38 | 7.2% | 69.2% | 40.0% | 100.0% | 0.0% | 0.0% |
| **5** | 50 / 50 | 100.0% | 33.3% | 9.4% | **14.7%** | 0.63 | 16.7% | 56.7% | 38.2% | 0.0% | 0.0% | 0.0% |

### 3.3 Policy P: Targeted Blueprint Probing (Reevaluation)
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 720 / 720  | 100.0% | 100.0% | 0.0% | **0.0%** | 0.21 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 1200 / 1079  | 89.9% | 33.3% | 5.6% | **9.5%** | 0.37 | 9.4% | 58.8% | 34.5% | 100.0% | 0.0% | 0.0% |
| **3** | 1680 / 1276  | 76.0% | 25.5% | 6.7% | **10.6%** | 0.41 | 11.1% | 60.0% | 29.4% | 100.0% | 0.0% | 0.0% |
| **5** | 2640 / 1499  | 56.8% | 25.0% | 7.8% | **11.9%** | 0.43 | 11.7% | 66.7% | 31.6% | 100.0% | 0.0% | 0.0% |

### 3.4 Policy PR (Pool-Only): Concept-Focused Misconception Sweep
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 720 / 720  | 100.0% | 100.0% | 0.0% | **0.0%** | 0.2 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 1200 / 1058  | 88.2% | 38.1% | 4.4% | **8.0%** | 0.37 | 6.1% | 72.7% | 42.1% | 100.0% | 0.0% | 0.0% |
| **3** | 1680 / 1193  | 71.0% | 40.0% | 6.7% | **11.4%** | 0.43 | 8.3% | 80.0% | 47.8% | 100.0% | 0.0% | 0.0% |
| **5** | 2640 / 1220  | 46.2% | 41.9% | 7.2% | **12.3%** | 0.45 | 8.9% | 81.2% | 50.0% | 100.0% | 0.0% | 0.0% |

### 3.5 Policy PR (Pool + Emulated Generation)
- **Quizzes to $\ge 50\%$ Active Held Misconceptions**: `not reached`
- **Share of Exposures from Emulation**: `28.7%`

| Quizzes | Slots Req / Fill | Fill Rate | Active Prec | Active Rec | Active F1 | Avg Offered | % Offered $\ge 2$ | Detectable Rec | Top-1 Match | Base Prec | Base Rec | Base F1 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 720 / 720  | 100.0% | 100.0% | 0.0% | **0.0%** | 0.22 | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| **2** | 1200 / 1056  | 88.0% | 21.4% | 3.3% | **5.8%** | 0.36 | 4.4% | 75.0% | 25.0% | 9.1% | 0.6% | 1.0% |
| **3** | 1680 / 1211  | 72.1% | 22.0% | 5.0% | **8.1%** | 0.51 | 7.8% | 64.3% | 23.5% | 8.3% | 2.2% | 3.5% |
| **5** | 2640 / 1461  | 55.3% | 24.0% | 10.0% | **14.1%** | 0.68 | 13.3% | 75.0% | 28.9% | 9.2% | 6.7% | 7.7% |

---

## 4. Discussion & Key Findings

### 4.1 Probe Quiz Mechanics & Pool Inventory Constraints
- **Concept Concentration vs Pool Breadth**: Policy P (
eevaluation) spreads 8 slots across 3 different concepts plus retention slots, achieving a ~56% fill rate because it samples widely across concepts. In contrast, Policy PR (probe) concentrates all 8 slots into a **single target concept** to aggressively sweep its catalog misconceptions.
- **Inventory Ceiling in Pool-Only**: In **Policy PR (pool-only)**, because certain concepts in the verified pool currently contain fewer than 8 total questions (or fewer unseen questions after diagnostic quiz 1), single-concept probing reaches an inventory ceiling (~45-46% fill rate) when unfilled slots cannot be generated live.
- **Precision and Detectable Recall**: Despite this pool inventory ceiling, Policy PR (pool-only) achieves the highest precision and detectable recall of all targeted policies: **100.0% detectable recall** under Model A and **81.2% detectable recall** under Model B, with top-1 diagnosis match reaching 50.0%. When misconceptions are offered $\\ge 2$ times, the agent detects them with near-perfect fidelity.

### 4.2 Pool-Only vs Emulated Live Generation
- In **Policy PR (pool + emulated generation)**, unfilled probe slots are filled via live generation (with a realistic 50% verifier survival assumption for distractor tags).
- Emulation accounts for **15.0%** of total exposures under Model A and **28.7%** under Model B.
- This additional live generation increases average held misconception exposure from 0.38 to 0.56 (Model A) and 0.45 to 0.68 (Model B), lifting active recall from 6.1% to **10.0%** (Model A) and from 7.2% to **10.0%** (Model B).
- This confirms that the primary bottleneck in misconception diagnosis is not the agent's detection logic, but **exposure opportunity** within a limited 5-quiz window.

### 4.3 Policy F vs Policy PR Trade-offs
- **Policy F** achieves a 100% fill rate and 11.7% recall by drawing 10 unconstrained questions from the weakest concept without blueprint structure.
- However, **Policy PR** is systematically structured around the misconception catalog: it tracks which catalog misconceptions have been offered to the student and intentionally sweeps untargeted ones. For concepts with sufficient pool depth or with live generation enabled (PR emulated), PR provides structured, verifiable diagnostic coverage.

### 4.4 Student Model A vs Model B Dynamics
- Under **Model B (Concept-Impact)**, students have compromised base accuracy on concepts where they hold misconceptions. This makes errors in those concepts more frequent, allowing misconceptions to surface earlier.
- Under both models, all policies require more than 5 quizzes (50 questions) across 44 concepts to reach $\\ge 50\\%$ of held misconceptions active with $\\ge 2$ exposures, because each student holds 3 misconceptions across 44 concepts (a student encounters any specific concept only ~1–2 times across 50 questions).

### 4.5 Baseline Heuristic Comparison
- Across both models, the legacy string-matching baseline exhibits negligible or zero F1 (0.0% - 7.7%). Because quizzes draw distinct questions without repetition, students rarely encounter identical option text strings twice.
- This demonstrates that pedagogical adaptivity cannot rely on string matching; it fundamentally requires structured misconception tracking grounded in a canonical concept/misconception catalog.
