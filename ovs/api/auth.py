"""Bearer-token gate.

A RunPod pod's HTTP proxy URL (`https://<podid>-8000.proxy.runpod.net`) is
public and has no auth of its own — anyone who learns the pod id reaches this
API, and it can upload files and burn GPU time. So when `OVS_AUTH_TOKEN` is set,
every request must carry it.

Blank token = open. That is the local-dev default and is only safe on
localhost; the entrypoint refuses to start a pod without one.
"""

from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

# Paths reachable without a token. `/api/health` is deliberately open so a pod
# can be probed for liveness before the token is configured; it never reveals
# more than GPU model and whether the weights are loaded.
PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    # Static frontend assets. The UI itself is not secret; every call it makes
    # still needs the token.
    return not path.startswith("/api")


def token_ok(supplied: str | None) -> bool:
    expected = settings.auth_token.strip()
    if not expected:
        return True
    # compare_digest to keep the check constant-time.
    return bool(supplied) and secrets.compare_digest(supplied, expected)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.auth_token.strip() or _is_public(request.url.path):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        supplied = header[7:].strip() if header.lower().startswith("bearer ") else None
        # The <audio> element and download links cannot set headers, so a token
        # in the query string is accepted for those GETs too.
        if supplied is None:
            supplied = request.query_params.get("token")

        if not token_ok(supplied):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid token. Set it on the Settings screen."},
            )
        return await call_next(request)
