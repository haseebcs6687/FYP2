"""
=============================================================================
EduGen - Authentication
=============================================================================
Server-side sessions, not client-supplied identity.

The FYP-1 build had a real security hole: the browser sent `student_id` with
every request, so anyone could read another student's quiz history by editing
one number in the URL. Here the student id is derived from a signed Flask
session cookie and is never accepted from the client.

  signup  -> create users row + linked students row -> log in
  login   -> verify password hash -> put user_id in the session
  logout  -> clear the session

Passwords are hashed with werkzeug's PBKDF2 implementation.
=============================================================================
"""

import re
from functools import wraps

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from core.agent_log import add_log
from core.db import get_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    def __init__(self, message, status=400):
        super(AuthError, self).__init__(message)
        self.message = message
        self.status = status


# ─────────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────────
def current_user():
    """Return the logged-in user dict, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    row = conn.execute(
        """SELECT u.id AS user_id, u.name, u.email, s.id AS student_id
           FROM users u
           LEFT JOIN students s ON s.user_id = u.id
           WHERE u.id = ?""",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        session.clear()
        return None
    return {
        "user_id": row["user_id"],
        "student_id": row["student_id"],
        "name": row["name"],
        "email": row["email"],
    }


def current_student_id():
    user = current_user()
    return user["student_id"] if user else None


def login_required(view):
    """Protect a page route. Unauthenticated visitors go to the login page."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("pages.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def api_login_required(view):
    """Protect a JSON route. Unauthenticated callers get 401 JSON."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Sign in to continue", "code": "unauthenticated"}), 401
        return view(*args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────────────────────
# Operations
# ─────────────────────────────────────────────────────────────
def signup(name, email, password):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""

    if len(name) < 2:
        raise AuthError("Enter your full name.")
    if not EMAIL_RE.match(email):
        raise AuthError("That email address does not look valid.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError("Use at least {} characters for your password.".format(MIN_PASSWORD_LENGTH))

    conn = get_db()
    cur = conn.cursor()
    if cur.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,)).fetchone():
        conn.close()
        raise AuthError("That email is already registered. Sign in instead.")

    cur.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash(password)),
    )
    user_id = cur.lastrowid
    cur.execute("INSERT INTO students (name, user_id) VALUES (?, ?)", (name, user_id))
    student_id = cur.lastrowid
    conn.commit()
    conn.close()

    _start_session(user_id, name, student_id)
    add_log("Coordinator", "New account created for {} (student #{})".format(name, student_id),
            "success")
    return {"user_id": user_id, "student_id": student_id, "name": name, "email": email}


def login(email, password):
    email = (email or "").strip().lower()
    conn = get_db()
    cur = conn.cursor()
    user = cur.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()

    if not user or not check_password_hash(user["password_hash"], password or ""):
        conn.close()
        raise AuthError("Email or password is incorrect.", status=401)

    student = cur.execute("SELECT id FROM students WHERE user_id = ?", (user["id"],)).fetchone()
    if student:
        student_id = student["id"]
    else:
        cur.execute("INSERT INTO students (name, user_id) VALUES (?, ?)",
                    (user["name"], user["id"]))
        student_id = cur.lastrowid
        conn.commit()
    conn.close()

    _start_session(user["id"], user["name"], student_id)
    add_log("Coordinator", "{} signed in (student #{})".format(user["name"], student_id))
    return {"user_id": user["id"], "student_id": student_id,
            "name": user["name"], "email": user["email"]}


def logout():
    user = current_user()
    session.clear()
    if user:
        add_log("Coordinator", "{} signed out".format(user["name"]))


def _start_session(user_id, name, student_id):
    session.clear()
    session["user_id"] = user_id
    session["student_id"] = student_id
    session["name"] = name
    session.permanent = True
