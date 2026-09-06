"""Single-account HTTP Basic authentication for the entire application."""

import base64
import binascii
import hashlib
import hmac
import os
from dataclasses import dataclass

from fastapi.responses import JSONResponse

CHALLENGE = 'Basic realm="Matchday", charset="UTF-8"'


def auth_enabled_from_environment():
    value = os.environ.get("MATCHDAY_AUTH_ENABLED", "true").strip().lower()
    if value not in ("true", "false", "1", "0"):
        raise ValueError("MATCHDAY_AUTH_ENABLED must be true or false")
    return value in ("true", "1")


@dataclass(frozen=True)
class Credentials:
    username: bytes
    password: bytes

    @classmethod
    def from_environment(cls):
        username = os.environ.get("MATCHDAY_USERNAME", "")
        password = os.environ.get("MATCHDAY_PASSWORD", "")
        if not username or not password or ":" in username:
            return None
        return cls(
            hashlib.sha256(username.encode()).digest(), hashlib.sha256(password.encode()).digest()
        )

    def accepts(self, header):
        # Bound malformed input before decoding, and compare fixed-size digests.
        if len(header) > 8192:
            return False
        try:
            scheme, value = header.split(" ", 1)
            if scheme.lower() != "basic":
                return False
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeError, binascii.Error):
            return False
        user_ok = hmac.compare_digest(self.username, hashlib.sha256(username.encode()).digest())
        password_ok = hmac.compare_digest(self.password, hashlib.sha256(password.encode()).digest())
        return user_ok & password_ok


def access_error(request):
    if getattr(request.app.state, "auth_enabled", True):
        credentials = getattr(request.app.state, "credentials", None)
        if credentials is None:
            return JSONResponse(
                {
                    "detail": "Login is not configured. Set MATCHDAY_USERNAME and MATCHDAY_PASSWORD on the server and restart."
                },
                status_code=503,
            )
        if not credentials.accepts(request.headers.get("authorization", "")):
            return JSONResponse(
                {"detail": "Login required."},
                status_code=401,
                headers={"WWW-Authenticate": CHALLENGE},
            )
    # A cross-origin form cannot set this header. Cross-origin JS would need a
    # successful CORS preflight; the app does not enable CORS.
    if request.method not in ("GET", "HEAD", "OPTIONS") and (
        request.headers.get("x-matchday-request") != "1"
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        return JSONResponse({"detail": "Same-origin app request required."}, status_code=403)
    return None
