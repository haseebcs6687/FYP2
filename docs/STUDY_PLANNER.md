# Adaptive Content Agent: Study Planner Architecture & Evaluation (Phase 6B)

## 1. Algorithmic Architecture (`core/study_planner.py`)

In Phase 6, the **Adaptive Content Agent** transitions from a greedy, single-step recommender (`decide()`) to a **graph-aware curriculum planner** that generates an end-to-end, prerequisite-closed, misconception-targeted study plan.

### Step Kinds Taxonomy
The study planner produces two distinct categories of steps:
- **Lesson Kinds**:
  - `weak`: Targeted remediation for concepts with low mastery (< 40%). Configured with simplified or detailed style, misconception contrasts, and student notes.
  - `prerequisite`: Remediation for unmastered prerequisites (< 70% mastery) where attempt history exists.
  - `review`: Retention reinforcement for previously mastered concepts due for decay review.
  - `advance`: Forward progression along `learning_order()` for frontier concepts whose prerequisites are fully mastered.
- **Quiz Kinds**:
  - `check`: Fast diagnostic verification (3 questions, Easy, no lesson text) for unproven prerequisites without attempt data. Placed before dependents in topological order.
  - `probe`: Focused 3-question diagnostic sweep targeting the student's highest-severity active or suspected misconception (`focus = {"concept": ..., "target_misconceptions": [...]}`).
  - `reevaluation`: Comprehensive plan-wide quiz assessing retention across all plan concepts (`concept = "all-plan-concepts"`, `focus = {"concepts": [...]}`).

Downstream consumers use `plan_step_concepts(step) -> List[str]` to extract concrete concept tags across all step kinds.

### Core Pipeline
1. **Seed Concept Discovery**: Gathers learner deficits from the Performance Analysis Agent report: weak topics (mastery < 40%), active misconceptions with unmastered concepts, retention review candidates, and theory-vs-tracing skill gaps.
2. **Frontier & Real Advance**: Identifies frontier concepts via `frontier(report, strong_threshold=70.0)` in `learning_order()` that are not mastered (< 70%) and whose direct prerequisites are all mastered (>= 70%). If no weak seeds exist, schedules up to 2 frontier concepts as `advance` steps. If the entire course is mastered, schedules a single mixed review `reevaluation` step. If weak seeds exist and learning steps < 3, adds 1 frontier advance step placed topologically.
3. **Prerequisite Closure & Check Steps**: Computes transitive dependencies. Unproven prerequisites (no attempt data) become `check` quiz steps rather than full lessons, scheduled before their dependent concepts. At most 4 check steps are permitted per plan; excess unproven prerequisites are deferred with reason `"will be verified when its dependent is reached"`.
4. **Dynamic Check Adaptation (`plan_after_check`)**: When a student completes a check step:
   - If check score < 50.0%: converts the check step into a `prerequisite` lesson step (`Easy`, `simplified`) with prompt instructions to build the missing foundation.
   - If check score >= 50.0%: marks the check step `done` (`status='done'`), verifying the foundation and unlocking downstream concepts.
5. **Skill Gap Difficulty Calibration**: Steps whose only trigger is an identified theory-vs-tracing skill gap are capped at `Medium` difficulty.
6. **Multi-Factor Priority Scoring**:
   $$\text{Priority} = (100 - \text{mastery}) + 15 \times \min(\text{active\_severity}, 4) + 10 \times (\text{dependents}) + 8 \times [\text{due\_for\_review}]$$
7. **Topological Ordering (Kahn's Algorithm)**: Orders concepts such that every prerequisite precedes its dependents. Breaks ties by priority descending, followed by curriculum module order.
8. **Size Caps**: 7 learning steps maximum; 4 check steps maximum. Essential prerequisite relationships are preserved by deferring non-prerequisite seeds.
9. **Closing Verification Quizzes**: Appends one `probe` quiz step sweeping the top misconception and one final `reevaluation` quiz step covering all plan concepts with `focus = {"concepts": [...]}` and helper `plan_step_concepts(step)`.
10. **Deterministic Prompt Generation**: Formats teach prompts embedding concept title, student evidence, misconception pairs (`wrong_belief -> correct_idea`), skill gap instructions, and student custom notes.
11. **Formal Coverage Checker (`check_coverage`)**: Validates order validity (including check step precedence), weak concept coverage, active misconception coverage, acyclicity/uniqueness, and closing quizzes.

---

## 2. Property Evaluation Results (300 Synthetic Profiles)

To test mathematical guarantees, we ran a Monte Carlo evaluation across **300 random student profiles** with diverse mastery distributions, prerequisite chains, and active misconception counts (seed 42).

| Evaluation Metric | Target Property | Measured Result | Status |
| :--- | :--- | :---: | :---: |
| **Topological Order Validity** | Every prerequisite precedes dependents | **100.0%** | PASS |
| **Prerequisite Closure** | All required prerequisites scheduled, mastered, or deferred check | **100.0%** | PASS |
| **Size Cap Compliance** | $\le 7$ learning steps and $\le 4$ check steps | **100.0%** | PASS |
| **Checker False Negatives** | 0 undetected planted violations (1 per profile) | **0 (0.0%)** | PASS |
| **Advance on Mastered Violations** | 0 advance steps for concepts with mastery $\ge 70\%$ | **0 (0 violations)** | PASS |
| **Lesson on Mastered Violations** | 0 lesson steps for concepts with mastery $\ge 70\%$ | **0 (0 violations)** | PASS |
| **Check Precedes Dependent** | 100% of check steps precede their dependent steps | **100.0%** | PASS |
| **`plan_after_check` Conversion** | 100% correct branching (< 50% lesson, $\ge 50\%$ done) | **100.0%** | PASS |
| **Average Plan Length** | Total steps per study plan | **9.12 steps** | PASS |
| **Breakdown: Lesson Steps** | Remediation, advance, review lessons | **4.80 steps** | PASS |
| **Breakdown: Check Steps** | Diagnostic prerequisite checks | **2.33 steps** | PASS |
| **Breakdown: Verification Quizzes** | Probe + Reevaluation closing quizzes | **2.00 steps** | PASS |
| **Average Deferred Items** | Preserved for subsequent study cycles | **0.71 concepts** | PASS |

---

## 3. Coverage comparison (by construction)

These metrics represent algorithmic structural coverage by construction (graph completeness, constraint satisfaction, and diagnostic verification properties), not measured student learning outcomes.

| Structural Coverage Property | Legacy Single-Step `decide()` | Multi-Step Study Plan | Scope & Diagnostic Difference |
| :--- | :---: | :---: | :--- |
| **Weak Concepts Handled** | 1.00 concepts | **3.45 concepts** | Multi-concept curriculum scheduling vs single greedy step |
| **Active Misconceptions Targeted** | 0.34 misconceptions | **2.00 misconceptions** | Complete active set addressed vs opportunistic single concept |
| **Prerequisite Architecture** | Greedy 1-step parent check (R2) | Transitive DAG closure with unproven `check` steps | Prevents learning gaps before teaching advanced concepts |
| **Prerequisite Verification** | Assumed unverified | Fast 3-question diagnostic quiz (`check`) before dependent | Verified prior knowledge without full lesson overhead |
| **Verification Loop** | None | Targeted `probe` + comprehensive `reevaluation` quizzes | Closing verification built into every generated plan |
| **Student Agency** | Binary accept/override | Inspectable plan with step notes, skips, and reordering | Transparent control over curriculum execution |
