# EduGen RAG Evaluation (Phase 3B - Honest Evaluation & Ablation)

## 1. Evaluation Methodology

The EduGen RAG retrieval subsystem was evaluated across all 44 canonical concepts in the OOP curriculum using three distinct query formulations per concept (132 total queries):

1. **Concept Title Query**: Exact canonical title (e.g., *"Defining a Class"*, *"Method Overriding"*).
2. **Question-Style Query**: Synthesized question based on the concept summary (e.g., *"How does Method Overriding work in Java? When a subclass defines a method with the same signature..."*).
3. **Misconception Query**: Student wrong-belief statement taken directly from the misconception catalog (e.g., *"static methods are overridden polymorphically"*).

### Evaluation Modes

- **Sanity Check (Filtered):** Tests the end-to-end retrieval wiring using production filters (`concept_tags = [target_concept]`). **NOTE: This is NOT a quality metric.** Because `retrieve()` filters by concept tag by construction, Hit@k is 100% by definition. It is preserved strictly as a sanity check for filter plumbing.
- **Blind Mode (Real Retrieval Quality Measurement):** Disables all concept tag filters. Filters exclusively by target collection:
  - **Lessons:** restricted to `collections = ['book', 'note']`
  - **Questions:** restricted to `collections = ['question']`
  Each query is embedded **ONCE** and evaluated against the full index candidate pool in memory across three ranking variants.

### Metrics Computed
- **Hit@1, Hit@3, Hit@5:** Fraction of queries where a returned chunk in the top-k is tagged with the target concept (or matches `chunk.concept`).
- **MRR (Mean Reciprocal Rank):** $\frac{1}{\text{rank}}$ of the first relevant chunk in top-5 (1.0 for rank 1, 0.5 for rank 2, 0.333 for rank 3, 0.25 for rank 4, 0.20 for rank 5; 0 if no match in top-5).

---

## 2. In-Memory Ablation Results

Each of the 132 queries was embedded once with `ollama:nomic-embed-text:768` (15.4s total embedding time), then re-ranked in memory across the three variants (4.5s total re-ranking time; 19.9s overall):

| Target Collection | Variant | Hit@1 | Hit@3 | Hit@5 | MRR | Queries |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Lessons (book+note)** | Lexical-only | 25.8% | 52.3% | 68.2% | 0.4085 | 132 |
| **Lessons (book+note)** | Cosine-only | 87.9% | 97.0% | 98.5% | 0.9217 | 132 |
| **Lessons (book+note)** | **Hybrid (0.7 Cosine + 0.3 Lexical)** | **88.6%** | **97.7%** | **98.5%** | **0.9274** | 132 |
| **Questions (MCQ)** | Lexical-only | 9.8% | 15.9% | 23.5% | 0.1432 | 132 |
| **Questions (MCQ)** | Cosine-only | 77.3% | 93.2% | 97.0% | 0.8500 | 132 |
| **Questions (MCQ)** | **Hybrid (0.7 Cosine + 0.3 Lexical)** | **78.0%** | **93.9%** | **98.5%** | **0.8604** | 132 |
| **Combined Overall** | Lexical-only | 17.8% | 34.1% | 45.8% | 0.2758 | 264 |
| **Combined Overall** | Cosine-only | 82.6% | 95.1% | 97.7% | 0.8859 | 264 |
| **Combined Overall** | **Hybrid (0.7 Cosine + 0.3 Lexical)** | **83.3%** | **95.8%** | **98.5%** | **0.8939** | 264 |

### Ablation Takeaways
1. **Lexical-only fails on student misconception queries:** Lexical matching achieves only 25.8% Hit@1 on lessons and 9.8% Hit@1 on questions. Queries describing misconceptions (e.g. *"static methods are overridden polymorphically"*) use terminology from multiple concepts, causing keyword collisions without semantic disambiguation.
2. **Dense vector representations dominate:** Cosine similarity jumps Hit@1 from 25.8% to 87.9% (+62.1%) on lessons, showing `nomic-embed-text` captures OOP semantics effectively.
3. **Hybrid combination provides reliable gains:** Combining $0.7 \times \text{cosine} + 0.3 \times \text{lexical}$ achieves the highest performance across all metrics (88.6% Hit@1, 97.7% Hit@3 on lessons; 83.3% Hit@1, 95.8% Hit@3 overall; MRR 0.8939). Lexical signals break ties when dense embeddings produce close scores between related concepts.

---

## 3. Blind Hybrid Performance by Module (Lessons)

Evaluating the hybrid model without concept tag filtering on lesson corpus (`book` + `note`):

| Module | Queries | Hit@1 | Hit@3 | Hit@5 | MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Classes & Objects** | 27 | 92.6% | 100.0% | 100.0% | 0.9568 |
| **Constructors** | 18 | 94.4% | 100.0% | 100.0% | 0.9722 |
| **Inheritance** | 12 | 66.7% | 100.0% | 100.0% | 0.7917 |
| **Polymorphism** | 9 | 55.6% | 100.0% | 100.0% | 0.7593 |
| **Encapsulation** | 18 | 100.0% | 100.0% | 100.0% | 1.0000 |
| **Abstraction** | 15 | 86.7% | 86.7% | 93.3% | 0.8833 |
| **Interfaces** | 9 | 88.9% | 88.9% | 88.9% | 0.8889 |
| **Exceptions** | 24 | 95.8% | 100.0% | 100.0% | 0.9792 |
| **OVERALL (44 concepts)** | **132** | **88.6%** | **97.7%** | **98.5%** | **0.9274** |

---

## 4. Weakest Concepts in Blind Retrieval

The five concepts with the lowest Blind Hit@3 / MRR in the hybrid model:

| Concept | Module | Blind Hit@3 | MRR | Root Cause Analysis |
| :--- | :--- | :---: | :---: | :--- |
| `design-patterns` | Abstraction | 66.7% | 0.6667 | Broad terminology overlap; queries for factory/singleton patterns match general class and interface chapters before specific pattern notes. |
| `interface-basics` | Interfaces | 66.7% | 0.6667 | Textbook chapters frequently introduce interfaces in comparative sections alongside abstract classes; chunks often receive `abstract-classes` tags first. |
| `abstract-class-vs-interface` | Abstraction | 66.7% | 0.7500 | Inherent dual-nature concept; passages discussing both abstract classes and interfaces are often tagged primarily with `abstract-classes` or `interface-basics`. |
| `runtime-polymorphism` | Polymorphism | 100.0% | 0.6111 | Hit@3 is 100% but Hit@1 is lower (MRR 0.6111) because `dynamic-method-dispatch` and `method-overriding` passages frequently outrank it due to identical vocabulary. |
| `dynamic-method-dispatch` | Polymorphism | 100.0% | 0.6667 | Synonymous concepts: textbook explanations interchange "dynamic binding", "virtual method invocation", and "polymorphic call", dispersing top-1 rank. |

---

## 5. Sanity Check (Filtered) — Not a Quality Metric

| Metric | Filtered Sanity Score |
| :--- | :---: |
| Filter Used | `concept_tags = [target_concept]` |
| Lesson Queries | 132 |
| Hit@1 | 100.0% |
| Hit@3 | 100.0% |
| Hit@5 | 100.0% |
| Evaluation Time | 1.6s |

> **Notice:** The filtered run confirms that when the Coordinator and Concept Clarifier pass explicit concept tags, the candidate pool filtering correctly isolates relevant passages. However, it cannot measure ranking quality on unstructured text, which is why the blind evaluation above is the authoritative benchmark.
