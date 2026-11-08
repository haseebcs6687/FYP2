# EduGen - Question Pool Status & Phase 11a Top-Up

This document tracks the verified active question pool in `data/edugen.db` alongside the Phase 11a generated gap batches (G01–G24, 288 questions in `rag/corpus/questions/raw/`).

## Active Pool & Phase 11a Additions per Concept

| Concept | DB Easy | DB Med | DB Hard | DB Total | Gap Top-Up (E/M/H) | Post-Ingest Projected |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `abstract-class-vs-interface` | 4 | 4 | 3 | **11** | - | **11** |
| `abstract-classes` | 8 | 4 | 0 | **12** | - | **12** |
| `abstract-methods` | 7 | 4 | 1 | **12** | - | **12** |
| `abstraction-basics` | 3 | 0 | 0 | **3** | +5/+9/+10 | **27** |
| `access-modifiers` | 2 | 0 | 0 | **2** | +6/+9/+9 | **26** |
| `checked-vs-unchecked` | 0 | 2 | 0 | **2** | +10/+5/+9 | **26** |
| `class-definition` | 7 | 3 | 4 | **14** | - | **14** |
| `constructor-basics` | 3 | 0 | 0 | **3** | +5/+9/+10 | **27** |
| `constructor-chaining` | 5 | 2 | 4 | **11** | - | **11** |
| `constructor-overloading` | 4 | 4 | 0 | **8** | +3/+4/+5 | **20** |
| `copy-constructor` | 7 | 4 | 0 | **11** | +3/+4/+5 | **23** |
| `custom-exceptions` | 4 | 4 | 3 | **11** | - | **11** |
| `data-hiding` | 8 | 2 | 0 | **10** | +3/+4/+5 | **22** |
| `default-constructor` | 0 | 2 | 0 | **2** | +9/+5/+10 | **26** |
| `default-methods` | 7 | 4 | 0 | **11** | - | **11** |
| `default-values` | 0 | 3 | 0 | **3** | +11/+3/+10 | **27** |
| `defensive-copying` | 5 | 4 | 3 | **12** | - | **12** |
| `design-patterns` | 7 | 4 | 1 | **12** | - | **12** |
| `dynamic-method-dispatch` | 3 | 0 | 0 | **3** | +5/+10/+9 | **27** |
| `exception-chaining` | 4 | 3 | 0 | **7** | - | **7** |
| `exception-throwing` | 6 | 4 | 1 | **11** | - | **11** |
| `finally-block` | 4 | 4 | 4 | **12** | - | **12** |
| `functional-interface` | 5 | 4 | 2 | **11** | - | **11** |
| `garbage-collection` | 4 | 4 | 4 | **12** | - | **12** |
| `getters-setters` | 7 | 4 | 0 | **11** | +3/+4/+5 | **23** |
| `immutability` | 4 | 4 | 3 | **11** | - | **11** |
| `inheritance-basics` | 15 | 8 | 2 | **25** | - | **25** |
| `inheritance-hierarchy` | 0 | 3 | 0 | **3** | +11/+3/+10 | **27** |
| `interface-basics` | 4 | 4 | 3 | **11** | - | **11** |
| `javabeans` | 6 | 4 | 2 | **12** | +4/+4/+4 | **24** |
| `local-vs-instance-variables` | 4 | 3 | 4 | **11** | - | **11** |
| `method-overloading` | 4 | 6 | 3 | **13** | - | **13** |
| `method-overriding` | 4 | 4 | 2 | **10** | - | **10** |
| `multiple-inheritance` | 4 | 4 | 2 | **10** | - | **10** |
| `null-pointer-exception` | 8 | 2 | 0 | **10** | +2/+4/+6 | **22** |
| `object-composition` | 5 | 4 | 2 | **11** | - | **11** |
| `object-instantiation` | 8 | 1 | 0 | **9** | +2/+5/+5 | **21** |
| `reference-semantics` | 8 | 4 | 0 | **12** | +3/+4/+5 | **24** |
| `runtime-polymorphism` | 4 | 3 | 2 | **9** | - | **9** |
| `static-members` | 5 | 4 | 3 | **12** | - | **12** |
| `super-keyword` | 4 | 3 | 3 | **10** | - | **10** |
| `this-keyword` | 4 | 4 | 4 | **12** | - | **12** |
| `try-catch` | 5 | 4 | 3 | **12** | - | **12** |
| `try-with-resources` | 4 | 4 | 4 | **12** | - | **12** |
| **TOTAL** | **214** | **146** | **72** | **432** | **+85/+86/+117 (+288)** | **720** |

## Phase 11a Deficit Resolution Summary

- **Initial Active Pool in DB:** 464 questions across 44 concepts (Easy=234, Medium=155, Hard=75).
- **Pool Top-Up Generated (G01–G24):** 288 validated questions (Easy=85, Medium=86, Hard=117).
- **Total Raw Question Bank on Disk:** 888 questions across 74 batches (P01–P50 + G01–G24), all 100% validated.
- **Top Deficit Concepts Addressed:** `default-constructor`, `access-modifiers`, `checked-vs-unchecked`, `default-values`, `constructor-basics`, `inheritance-hierarchy`, `dynamic-method-dispatch`, `abstraction-basics`, `null-pointer-exception`, `object-instantiation`, `data-hiding`, `reference-semantics`, `constructor-overloading`, `copy-constructor`, `getters-setters`, `javabeans`.

