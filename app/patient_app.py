"""The PATIENT's own web address.

A second local server (and a second Cloudflare link) that exposes ONLY what
the patient's phone needs. The caregiver dashboard, settings and data APIs
simply don't exist on this address. It shares the same database, so alerts
and the assistant work exactly as before.
"""

from __future__ import annotations

from .main import app as _main

from .patient_paths import ALLOWED_EXACT, ALLOWED_PREFIXES, _NOT_HERE  # noqa: E402


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        # The main server already runs the background jobs (Telegram, checks).
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return await _main(scope, receive, send)
    path = scope.get("path", "/")
    if path == "/":
        scope = dict(scope, path="/patient", raw_path=b"/patient")
        return await _main(scope, receive, send)
    if path in ALLOWED_EXACT or path.startswith(ALLOWED_PREFIXES):
        return await _main(scope, receive, send)
    status = 404
    body = _NOT_HERE if not path.startswith("/api/") else b'{"detail":"not available on the patient link"}'
    ctype = b"text/html; charset=utf-8" if not path.startswith("/api/") else b"application/json"
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", ctype), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
