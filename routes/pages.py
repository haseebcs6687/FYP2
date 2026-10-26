"""
=============================================================================
EduGen - Page Routes
=============================================================================
Server-rendered pages. Each screen is its own URL so the flow is readable,
linkable and demonstrable - FYP-1 was a single-page app where every screen
lived at "/".

  /                 landing
  /signup /login    authentication
  /dashboard        session start, agent status
  /pipeline         the live agent pipeline: analysis -> decision -> content
  /learn            concept library (8 modules, 44 concepts)
  /learn/<concept>  one lesson, generated and grounded
  /quiz             quiz setup
  /quiz/attempt     quiz in progress
  /quiz/result/<id> marked quiz with explanations
  /analysis         mastery report
  /history          every past attempt
  /library          knowledge base explorer (search the RAG corpus)
  /about            architecture explainer for the evaluator
=============================================================================
"""

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from core.auth import current_user, login_required
from core.concepts import CONCEPTS, DIFFICULTIES, MODULES, concept_title, module_summary

bp = Blueprint("pages", __name__)


def _ctx(**kwargs):
    base = {
        "user": current_user(),
        "show_logs": current_app.config.get("SHOW_LOGS", True),
        "modules": module_summary(),
        "difficulties": DIFFICULTIES,
    }
    base.update(kwargs)
    return base


@bp.route("/")
def index():
    if current_user():
        return redirect(url_for("pages.dashboard"))
    return render_template("index.html", **_ctx(page="home"))


@bp.route("/signup")
def signup():
    if current_user():
        return redirect(url_for("pages.dashboard"))
    return render_template("signup.html", **_ctx(page="signup"))


@bp.route("/login")
def login():
    if current_user():
        return redirect(url_for("pages.dashboard"))
    return render_template("login.html", **_ctx(page="login", next_url=request.args.get("next", "")))


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", **_ctx(page="dashboard"))


@bp.route("/pipeline")
@login_required
def pipeline():
    return render_template("pipeline.html", **_ctx(page="pipeline"))


@bp.route("/learn")
@login_required
def learn():
    return render_template("learn.html", **_ctx(page="learn"))


@bp.route("/learn/<concept>")
@login_required
def learn_concept(concept):
    if concept not in CONCEPTS:
        return redirect(url_for("pages.learn"))
    meta = CONCEPTS[concept]
    return render_template(
        "lesson.html",
        **_ctx(page="learn",
               concept=concept,
               concept_meta=meta,
               concept_title=concept_title(concept),
               module=MODULES.get(meta["module"]),
               difficulty=request.args.get("difficulty", "Easy"))
    )


@bp.route("/quiz")
@login_required
def quiz():
    return render_template(
        "quiz_setup.html",
        **_ctx(page="quiz",
               preselect_concept=request.args.get("concept", ""),
               preselect_difficulty=request.args.get("difficulty", ""))
    )


@bp.route("/quiz/attempt")
@login_required
def quiz_attempt():
    return render_template("quiz_attempt.html", **_ctx(page="quiz"))


@bp.route("/quiz/result/<int:result_id>")
@login_required
def quiz_result(result_id):
    return render_template("quiz_result.html", **_ctx(page="quiz", result_id=result_id))


@bp.route("/analysis")
@login_required
def analysis():
    return render_template("analysis.html", **_ctx(page="analysis"))


@bp.route("/history")
@login_required
def history():
    return render_template("history.html", **_ctx(page="history"))


@bp.route("/library")
@login_required
def library():
    return render_template("library.html", **_ctx(page="library"))


@bp.route("/about")
def about():
    return render_template("about.html", **_ctx(page="about"))
