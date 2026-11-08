"""
=============================================================================
EduGen - Security: CSRF Protection & Rate Limiting
=============================================================================
Provides:
  - Per-session CSRF token generation and validation.
  - Token rotation on login and logout.
  - Enforcement hook for all state-changing HTTP methods on /api/*.
  - Thread-safe, in-memory rate limiting with injectable clock for:
      * Failed login attempts per (IP, email)
      * Global failed logins per IP
      * Account signups per IP
=============================================================================
"""

import hmac
import secrets
import threading
import time
from flask import jsonify, request, session


# ─────────────────────────────────────────────────────────────
# CSRF Protection
# ─────────────────────────────────────────────────────────────

def get_csrf_token():
    """Retrieve the current session CSRF token, or create one if absent."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def rotate_csrf_token():
    """Generate and store a new CSRF token in the session."""
    token = secrets.token_urlsafe(32)
    session["_csrf_token"] = token
    return token


def verify_csrf_token(header_token):
    """Return True if header_token matches the current session token."""
    sess_token = session.get("_csrf_token")
    if not sess_token or not header_token:
        return False
    return hmac.compare_digest(str(header_token), str(sess_token))


def csrf_protect_before_request():
    """
    Flask before_request hook.
    Enforces valid X-CSRF-Token header on all state-changing methods to /api/*.
    Returns 403 JSON {"error": "csrf"} on missing or mismatched token.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.path.startswith("/api/"):
            header_token = request.headers.get("X-CSRF-Token", "")
            if not verify_csrf_token(header_token):
                return jsonify({"error": "csrf"}), 403
    return None


# ─────────────────────────────────────────────────────────────
# Login & Signup Rate Limiting
# ─────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Thread-safe in-memory rate limiter with injectable clock.
    Tracks:
      1. Failed logins per (client_ip, email): max 5 in 10 minutes (600s)
      2. Global failed logins per client_ip: max 20 in 10 minutes (600s)
      3. Signups per client_ip: max 10 in 1 hour (3600s)
    """

    LOGIN_WINDOW = 600       # 10 minutes
    LOGIN_MAX_FAILURES = 5   # per (ip, email)
    GLOBAL_LOGIN_MAX = 20    # per ip
    SIGNUP_WINDOW = 3600     # 1 hour
    SIGNUP_MAX = 10          # per ip

    def __init__(self, time_fn=None):
        self._time_fn = time_fn or time.time
        self._lock = threading.Lock()
        self._login_failures = {}         # (ip, email) -> [ts, ...]
        self._global_login_failures = {}  # ip -> [ts, ...]
        self._signups = {}                # ip -> [ts, ...]

    def set_time_fn(self, time_fn):
        with self._lock:
            self._time_fn = time_fn

    def _now(self):
        return self._time_fn()

    def _prune(self, timestamps, window, now):
        cutoff = now - window
        return [ts for ts in timestamps if ts > cutoff]

    def check_login(self, client_ip, email):
        """
        Check if login attempt is allowed.
        Returns (allowed: bool, retry_after: int).
        """
        ip = (client_ip or "127.0.0.1").strip()
        norm_email = (email or "").strip().lower()
        now = self._now()

        with self._lock:
            # 1. Check global IP limit
            global_attempts = self._prune(
                self._global_login_failures.get(ip, []), self.LOGIN_WINDOW, now
            )
            self._global_login_failures[ip] = global_attempts
            if len(global_attempts) >= self.GLOBAL_LOGIN_MAX:
                oldest = global_attempts[0]
                retry_after = max(1, int(oldest + self.LOGIN_WINDOW - now))
                return False, retry_after

            # 2. Check (IP, email) limit
            key = (ip, norm_email)
            attempts = self._prune(
                self._login_failures.get(key, []), self.LOGIN_WINDOW, now
            )
            self._login_failures[key] = attempts
            if len(attempts) >= self.LOGIN_MAX_FAILURES:
                oldest = attempts[0]
                retry_after = max(1, int(oldest + self.LOGIN_WINDOW - now))
                return False, retry_after

            return True, 0

    def record_login_failure(self, client_ip, email):
        """Record a failed login attempt for (ip, email) and global IP."""
        ip = (client_ip or "127.0.0.1").strip()
        norm_email = (email or "").strip().lower()
        now = self._now()

        with self._lock:
            key = (ip, norm_email)
            attempts = self._prune(
                self._login_failures.get(key, []), self.LOGIN_WINDOW, now
            )
            attempts.append(now)
            self._login_failures[key] = attempts

            global_attempts = self._prune(
                self._global_login_failures.get(ip, []), self.LOGIN_WINDOW, now
            )
            global_attempts.append(now)
            self._global_login_failures[ip] = global_attempts

    def record_login_success(self, client_ip, email):
        """Successful login clears the (ip, email) failure count."""
        ip = (client_ip or "127.0.0.1").strip()
        norm_email = (email or "").strip().lower()
        key = (ip, norm_email)
        with self._lock:
            self._login_failures.pop(key, None)

    def check_signup(self, client_ip):
        """
        Check if signup attempt is allowed.
        Returns (allowed: bool, retry_after: int).
        """
        ip = (client_ip or "127.0.0.1").strip()
        now = self._now()

        with self._lock:
            attempts = self._prune(
                self._signups.get(ip, []), self.SIGNUP_WINDOW, now
            )
            self._signups[ip] = attempts
            if len(attempts) >= self.SIGNUP_MAX:
                oldest = attempts[0]
                retry_after = max(1, int(oldest + self.SIGNUP_WINDOW - now))
                return False, retry_after
            return True, 0

    def record_signup(self, client_ip):
        """Record a successful signup from this IP."""
        ip = (client_ip or "127.0.0.1").strip()
        now = self._now()
        with self._lock:
            attempts = self._prune(
                self._signups.get(ip, []), self.SIGNUP_WINDOW, now
            )
            attempts.append(now)
            self._signups[ip] = attempts

    def reset(self):
        """Reset all rate limiter counters (useful for test isolation)."""
        with self._lock:
            self._login_failures.clear()
            self._global_login_failures.clear()
            self._signups.clear()


# Module-level default instance
default_limiter = RateLimiter()

def check_login_rate_limit(ip, email):
    return default_limiter.check_login(ip, email)

def record_login_failure(ip, email):
    default_limiter.record_login_failure(ip, email)

def record_login_success(ip, email):
    default_limiter.record_login_success(ip, email)

def check_signup_rate_limit(ip):
    return default_limiter.check_signup(ip)

def record_signup(ip):
    default_limiter.record_signup(ip)

def reset_rate_limits():
    default_limiter.reset()
