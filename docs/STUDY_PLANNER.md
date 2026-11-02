# Adaptive Content Agent: Study Planner Architecture & Evaluation (Phase 6)

## 1. Algorithmic Architecture (`core/study_planner.py`)

In Phase 6, the **Adaptive Content Agent** transitions from a greedy, single-step recommender (`decide()`) to a **graph-aware curriculum planner** that generates an end-to-end, prerequisite-closed, misconception-targeted study plan.

### Core Pipeline
1. **Seed Concept Discovery**: Gathers learner deficits from the Performance Analysis Agent report: weak topics (mastery < 40%), active misconceptions with unmastered concepts, retention review candidates, and theory-vs-tracing skill gaps.
2. **Prerequisite Closure**: Computes transitive prerequisite dependencies via `core.concepts.prerequisites_of(deep=True)`. Incorporates unmastered prerequisites (< 70% mastery) and unproven prerequisites (<= 2 edges away). Excludes mastered prerequisites (>= 70%).
3. **Multi-Factor Priority Scoring**:
   $$\text{Priority} = (100 - \text{mastery}) + 15 \times \min(\text{active\_severity}, 4) + 10 \times (\text{dependents}) + 8 \times [\text{due\_for\_review}]$$
4. **Topological Ordering (Kahn's Algorithm)**: Orders concepts such that every prerequisite precedes its dependents. Breaks ties by priority descending, followed by curriculum module order.
5. **Closure-Preserving Size Cap**: Default cap of 7 learning steps. If candidates exceed cap, defers lowest-priority non-prerequisites to `deferred`. Essential prerequisite closures are never broken.
6. **Calibrated Learning Steps**: Configures difficulty (`Easy` < 40, `Medium` 40-70, `Hard` >= 70), lesson style (`simplified` < 40, `detailed` >= 40), and estimated duration ($5 + 3 \times \text{focus\_items}$ min, capped at 20m).
7. **Closing Verification Quizzes**: Appends one `probe` quiz step sweeping the highest-severity misconception and one final `reevaluation` quiz step covering all plan concepts.
8. **Deterministic Prompt Generation**: Formats teach prompts embedding concept title, student evidence, misconception pairs (`wrong_belief -> correct_idea`), skill gap instructions, and student custom notes.
9. **Formal Coverage Checker (`check_coverage`)**: Validates (a) order validity, (b) weak concept coverage, (c) active misconception coverage, (d) acyclicity & uniqueness, and (e) closing quiz presence. Skipped steps trigger explicit uncovered warnings.

---

## 2. Property Evaluation Results (300 Synthetic Profiles)

To rigorously test mathematical guarantees, we ran a Monte Carlo evaluation across **300 random student profiles** with diverse mastery distributions, prerequisite chains, and active misconception counts (seed 42).

| Evaluation Metric | Target Property | Measured Result | Status |
| :--- | :--- | :---: | :---: |
| **Topological Order Validity** | Every prerequisite precedes dependents | **100.0%** | PASS |
| **Prerequisite Closure** | All required prerequisites scheduled or mastered | **100.0%** | PASS |
| **Size Cap Compliance** | $\le 7$ learning steps unless closure requires more | **100.0%** | PASS |
| **Checker False Negatives** | 0 undetected planted violations (1 per profile) | **0 (0.0%)** | PASS |
| **Average Plan Length** | Balanced learning + verification | **8.51 steps** | PASS |
| **Average Learning Steps** | Focused remediation scope | **6.51 steps** | PASS |
| **Average Deferred Items** | Preserved for subsequent study cycles | **2.23 concepts** | PASS |

---

## 3. Comparative Benchmark: Single-Step `decide()` vs. Study Plan

The legacy `decide()` engine evaluates one concept at a time without curriculum visibility. The Phase 6 study planner schedules an entire personalized learning path:

| Pedagogical Metric | Legacy Single-Step `decide()` | Phase 6 Multi-Step Study Plan | Gain Factor |
| :--- | :---: | :---: | :---: |
| **Weak Concepts Addressed per Request** | 1.00 concepts | **3.45 concepts** | **3.5x broader coverage** |
| **Active Misconceptions Scheduled** | 0.34 misconceptions | **2.00 misconceptions** | **5.9x higher diagnostic capture** |
| **Prerequisite Sequencing** | Remediates single parent on R2 | Full topological DAG closure | **Complete learning path** |
| **Verification Loop** | None | Probe + Reevaluation quiz closing steps | **Built-in verification** |
| **Learner Control** | Accept / Override | Editable custom notes + skip controls | **Transparent agency** |
