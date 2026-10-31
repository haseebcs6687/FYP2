"""
End-to-end smoke test. Exercises the whole stack without a browser:
signup, session pipeline, analysis, recommendation, quiz start/submit,
history, RAG search and access control.

    python scripts/smoke_test.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("EDUGEN_EMBEDDING_BACKEND", "hashing")
os.environ.setdefault("EDUGEN_SECRET_KEY", "smoke-test-key")
os.environ["EDUGEN_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "smoke.db")

import core.db as db                                       # noqa: E402
db.DB_PATH = os.environ["EDUGEN_DB_PATH"]

from app import app                                        # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("  {} {}{}".format("PASS" if condition else "FAIL", name,
                             "" if condition else "  <- " + str(detail)[:160]))


def main():
    app.config["TESTING"] = True
    client = app.test_client()

    print("\n1. Public pages")
    check("landing renders", client.get("/").status_code == 200)
    check("about renders", client.get("/about").status_code == 200)
    check("login renders", client.get("/login").status_code == 200)

    print("\n2. Access control")
    check("dashboard redirects when signed out", client.get("/dashboard").status_code == 302)
    r = client.get("/api/analysis")
    check("analysis API returns 401 when signed out", r.status_code == 401, r.data)

    print("\n3. Signup and session")
    r = client.post("/api/auth/signup", json={
        "name": "Test Student", "email": "test@example.com", "password": "password123"})
    check("signup succeeds", r.status_code == 201, r.data)
    check("dashboard now loads", client.get("/dashboard").status_code == 200)

    r = client.post("/api/auth/signup", json={
        "name": "X", "email": "test@example.com", "password": "password123"})
    check("duplicate email rejected", r.status_code == 400)

    r = client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong"})
    check("wrong password rejected", r.status_code == 401)

    print("\n4. Coordinator pipeline (first visit)")
    r = client.get("/api/session?generate=0")
    s = r.get_json()
    check("session runs", r.status_code == 200, r.data)
    check("routed as first visit", s.get("first_visit") is True, s)
    check("trace produced", len(s.get("trace", [])) >= 2, s.get("trace"))
    check("retrieval brief issued", bool(s.get("retrieval_brief")), s.get("retrieval_brief"))
    concept = s.get("focus_concept")
    difficulty = s.get("recommended_difficulty")
    print("     -> agent chose '{}' at {}".format(concept, difficulty))

    print("\n5. RAG")
    r = client.get("/api/rag/status")
    rag = r.get_json()
    check("index is loaded", rag.get("ready") is True, rag.get("error"))
    check("all 44 concepts covered", rag.get("covered_concepts") == 44, rag.get("covered_concepts"))
    r = client.get("/api/rag/search?q=constructor chaining super this")
    res = r.get_json()
    check("search returns hits", len(res.get("results", [])) > 0, res)
    top = res["results"][0] if res.get("results") else {}
    check("top hit is on-topic",
          "constructor" in (top.get("text", "") + top.get("heading", "")).lower(),
          top.get("heading"))

    r = client.get("/api/rag/brief/method-overriding/Medium")
    brief = r.get_json()
    check("brief retrieval works", brief["retrieval"]["ready"] is True, brief["retrieval"].get("error"))

    print("\n6. Lesson generation (offline fallback path)")
    r = client.get("/api/lesson/{}/{}".format(concept, difficulty))
    lesson = r.get_json()
    check("lesson returned", r.status_code == 200, r.data)
    check("lesson has explanation", len(lesson.get("explanation", "")) > 100)
    check("lesson has code", len(lesson.get("code_example", "")) > 20)
    print("     -> served by: {}".format(lesson.get("generated_by")))

    print("\n7. Quiz flow")
    r = client.post("/api/quiz/start", json={
        "concept": concept, "difficulty": difficulty, "count": 5})
    quiz = r.get_json()

    if r.status_code == 503:
        # In FYP-2, the static 120-question bank was retired on purpose (all quizzes
        # are generated on demand by the Concept Clarifier via external LLM).
        # In offline mode or when no GROQ_API_KEY is configured, /api/quiz/start
        # legitimately returns 503 generation_unavailable; smoke_test injects a synthetic
        # quiz session to exercise grading and downstream analysis.
        # This replaces the 3 online quiz checks ('quiz generated', 'questions returned',
        # 'answers hidden from client') with 1 offline check ('synthetic quiz injected'),
        # resulting in 52 checks passing instead of 54.
        print("     -> quiz generation unavailable (no LLM key). Injecting a")
        print("        synthetic quiz session to exercise grading and analysis.")
        quiz = inject_quiz(concept, difficulty)
        check("synthetic quiz injected", quiz is not None)
    else:
        check("quiz generated", r.status_code == 200, r.data)
        check("questions returned", len(quiz.get("questions", [])) >= 3)
        check("answers hidden from client",
              all("correct" not in q for q in quiz.get("questions", [])))

    if quiz:
        answers = {str(i): 0 for i in range(len(quiz["questions"]))}
        timings = {str(i): 4000 for i in range(len(quiz["questions"]))}
        r = client.post("/api/quiz/submit", json={
            "quiz_session_id": quiz["quiz_session_id"],
            "answers": answers, "timings": timings, "duration_ms": 30000})
        result = r.get_json()
        check("quiz graded", r.status_code == 200, r.data)
        check("score computed", "score" in result and "percentage" in result)
        check("review returned", len(result.get("review", [])) == len(quiz["questions"]))
        print("     -> scored {}/{}".format(result.get("score"), result.get("total")))

        r = client.get("/api/quiz/result/{}".format(result["quiz_result_id"]))
        check("result page data loads", r.status_code == 200, r.data)

    print("\n8. Analysis and adaptivity after a quiz")
    r = client.get("/api/analysis")
    analysis = r.get_json()
    check("analysis runs", r.status_code == 200, r.data)
    check("concepts were scored", len(analysis.get("concept_stats", {})) > 0)
    check("mastery is computed",
          all("mastery" in v for v in analysis.get("concept_stats", {}).values()))
    check("model info present", "model_info" in analysis)

    r = client.get("/api/recommendation")
    rec = r.get_json()
    check("recommendation produced", r.status_code == 200, r.data)
    check("a rule fired", bool(rec.get("rule")), rec)
    check("reasoning is human readable", len(rec.get("reasoning", "")) > 30)
    check("retrieval brief attached", bool(rec.get("retrieval_brief")))
    print("     -> rule {} chose '{}' at {}".format(
        rec.get("rule"), rec.get("focus_concept"), rec.get("recommended_difficulty")))

    r = client.post("/api/recommendation/respond", json={
        "accepted": False, "concept": "inheritance-basics", "difficulty": "Easy"})
    check("override recorded", r.status_code == 200, r.data)
    r = client.get("/api/recommendation/stats")
    check("acceptance stats available", r.get_json().get("total_decisions", 0) >= 1)

    print("\n9. Session now routes as a returning student")
    r = client.get("/api/session?generate=0")
    s2 = r.get_json()
    check("no longer a first visit", s2.get("first_visit") is False, s2.get("first_visit"))
    check("full four-agent flow", len(s2.get("pipeline_flow", [])) == 4, s2.get("pipeline_flow"))

    print("\n10. History and isolation")
    r = client.get("/api/history")
    check("history returns records", r.get_json().get("total", 0) >= 1)

    other = app.test_client()
    other.post("/api/auth/signup", json={
        "name": "Second Student", "email": "other@example.com", "password": "password123"})
    h = other.get("/api/history").get_json()
    check("other student sees no records", h.get("total") == 0, h)

    print("\n11. Every page renders for a signed-in student")
    for path in ["/dashboard", "/pipeline", "/learn", "/learn/" + concept, "/quiz",
                 "/quiz/attempt", "/analysis", "/history", "/library", "/about"]:
        code = client.get(path).status_code
        check("GET {}".format(path), code == 200, code)

    print("\n12. Logs")
    logs = client.get("/api/logs").get_json().get("logs", [])
    check("agents wrote activity logs", len(logs) > 5, len(logs))
    check("hand-offs were logged", any(l["type"] == "handoff" for l in logs))

    print("\n" + "=" * 60)
    print("  {} passed, {} failed".format(len(PASS), len(FAIL)))
    if FAIL:
        print("  Failures: " + ", ".join(FAIL))
    print("=" * 60 + "\n")
    return 1 if FAIL else 0


def inject_quiz(concept, difficulty):
    """Build a quiz_sessions row directly so grading can be tested offline."""
    from core.concepts import MODULE_TO_LEGACY_TOPIC, module_of
    payload = {
        "concept": concept, "difficulty": difficulty, "generated_by": "smoke-test",
        "questions": [
            {"question": "Synthetic question {}".format(i),
             "options": ["a", "b", "c", "d"], "correct": i % 4,
             "explanation": "test", "concept_tags": [concept]}
            for i in range(5)
        ],
    }
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO quiz_sessions (student_id, concept, topic, difficulty, source, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (1, concept, MODULE_TO_LEGACY_TOPIC.get(module_of(concept)), difficulty,
         "smoke-test", json.dumps(payload)))
    quiz_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"quiz_session_id": quiz_id, "questions": payload["questions"]}


if __name__ == "__main__":
    sys.exit(main())
