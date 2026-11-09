# EduGen Demonstration & Viva Guide (FYP-2)

This document provides credentials, setup steps, and a structured 5-minute click-by-click viva demonstration script showcasing EduGen's four collaborating autonomous agents, Bayesian Knowledge Tracing (BKT), prerequisite study planning, real-time event telemetry, and secure student assessment.

---

## 1. "Before the Demo" Pre-Flight Checklist

Complete these 7 checks prior to starting the viva demonstration:

1. **Ollama Service Running & Embedding Model Available**:
   - Ensure the Ollama local daemon is active.
   - Confirm the embedding model is downloaded: `ollama list` (should list `nomic-embed-text`).
   - If not running, start Ollama; note that even if Ollama is offline, EduGen automatically falls back to memory-cached BM25 lexical retrieval.
2. **Virtual Environment Python**:
   - Always run commands and launch the application using `venv\Scripts\python.exe` to ensure pinned dependencies (`flask`, `reportlab`, `matplotlib`, `playwright`) are loaded.
3. **Groq API Key in `.env`**:
   - Confirm `.env` exists in the project root containing a valid, active `GROQ_API_KEY=<your_api_key>`.
4. **Internet Connectivity Active**:
   - Verify network connectivity so the Concept Clarifier agent can reach the Groq API endpoint (`api.groq.com`).
5. **Reset Demo Student to Known Baseline**:
   - Re-initialize the demonstration student to the canonical 5/6 completed state:
     ```bash
     venv\Scripts\python.exe scripts/seed_demo_student.py --reset
     ```
6. **Verify System Health Endpoint**:
   - Start the application: `venv\Scripts\python.exe run.py`
   - In a browser or terminal, verify `GET http://localhost:5000/api/health`.
   - Ensure response confirms `"status": "ok"`, `"database": "ok"`, and `703` active pool questions.
7. **Reset Browser Evaluator Capsule State**:
   - If the browser previously retained a stale UI state, open Developer Tools Console and run:
     ```javascript
     localStorage.setItem('edugen_evaluator_capsule_state', 'minimized');
     ```
   - This ensures the floating Evaluator capsule pill is neatly displayed in the bottom-right corner without blocking the screen.

---

## 2. Demo Student Credentials & Seed Script

| Field | Value |
|---|---|
| **Login URL** | `http://localhost:5000/login` |
| **Email** | `demo@edugen.local` |
| **Password** | `demo-pass` |
| **Student Name** | Demo Student |
| **Seed State** | 8 quizzes, 47 questions, 66.0% accuracy, 5/6 plan steps complete |

To reset or re-seed the demonstration student at any time:
```bash
venv\Scripts\python.exe scripts/seed_demo_student.py --reset
```

*Note: The seed script executes purely against verified local pool questions and the real Coordinator state machine without external LLM calls or network latency.*

---

## 3. 5-Minute Click-by-Click Viva Script

### Step 1: Sign In & Dashboard (0:00 – 0:45)
1. Navigate to `http://localhost:5000/login`.
2. Enter email `demo@edugen.local` and password `demo-pass`. Click **Sign in**.
3. Point out the personalized dashboard:
   - **Snapshot Cards**: 66.0% overall accuracy, 8 quizzes completed, 47 questions answered across 4 modules.
   - **Active Study Plan Card**: Displays *Core OOP & Inheritance Mastery Plan*, showing 5 of 6 steps completed (83% progress) with next recommended action: **Final Reevaluation**.
   - **Evaluator Pill**: Located in the bottom-right corner, displaying live telemetry events.

---

### Step 2: Evaluator Activity Window (0:45 – 1:30)
1. Click the floating **Evaluator capsule pill** at the bottom-right corner.
2. The Evaluator Activity Panel slides open:
   - **Event Timeline**: Shows real-time multi-agent handoffs (`Coordinator` -> `Performance Analysis` -> `Adaptive Content` -> `Concept Clarifier`).
   - **Latency Metrics**: Highlight sub-50ms execution times when questions are served directly from the verified active question pool.
   - **Agent Logs**: Displays real-time logging reflecting domain events.
3. Click the **Minimize (-)** button in the top-right of the panel. Note that the panel minimizes cleanly into the pill without obstructing the interface.

---

### Step 3: Prerequisite-Ordered Study Plan (1:30 – 2:15)
1. Click **Learn** in the top navigation, then select **Study plan** (or navigate to `/plan`).
2. Point out the pedagogical progression:
   - **Step 1 (Prerequisite)**: *Class & Object Fundamentals* (Completed).
   - **Step 2 (Skill Gap)**: *Inheritance Architecture in Java* (Completed).
   - **Step 3 (Check Quiz)**: *Check: Inheritance Basics* (Initial attempt failed at 60%, retried and cleared at 80%).
   - **Step 4 (Probe Quiz)**: *Probe: Method Overriding* (Completed misconception sweep).
   - **Step 5 (Advance)**: *Super Keyword & Member Access* (Completed).
   - **Step 6 (Reevaluation)**: *Final Reevaluation* (Pending closing assessment).
3. Explain how the prerequisite closure and frontier algorithms prevent students from skipping foundational gaps.

---

### Step 4: Performance Analytics & Misconception Diagnosis (2:15 – 3:00)
1. Click **Analysis** in the top navigation (`/analysis`).
2. Highlight the diagnostic signals:
   - **Concept Mastery Table**: Displays recency-weighted EWMA and Bayesian Knowledge Tracing scores across concepts.
   - **Trend Indicators**: Badges indicate whether a student is *improving*, *steady*, or *declining*.
   - **Detected Misconceptions**: Shows authentic misconceptions identified from distractor selections (e.g. `class-definition/class-stores-instance-data`) paired with targeted conceptual clarifications.

---

### Step 5: Chronological Assessment History (3:00 – 3:30)
1. Click **History** in the top navigation (`/history`).
2. Point out the 14-day progression:
   - 8 backdated assessment attempts spanning OO Basics, Inheritance, Polymorphism, and Exception Handling.
   - The diagnostic assessment baseline (Day -14) showing initial 41.7% accuracy advancing to ~80% on recent module assessments.

---

### Step 6: Live Assessment Run & Real-Time Grading (3:30 – 4:15)
1. Click **Quiz** in the top navigation (`/quiz`).
2. Select concept **Class Definition** and difficulty **Easy**.
3. Click **Start quiz**.
4. Answer the 5 questions by selecting option choices.
5. Click **Submit quiz**.
6. The server grades the submission instantly via `POST /api/quiz/submit` (protected by CSRF token):
   - Result page renders with score, question explanations, and updated concept mastery.
   - Re-opening the Evaluator window shows the new grading and BKT update events logged in real time.

---

### Step 7: Download PDF Performance Report (4:15 – 4:45)
1. Return to **Dashboard** or **Analysis**.
2. Click the **Download report** button in the header.
3. Open the downloaded PDF document:
   - **Header & Executive Summary**: Formatted student identity, accuracy %, questions attempted, and learning stage.
   - **Curriculum Mastery Breakdown**: Table grouped by module with mastery percentages and proficiency statuses (*Mastered*, *In Progress*, *Needs Review*).
   - **Key Focus Areas & Misconceptions**: Plain-English explanations of observed misunderstandings with actionable remedies.
   - **Professional Typography**: Clean typography, page numbers, generation timestamp, and zero internal technical jargon.

---

### Step 8: Sign Out & Access Control Verification (4:45 – 5:00)
1. Click **Sign out** in the top navigation bar.
2. Confirm redirect to the public landing page (`/`).
3. Attempt to navigate directly to `http://localhost:5000/dashboard` or `http://localhost:5000/report.pdf`.
4. Confirm access control instantly blocks unauthenticated visitors and redirects to `/login`.

---

## 3. Test Suites & System Verification

To run the unified test runner and verify 100% pass across all test suites:
```bash
venv\Scripts\python.exe scripts/run_all_tests.py
```

### Individual Test Suites
- **Real Browser Integration Test (Playwright)**:
  `venv\Scripts\python.exe scripts/test_browser.py`
- **Security & CSRF Protection**:
  `venv\Scripts\python.exe scripts/test_security.py`
- **PDF Report Generation**:
  `venv\Scripts\python.exe scripts/test_report.py`
- **End-to-End Smoke Test**:
  `venv\Scripts\python.exe scripts/smoke_test.py`
- **JavaScript Syntax Check**:
  `venv\Scripts\python.exe scripts/test_js.py`
