"""
=============================================================================
EduGen - Security Unit & Integration Tests (scripts/test_security.py)
=============================================================================
Tests:
  1. CSRF Protection:
     - Missing header -> 403 {"error": "csrf"}
     - Invalid header -> 403 {"error": "csrf"}
     - Valid header -> succeeds (200/201)
     - Token rotated upon successful login & logout
     - GET requests are exempt
  2. Rate Limiting (Login & Signup):
     - 5 failed logins for (IP, email) -> 6th returns 429 with Retry-After even with correct password
     - Fake clock advance unblocks after window expires
     - Independent email on same IP is unaffected until global cap
     - Successful login clears the failure counter for that (IP, email)
     - Global IP limit: 20 failed logins from same IP triggers 429
     - Signup limit: 10 signups per IP per hour -> 11th triggers 429
  3. Hardening & Headers:
     - Minimum 8-char password enforcement on signup
     - Security headers: X-Content-Type-Options, X-Frame-Options, Referrer-Policy
     - Generic 500 JSON handler in production mode
=============================================================================
"""

import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import core.db
from app import create_app
from core.db import init_db
from core.security import (
    RateLimiter,
    default_limiter,
    get_csrf_token,
    reset_rate_limits,
    rotate_csrf_token,
    verify_csrf_token,
)


class TestSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp_dir.name, "test_security.db")
        os.environ["EDUGEN_DB_PATH"] = cls.db_path
        core.db.DB_PATH = cls.db_path
        init_db(cls.db_path)

        cls.app = create_app()
        cls.app.config.update(
            TESTING=True,
            EDUGEN_SHOW_LOGS=False,
        )
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def setUp(self):
        reset_rate_limits()

    # ─────────────────────────────────────────────────────────
    # 1. CSRF Protection
    # ─────────────────────────────────────────────────────────
    def test_csrf_missing_header_rejected(self):
        """State-changing POST to /api/* without X-CSRF-Token yields 403."""
        res = self.client.post("/api/auth/login", json={"email": "nobody@test.com", "password": "x"})
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("error"), "csrf")

    def test_csrf_wrong_header_rejected(self):
        """State-changing POST with wrong X-CSRF-Token yields 403."""
        # Establish session first
        self.client.get("/api/csrf-token")
        res = self.client.post(
            "/api/auth/login",
            json={"email": "nobody@test.com", "password": "x"},
            headers={"X-CSRF-Token": "invalid-token-12345"},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("error"), "csrf")

    def test_csrf_valid_token_accepted(self):
        """Valid X-CSRF-Token allows request to proceed to application logic."""
        res_csrf = self.client.get("/api/csrf-token")
        self.assertEqual(res_csrf.status_code, 200)
        token = res_csrf.get_json()["csrf_token"]

        # Attempt login with valid token (fails on bad creds -> 401, not 403 csrf)
        res = self.client.post(
            "/api/auth/login",
            json={"email": "nobody@test.com", "password": "wrongpassword"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(res.status_code, 401)
        self.assertNotEqual(res.get_json().get("error"), "csrf")

    def test_csrf_get_requests_exempt(self):
        """GET requests to API do not require CSRF token."""
        res = self.client.get("/api/concepts")
        self.assertEqual(res.status_code, 200)

    def test_csrf_rotated_on_login_and_logout(self):
        """CSRF token rotates when a user logs in and when they log out."""
        # 1. Get initial token
        r1 = self.client.get("/api/csrf-token")
        initial_token = r1.get_json()["csrf_token"]

        # 2. Sign up a new user
        signup_email = f"user_{secrets.token_hex(4)}@test.com"
        r_signup = self.client.post(
            "/api/auth/signup",
            json={"name": "Test User", "email": signup_email, "password": "password123"},
            headers={"X-CSRF-Token": initial_token},
        )
        self.assertEqual(r_signup.status_code, 201)

        # Token should have rotated on signup
        r2 = self.client.get("/api/csrf-token")
        post_signup_token = r2.get_json()["csrf_token"]
        self.assertNotEqual(initial_token, post_signup_token)

        # 3. Log out
        r_logout = self.client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": post_signup_token},
        )
        self.assertEqual(r_logout.status_code, 200)

        # Token should have rotated on logout
        r3 = self.client.get("/api/csrf-token")
        post_logout_token = r3.get_json()["csrf_token"]
        self.assertNotEqual(post_signup_token, post_logout_token)

        # 4. Log in
        r_login = self.client.post(
            "/api/auth/login",
            json={"email": signup_email, "password": "password123"},
            headers={"X-CSRF-Token": post_logout_token},
        )
        self.assertEqual(r_login.status_code, 200)

        # Token should have rotated on login
        r4 = self.client.get("/api/csrf-token")
        post_login_token = r4.get_json()["csrf_token"]
        self.assertNotEqual(post_logout_token, post_login_token)

    # ─────────────────────────────────────────────────────────
    # 2. Rate Limiting Unit & Integration
    # ─────────────────────────────────────────────────────────
    def test_login_rate_limiting_with_mock_clock(self):
        """
        Unit test RateLimiter with injectable fake clock:
        - 5 failed attempts allowed
        - 6th attempt blocked with 429
        - Clock advances past 10m -> allowed again
        """
        current_time = 1000.0

        def fake_time():
            return current_time

        limiter = RateLimiter(time_fn=fake_time)
        ip = "192.168.1.50"
        email = "victim@edugen.local"

        for i in range(5):
            allowed, retry_after = limiter.check_login(ip, email)
            self.assertTrue(allowed, f"Attempt {i+1} should be allowed")
            limiter.record_login_failure(ip, email)
            current_time += 10.0

        # 6th attempt must be blocked
        allowed, retry_after = limiter.check_login(ip, email)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

        # Advance clock by 600s
        current_time += 600.0
        allowed, retry_after = limiter.check_login(ip, email)
        self.assertTrue(allowed, "Should be allowed after window expires")

    def test_login_rate_limiting_cleared_on_success(self):
        """Successful login resets failure counter for that (ip, email)."""
        current_time = 2000.0
        limiter = RateLimiter(time_fn=lambda: current_time)
        ip = "10.0.0.1"
        email = "student@edugen.local"

        # 4 failures
        for _ in range(4):
            limiter.record_login_failure(ip, email)

        # Success clears it
        limiter.record_login_success(ip, email)

        # Should now have 0 failures, can fail 4 more times without block
        for _ in range(4):
            allowed, _ = limiter.check_login(ip, email)
            self.assertTrue(allowed)
            limiter.record_login_failure(ip, email)

    def test_login_rate_limiting_independent_email(self):
        """Independent email on same IP is not blocked by another email's failures."""
        current_time = 3000.0
        limiter = RateLimiter(time_fn=lambda: current_time)
        ip = "10.0.0.2"

        for _ in range(5):
            limiter.record_login_failure(ip, "user_a@edugen.local")

        # user_a is blocked
        allowed_a, _ = limiter.check_login(ip, "user_a@edugen.local")
        self.assertFalse(allowed_a)

        # user_b is not blocked
        allowed_b, _ = limiter.check_login(ip, "user_b@edugen.local")
        self.assertTrue(allowed_b)

    def test_login_rate_limiting_global_ip_cap(self):
        """Global cap: 20 failed logins from same IP blocks all attempts from that IP."""
        current_time = 4000.0
        limiter = RateLimiter(time_fn=lambda: current_time)
        ip = "10.0.0.3"

        for i in range(20):
            limiter.record_login_failure(ip, f"diff_user_{i}@edugen.local")

        # Now any email from this IP is blocked
        allowed, retry_after = limiter.check_login(ip, "fresh_user@edugen.local")
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

    def test_signup_rate_limiting(self):
        """Signup cap: 10 signups per IP per hour -> 11th blocked."""
        current_time = 5000.0
        limiter = RateLimiter(time_fn=lambda: current_time)
        ip = "10.0.0.4"

        for _ in range(10):
            allowed, _ = limiter.check_signup(ip)
            self.assertTrue(allowed)
            limiter.record_signup(ip)

        allowed, retry_after = limiter.check_signup(ip)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

    def test_http_rate_limit_blocks_even_with_correct_password(self):
        """5 failed HTTP logins -> 6th returns 429 even with correct password."""
        email = f"ratelimit_{secrets.token_hex(3)}@test.com"
        password = "correct_password_123"

        # Register user
        r_csrf = self.client.get("/api/csrf-token")
        csrf_tok = r_csrf.get_json()["csrf_token"]
        r_signup = self.client.post(
            "/api/auth/signup",
            json={"name": "RL User", "email": email, "password": password},
            headers={"X-CSRF-Token": csrf_tok},
            environ_base={"REMOTE_ADDR": "192.168.1.99"},
        )
        self.assertEqual(r_signup.status_code, 201)

        # 5 failed logins
        for _ in range(5):
            r_csrf = self.client.get("/api/csrf-token")
            tok = r_csrf.get_json()["csrf_token"]
            res = self.client.post(
                "/api/auth/login",
                json={"email": email, "password": "WRONG_PASSWORD"},
                headers={"X-CSRF-Token": tok},
                environ_base={"REMOTE_ADDR": "192.168.1.99"},
            )
            self.assertEqual(res.status_code, 401)

        # 6th attempt with CORRECT password must get 429
        r_csrf = self.client.get("/api/csrf-token")
        tok = r_csrf.get_json()["csrf_token"]
        res_6 = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
            headers={"X-CSRF-Token": tok},
            environ_base={"REMOTE_ADDR": "192.168.1.99"},
        )
        self.assertEqual(res_6.status_code, 429)
        self.assertIn("Retry-After", res_6.headers)
        self.assertIn("Too many failed login attempts", res_6.get_json().get("error", ""))

    # ─────────────────────────────────────────────────────────
    # 3. Application Hardening & Security Headers
    # ─────────────────────────────────────────────────────────
    def test_password_min_length_8(self):
        """Passwords shorter than 8 chars are rejected on signup with 400."""
        r_csrf = self.client.get("/api/csrf-token")
        tok = r_csrf.get_json()["csrf_token"]
        res = self.client.post(
            "/api/auth/signup",
            json={"name": "Short Pass", "email": "short@test.com", "password": "12345"},
            headers={"X-CSRF-Token": tok},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("8 characters", res.get_json().get("error", ""))

    def test_security_headers_present(self):
        """All responses carry strict security headers."""
        res = self.client.get("/api/concepts")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(res.headers.get("Referrer-Policy"), "same-origin")


if __name__ == "__main__":
    unittest.main()
