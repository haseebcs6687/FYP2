# EduGen - Verified Question Pool Status

This document tracks the verified active question pool across all 44 canonical concepts
and 3 difficulty tiers (Easy, Medium, Hard), alongside catalog misconception coverage.

| Concept | Easy | Medium | Hard | Total | Misconceptions Covered |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `abstract-class-vs-interface` | 4 | 4 | 3 | **11** | 4/4 |
| `abstract-classes` | 8 | 4 | 0 | **12** | 5/5 |
| `abstract-methods` | 7 | 4 | 1 | **12** | 3/4 |
| `abstraction-basics` | 13 | 9 | 5 | **27** | 4/4 |
| `access-modifiers` | 12 | 8 | 1 | **21** | 4/5 |
| `checked-vs-unchecked` | 11 | 7 | 8 | **26** | 4/4 |
| `class-definition` | 7 | 3 | 4 | **14** | 4/4 |
| `constructor-basics` | 10 | 6 | 6 | **22** | 5/5 |
| `constructor-chaining` | 5 | 2 | 4 | **11** | 3/4 |
| `constructor-overloading` | 10 | 8 | 1 | **19** | 4/4 |
| `copy-constructor` | 9 | 6 | 0 | **15** | 4/4 |
| `custom-exceptions` | 4 | 4 | 3 | **11** | 4/4 |
| `data-hiding` | 14 | 5 | 0 | **19** | 3/4 |
| `default-constructor` | 7 | 7 | 4 | **18** | 4/4 |
| `default-methods` | 7 | 4 | 0 | **11** | 4/4 |
| `default-values` | 18 | 6 | 2 | **26** | 4/4 |
| `defensive-copying` | 5 | 4 | 3 | **12** | 3/4 |
| `design-patterns` | 7 | 4 | 1 | **12** | 4/4 |
| `dynamic-method-dispatch` | 15 | 9 | 1 | **25** | 4/4 |
| `exception-chaining` | 4 | 3 | 0 | **7** | 4/4 |
| `exception-throwing` | 6 | 4 | 1 | **11** | 4/4 |
| `finally-block` | 4 | 4 | 4 | **12** | 4/4 |
| `functional-interface` | 5 | 4 | 2 | **11** | 4/4 |
| `garbage-collection` | 4 | 4 | 4 | **12** | 4/4 |
| `getters-setters` | 12 | 7 | 2 | **21** | 4/4 |
| `immutability` | 4 | 4 | 3 | **11** | 2/4 |
| `inheritance-basics` | 15 | 8 | 2 | **25** | 5/5 |
| `inheritance-hierarchy` | 18 | 5 | 1 | **24** | 2/4 |
| `interface-basics` | 4 | 4 | 3 | **11** | 5/5 |
| `javabeans` | 13 | 6 | 2 | **21** | 4/4 |
| `local-vs-instance-variables` | 4 | 3 | 4 | **11** | 4/4 |
| `method-overloading` | 4 | 6 | 3 | **13** | 5/5 |
| `method-overriding` | 4 | 4 | 2 | **10** | 5/6 |
| `multiple-inheritance` | 4 | 4 | 2 | **10** | 4/4 |
| `null-pointer-exception` | 12 | 4 | 0 | **16** | 1/4 |
| `object-composition` | 5 | 4 | 2 | **11** | 4/4 |
| `object-instantiation` | 14 | 6 | 0 | **20** | 4/4 |
| `reference-semantics` | 14 | 7 | 2 | **23** | 5/5 |
| `runtime-polymorphism` | 4 | 3 | 2 | **9** | 4/4 |
| `static-members` | 5 | 4 | 3 | **12** | 5/5 |
| `super-keyword` | 4 | 3 | 3 | **10** | 4/4 |
| `this-keyword` | 4 | 4 | 4 | **12** | 4/4 |
| `try-catch` | 5 | 4 | 3 | **12** | 5/5 |
| `try-with-resources` | 4 | 4 | 4 | **12** | 4/4 |
| **TOTAL** | **349** | **217** | **105** | **671** | - |

*Note on Active Question Pool Totals:*
The table above counts the 671 concept/difficulty-tier questions. The total active pool in `data/edugen.db` comprises **703 active questions** (671 standard tier questions + 31 prebuilt diagnostic set questions + 1 practice question).
Misconception distractor tag coverage (computed strictly from `questions.tags_json`, which is consumed by the Quiz Engine and Performance Analysis Agent):
- **373 of 703 active questions (53.1%)** carry $\ge 1$ tagged distractor.
- **584 total distractor misconception tags** are distributed across all 44 canonical concepts.
- 42 of 44 concepts have $\ge 3$ tagged questions; only `inheritance-hierarchy` (2) and `null-pointer-exception` (2) have fewer than 3.
- Unverified labels in `verifier_labels_json` are kept strictly separate as non-authoritative guesses and are never merged into tag coverage figures.

## Top 10 Emptiest Concept/Difficulty Cells

The following cells have the lowest coverage and should be prioritized for generation:

1. `abstract-classes` (Hard) — **0** verified question(s)
2. `copy-constructor` (Hard) — **0** verified question(s)
3. `data-hiding` (Hard) — **0** verified question(s)
4. `default-methods` (Hard) — **0** verified question(s)
5. `exception-chaining` (Hard) — **0** verified question(s)
6. `null-pointer-exception` (Hard) — **0** verified question(s)
7. `object-instantiation` (Hard) — **0** verified question(s)
8. `abstract-methods` (Hard) — **1** verified question(s)
9. `access-modifiers` (Hard) — **1** verified question(s)
10. `constructor-overloading` (Hard) — **1** verified question(s)
