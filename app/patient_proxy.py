"""The patient app as its own web service (for Render / any host).

It holds no data. It shows the patient screen and passes the few requests the
patient's phone needs to the main ECHOES service (MAIN_URL). Everything else —
the caregiver dashboard, settings, data — does not exist on this address.

Run:  uvicorn app.patient_proxy:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import os

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from .patient_paths import ALLOWED_EXACT, ALLOWED_PREFIXES, _NOT_HERE


def _main_url() -> str:
    v = (os.environ.get("MAIN_URL") or "").strip().rstrip("/")
    if v and not v.startswith("http"):
        v = "https://" + (v if "." in v else v + ".onrender.com")
    return v


_client = httpx.AsyncClient(timeout=60, follow_redirects=False)
HOP = {"host", "content-length", "connection", "transfer-encoding", "content-encoding", "keep-alive"}


async def proxy(request: Request) -> Response:
    path = request.url.path
    if path == "/":
        path = "/patient"
    if not (path in ALLOWED_EXACT or path.startswith(ALLOWED_PREFIXES)):
        if path.startswith("/api/"):
            return Response(b'{"detail":"not available on the patient link"}', 404,
                            media_type="application/json")
        return HTMLResponse(_NOT_HERE, 404)
    main = _main_url()
    if not main:
        return HTMLResponse("<h3>MAIN_URL is not set</h3>", 500)
    url = main + path + (("?" + request.url.query) if request.url.query else "")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers.pop("cookie", None)   # the patient app never carries a caregiver session
    r = await _client.request(request.method, url, headers=headers, content=await request.body())
    out = {k: v for k, v in r.headers.items() if k.lower() not in HOP and k.lower() != "set-cookie"}
    return Response(r.content, r.status_code, headers=out)


async def health(_: Request) -> Response:
    return Response(b"ok")


app = Starlette(routes=[
    Route("/healthz", health),
    Route("/{path:path}", proxy, methods=["GET", "POST", "PUT", "DELETE"]),
])
