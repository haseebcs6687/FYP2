"""
=============================================================================
EduGen - Test CSRF Helper (scripts/test_csrf_helper.py)
=============================================================================
Utility functions for Flask test clients to automatically retrieve and attach
valid X-CSRF-Token headers to state-changing HTTP requests.
=============================================================================
"""


def get_csrf_token(client):
    """Retrieve a valid CSRF token from the test client session."""
    res = client.get("/api/csrf-token")
    if res.status_code == 200:
        data = res.get_json() or {}
        return data.get("csrf_token")
    return None


def csrf_headers(client, extra=None):
    """Return dictionary with X-CSRF-Token merged with any extra headers."""
    headers = dict(extra or {})
    token = get_csrf_token(client)
    if token:
        headers["X-CSRF-Token"] = token
    return headers


def csrf_post(client, path, **kwargs):
    """Execute client.post() with valid X-CSRF-Token header."""
    headers = csrf_headers(client, kwargs.pop("headers", None))
    return client.post(path, headers=headers, **kwargs)


def csrf_put(client, path, **kwargs):
    """Execute client.put() with valid X-CSRF-Token header."""
    headers = csrf_headers(client, kwargs.pop("headers", None))
    return client.put(path, headers=headers, **kwargs)


def csrf_delete(client, path, **kwargs):
    """Execute client.delete() with valid X-CSRF-Token header."""
    headers = csrf_headers(client, kwargs.pop("headers", None))
    return client.delete(path, headers=headers, **kwargs)
