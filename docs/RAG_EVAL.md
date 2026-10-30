# EduGen RAG Evaluation (Phase 3)

## Evaluation Methodology

The EduGen RAG retrieval subsystem was evaluated across all 44 canonical concepts in the curriculum. For each concept, three distinct query formulations were evaluated:

1. **Concept Title Query**: Exact canonical title (e.g., *"Defining a Class"*, *"Method Overriding"*).
2. **Question-Style Query**: Synthesized question based on the concept's summary (e.g., *"How does Method Overriding work in Java? When a subclass defines a method with the same signature..."*).
3. **Misconception Query**: Student wrong-belief statement taken directly from the misconception catalog (e.g., *"static methods are overridden polymorphically"*).

### Evaluation Tasks & Metrics

- **Lesson Retrieval (`mode='lesson'`):**
  - Search restricted to pedagogical corpus collections: `['book', 'note']` (strictly excludes question bank).
  - Scoring: Hybrid $0.70 \times \text{cosine} + 0.30 \times \text{lexical}$ with $+0.08$ level boost matching requested difficulty (`Easy` $\rightarrow$ `basic`, `Medium` $\rightarrow$ `standard`, `Hard` $\rightarrow$ `advanced`).
  - Metrics: **Hit@1**, **Hit@3**, and **Hit@5**, measuring whether the retrieved passages are explicitly tagged with the target concept.
- **Reference Question Retrieval (`retrieve_reference_questions`):**
  - Search restricted to collection `['question']`.
  - Strict metadata filtering: concept match, strict difficulty matching (`Easy`, `Medium`, `Hard`), and near-duplicate vector rejection ($\text{cosine} \ge 0.90$).
  - Metrics: **MCQ Hit@1**, **MCQ Hit@3**, and **Difficulty Match Accuracy** (100% strict verification).

---

## Evaluation Results

**Active Embedder Backend:** `ollama:nomic-embed-text:768`  
**Total Queries Evaluated:** 132 lesson queries + 132 reference MCQ retrievals (264 queries total)

| Module | Lesson Hit@1 | Lesson Hit@3 | Lesson Hit@5 | MCQ Hit@1 | MCQ Hit@3 | Difficulty Match |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Classes & Objects** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Constructors** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Inheritance** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Polymorphism** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Encapsulation** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Abstraction** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Interfaces** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **Exceptions** | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **OVERALL (44 concepts)** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** | **100.0%** |

---

## Embedder Backend Comparison

| Backend | Vector Dim | Dependencies | Search Latency | Overall Hit@1 |
| :--- | :---: | :---: | :---: | :---: |
| `ollama:nomic-embed-text:768` *(Active)* | 768 | Local Ollama server | ~30ms / query | **100.0%** |
| `hashing:feature-hash-768:768` *(Fallback)* | 768 | None (Standard Python) | <5ms / query | **93.2%** |

### Key Findings
1. **Two-Stage Filtering:** Stage 1 metadata filtering isolates candidate subsets before scoring, preventing cross-collection contamination (lessons never receive raw MCQs and vice versa).
2. **Pedagogical Level Boost:** The $+0.08$ boost successfully favors introductory text for Easy lessons and deep-dive caveat text for Hard lessons without dropping relevant passages.
3. **Reference Question Quality:** All 600 bank MCQs are indexed with full schema provenance and strict difficulty matching, enabling the Concept Clarifier to ground generation in vetted reference items.
