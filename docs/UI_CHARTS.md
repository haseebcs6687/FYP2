# EduGen UI Charting & Grounding Sources Specification

## 1. Zero-Dependency Inline SVG Charting Architecture

EduGen replaces third-party external charting libraries (e.g. Chart.js, D3.js) with a lightweight, offline, zero-dependency inline SVG engine located at `static/js/charts.js` (`window.EGCharts`).

### Design Principles:
1. **Offline & Self-Contained**: Operates without external CDNs or network calls, ensuring fast, deterministic headless Chromium test passes and air-gapped lab compatibility.
2. **Accessible**: Every SVG element includes semantic `<title>`, `role="img"`, and `aria-label` attributes to support screen readers without cluttering visual layout.
3. **Responsive**: SVGs use percentage widths, `viewBox` scaling, and flex/grid containers to resize fluidly across viewports down to 360px mobile width.
4. **Theme Consistency**: Colors directly bind to existing CSS variables in `static/css/edugen.css`.

### Available Chart Types:
- **`EGCharts.ring(value, total, options)`**: Circular progress meter showing percentage or fraction with smooth stroke-dasharray and centered label.
- **`EGCharts.spark(data, options)`**: Minimal inline sparkline tracking score trajectories and trend directions without axes.
- **`EGCharts.line(data, options)`**: Full multi-point trend graph with Cartesian axes, dot markers, grid lines, and a 70% mastery benchmark guide line. Accepts both arrays of numeric scores and point objects (`{x, y, label}`), rendering un-distorted SVG geometry.
- **`EGCharts.bar(items, options)`**: Horizontal labeled progress bars comparing discrete concepts or module masteries.
- **`EGCharts.stacked(segments, options)`**: Multi-segment proportional stacked bar showing distribution across categories (e.g. Mastered, Progressing, Weak, Not enough data yet).
- **`EGCharts.strip(outcomes, options)`**: Compact horizontal question outcome sequence (correct/incorrect) with tooltip inspection.

---

## 2. Design System Color Semantics

All visualization colors adhere strictly to the EduGen design system tokens:

| Token | CSS Variable | Hex / Role | Semantic Usage |
|---|---|---|---|
| **Student Signal** | `--signal` | `#2563eb` (Blue) | Student activity, baseline scores, progression, sparklines |
| **Agent / System** | `--agent` | `#7c3aed` (Violet) | AI agent decisions, study plan milestones, coordinator telemetry |
| **Attention / Weak** | `--attn` | `#d97706` (Amber) | Scores < 70%, weak topics, review decayed concepts, attention alerts |
| **Mastered / Good** | `--good` | `#059669` (Green) | Scores >= 70%, mastered concepts, completed milestones |
| **Neutral / Insufficient Data** | `--ink-4` | `#94a3b8` (Grey) | Concepts with not enough attempt data yet, background tracks |
| **Error / Wrong Answer** | `--crit` | `#dc2626` (Red) | Incorrect question choices on quiz review only (never applied to low aggregate scores) |

---

## 3. Grounding Sources & Corpus Breakdown

EduGen's knowledge retrieval index grounds all pedagogical interventions, lesson explanations, and question validations against authoritative open-source textbooks and authored curriculum material.

### Corpus Passage Distribution:
```
Total Corpus Passages: 7,333
├── 3 Core Textbooks (6,556 passages, 89.4%)
│   ├── Introduction to Programming Using Java, v9 (David J. Eck) ..... 3,258 passages (44.4%)
│   ├── Java Notes for Professionals (GoalKicker) ....................... 2,673 passages (36.5%)
│   └── Think Java, 2nd ed. (Allen B. Downey & Chris Mayfield) ........... 625 passages (8.5%)
├── Question Bank Reference Passages (600 passages, 8.2%)
│   ├── Java Notes for Professionals batches ............................ 276 passages (3.8%)
│   ├── Introduction to Programming Using Java batches ................... 216 passages (2.9%)
│   └── Think Java batches .............................................. 108 passages (1.5%)
└── Authored Concept Notes (177 passages, 2.4%)
    └── 44 canonical Java OOP concept definitions ........................ 177 passages (2.4%)
```

### Question Pool Breakdown:
- **Raw Textbook-Derived MCQs**: **888** candidate questions generated and cataloged across the 3 textbooks (`docs/report_assets/question_bank_by_pdf.csv`):
  - *Java Notes for Professionals*: 420 questions
  - *Introduction to Programming Using Java, v9*: 276 questions
  - *Think Java, 2nd ed.*: 192 questions
- **Active Pool Questions in SQLite**: **703** questions (`pool_status = 'active'`) verified by the structural verifier and bias gate (excluding quarantined items).
