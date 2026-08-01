"""Optional HTTP Basic Auth gate, toggled by AUTH_ENABLED.

Unlike an internal debugging tool, this dashboard is the product's
public-facing deliverable (see DASHBOARD_SENTIMENT.md's "Access control"
section), so auth defaults to *off* here and is opt-in via AUTH_ENABLED
rather than always-on.
"""

from __future__ import annotations

import os
import secrets

from flask import Flask, Response, request

EXEMPT_PATHS = {"/healthz"}
TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "false").strip().lower() in TRUTHY_VALUES


def init_app(app: Flask) -> None:
    if not _auth_enabled():
        return

    @app.before_request
    def require_basic_auth():
        if request.path in EXEMPT_PATHS:
            return None

        expected_user = os.environ["BASIC_AUTH_USER"]
        expected_password = os.environ["BASIC_AUTH_PASSWORD"]

        auth = request.authorization
        if (
            auth is None
            or not secrets.compare_digest(auth.username or "", expected_user)
            or not secrets.compare_digest(auth.password or "", expected_password)
        ):
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Dashboard Sentiment"'},
            )
        return None
