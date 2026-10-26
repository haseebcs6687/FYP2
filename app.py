"""
=============================================================================
EduGen - Application Factory
=============================================================================
Wires the four agents, the RAG retriever, the database and the HTTP layer
into one Flask app.

    python run.py            -> http://localhost:5000

Startup order matters: the retriever is constructed lazily (the embedding
model only loads on the first retrieval) so the server starts in under a
second even when sentence-transformers is installed.
=============================================================================
"""

import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

from agents.adaptive_content_agent import AdaptiveContentAgent      # noqa: E402
from agents.concept_clarifier_agent import ConceptClarifierAgent    # noqa: E402
from agents.coordinator_agent import CoordinatorAgent               # noqa: E402
from agents.performance_analysis_agent import PerformanceAnalysisAgent  # noqa: E402
from core.agent_log import add_log                                  # noqa: E402
from core.concepts import CONCEPTS                                  # noqa: E402
from core.db import DB_PATH, init_db                                # noqa: E402
from rag.retriever import get_retriever                             # noqa: E402
from routes.api import bp as api_bp                                 # noqa: E402
from routes.pages import bp as pages_bp                             # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    secret = os.environ.get("EDUGEN_SECRET_KEY")
    if not secret:
        secret = secrets.token_hex(32)
        print("[System] EDUGEN_SECRET_KEY not set - using a random key. "
              "Sessions will reset on restart. Set one in .env for stable logins.")
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        JSON_SORT_KEYS=False,
        SHOW_LOGS=os.environ.get("EDUGEN_SHOW_LOGS", "1") != "0",
        TEMPLATES_AUTO_RELOAD=True,
    )

    banner()
    init_db()
    print("[Database] SQLite ready at {}".format(DB_PATH))

    retriever = get_retriever()

    pa = PerformanceAnalysisAgent(log=add_log)
    ac = AdaptiveContentAgent(log=add_log)
    cc = ConceptClarifierAgent(retriever=retriever, log=add_log)
    coordinator = CoordinatorAgent(pa_agent=pa, ac_agent=ac, cc_agent=cc, retriever=retriever)

    app.extensions["edugen"] = {
        "pa": pa, "ac": ac, "cc": cc,
        "coordinator": coordinator, "retriever": retriever,
    }

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    @app.errorhandler(404)
    def not_found(_err):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Endpoint not found"}), 404
        return render_template("error.html", code=404,
                               message="That page does not exist.",
                               show_logs=app.config["SHOW_LOGS"]), 404

    @app.errorhandler(500)
    def server_error(err):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Something failed on the server", "detail": str(err)}), 500
        return render_template("error.html", code=500,
                               message="Something failed on the server.",
                               show_logs=app.config["SHOW_LOGS"]), 500

    @app.context_processor
    def inject_globals():
        return {"app_name": "EduGen", "concept_count": len(CONCEPTS)}

    startup_report(cc, retriever)
    add_log("System", "EduGen started - four agents online", "success")
    return app


def banner():
    print("\n" + "=" * 68)
    print("  EduGen - Agentic AI Learning System for Java / OOP")
    print("  FYP-2  |  COMSATS University Islamabad, Lahore Campus")
    print("=" * 68)


def startup_report(cc, retriever):
    rag = retriever.status()
    print("\n  Agents")
    print("    Coordinator .............. ready")
    print("    Performance Analysis ..... ready (concept-graph classifier)")
    print("    Adaptive Content ......... ready (6-rule policy engine)")
    print("    Concept Clarifier ........ {}".format(
        "ready (LLM: {})".format(cc.model) if cc.llm_available
        else "OFFLINE - no GROQ_API_KEY, local notes + static bank will be served"))

    print("\n  Knowledge base (RAG)")
    if rag.get("ready"):
        print("    chunks ................... {}".format(rag["chunk_count"]))
        print("    embedder ................. {}".format(rag["embedder"]))
        print("    sources .................. {}".format(len(rag.get("sources", {}))))
        print("    concepts covered ......... {}/{}".format(rag.get("covered_concepts", 0), len(CONCEPTS)))
    else:
        print("    NOT BUILT - run:  python -m rag.ingest")
        if rag.get("error"):
            print("    reason ................... {}".format(rag["error"]))

    if not cc.llm_available:
        print("\n  NOTE: all lessons and quizzes come from the Concept Clarifier Agent.")
        print("        Without GROQ_API_KEY, lessons fall back to the local concept")
        print("        notes and quizzes are unavailable. Set the key in .env.")
    print("\n  Open http://localhost:5000\n" + "=" * 68 + "\n")


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("EDUGEN_DEBUG", "1") == "1", port=5000)
