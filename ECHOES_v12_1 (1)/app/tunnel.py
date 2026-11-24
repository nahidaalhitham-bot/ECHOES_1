"""Automatic public HTTPS address for the live-location link.

The live link sent to Telegram must open on ANY phone, not only on the laptop.
`127.0.0.1` links are useless to a family member, so the app needs a public
HTTPS hostname. Order of preference:

1. ECHOES_PUBLIC_URL / RENDER_EXTERNAL_URL (a real deployment or run_public.py)
2. A Cloudflare Quick Tunnel started automatically by the app itself.
   `cloudflared` is looked up on PATH, then in app/bin/; if missing on
   Windows or Linux it is downloaded once from Cloudflare's GitHub releases.

Safety rules kept from run_public.py:
- no tunnel while first-owner registration is still open (no account yet)
- no tunnel in DEMO mode
- ECHOES_AUTO_TUNNEL=0 disables this module completely
"""

from __future__ import annotations

import os
import platform
import queue
import re
import shutil
import stat
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
BIN_DIR = Path(__file__).resolve().parent / "bin"
RELEASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"

_lock = threading.Lock()
_state: dict = {"status": "idle", "url": None, "detail": "", "proc": None}


def _env_url() -> str | None:
    for key in ("ECHOES_PUBLIC_URL", "RENDER_EXTERNAL_URL"):
        v = (os.environ.get(key) or "").strip().rstrip("/")
        if v.startswith("https://"):
            return v
    return None


def enabled() -> bool:
    # The simulated demo may be published on purpose (fictional data only):
    # run_demo_public_windows.bat sets ECHOES_DEMO_PUBLIC=1.
    demo_ok = (os.environ.get("ECHEOS_DEMO", "0") != "1"
               or os.environ.get("ECHOES_DEMO_PUBLIC", "0") == "1")
    return os.environ.get("ECHOES_AUTO_TUNNEL", "1") != "0" and demo_ok


def status() -> dict:
    url = public_base()
    return {
        "public_url": url,
        "status": "ready" if url else _state["status"],
        "source": ("env" if _env_url() else ("tunnel" if url else None)),
        "detail": _state["detail"],
        "auto_enabled": enabled(),
    }


def public_base(wait_seconds: float = 0) -> str | None:
    """The public https base URL, or None. Optionally wait for a starting tunnel."""
    env = _env_url()
    if env:
        return env
    end = time.time() + max(0.0, wait_seconds)
    while True:
        if _state["url"]:
            return _state["url"]
        if _state["status"] not in ("starting", "downloading") or time.time() >= end:
            return None
        time.sleep(0.5)


def _asset_name() -> str | None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else (
        "386" if machine in ("i386", "i686", "x86") else "amd64")
    if system == "windows":
        return f"cloudflared-windows-{arch}.exe"
    if system == "linux":
        return f"cloudflared-linux-{arch}"
    return None  # macOS ships as .tgz — install with: brew install cloudflared


def _find_binary() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    for name in ("cloudflared.exe", "cloudflared"):
        p = BIN_DIR / name
        if p.exists():
            return str(p)
    return None


def _download_binary() -> str | None:
    asset = _asset_name()
    if not asset:
        _state["detail"] = ("cloudflared غير مثبت. على macOS: brew install cloudflared")
        return None
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = BIN_DIR / ("cloudflared.exe" if asset.endswith(".exe") else "cloudflared")
    tmp = target.with_suffix(target.suffix + ".part")
    _state["status"] = "downloading"
    _state["detail"] = "جارٍ تنزيل cloudflared (مرة واحدة فقط)…"
    try:
        try:
            import certifi, ssl  # noqa: E401
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = None
        with urllib.request.urlopen(RELEASE + asset, timeout=120, context=ctx) as r, \
                open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(target)
        target.chmod(target.stat().st_mode | stat.S_IEXEC)
        return str(target)
    except Exception as e:  # noqa: BLE001
        _state["detail"] = f"تعذّر تنزيل cloudflared: {type(e).__name__}"
        try:
            tmp.unlink()
        except OSError:
            pass
        return None


def _run(port: int) -> None:
    binary = _find_binary() or _download_binary()
    if not binary:
        _state["status"] = "failed"
        return
    _state["status"] = "starting"
    _state["detail"] = "جارٍ فتح الرابط العام…"
    flags = 0
    if platform.system().lower() == "windows":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [binary, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )
    except Exception as e:  # noqa: BLE001
        _state["status"] = "failed"
        _state["detail"] = f"تعذّر تشغيل cloudflared: {type(e).__name__}"
        return
    _state["proc"] = proc
    lines: queue.Queue[str] = queue.Queue()

    def pump():
        for line in proc.stdout or []:
            lines.put(line)
    threading.Thread(target=pump, daemon=True).start()

    deadline = time.time() + 60
    while time.time() < deadline and proc.poll() is None:
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            continue
        m = URL_RE.search(line)
        if m:
            url = m.group(0).rstrip("/")
            _state.update(status="ready", url=url, detail="")
            try:   # paired watches learn the new address automatically
                from . import watch_relay
                watch_relay.announce_url(url)
            except Exception:
                pass
            print(f"\n  🌐 الرابط العام (للروابط المرسلة في تيليجرام): {url}\n", flush=True)
            # Keep draining output so the pipe never blocks the tunnel.
            return
    _state["status"] = "failed"
    _state["detail"] = "لم يُفتح الرابط العام خلال 60 ثانية — تحققي من الإنترنت"
    if proc.poll() is None:
        proc.terminate()


def start_async(port: int | None = None) -> None:
    """Start the tunnel in the background once. Safe to call repeatedly."""
    if not enabled() or _env_url():
        return
    from . import auth
    try:
        if auth.count_users() == 0:
            _state["detail"] = "أنشئي حساب المسؤول أولًا ثم سيُفتح الرابط العام تلقائيًا"
            return
    except Exception:
        return
    with _lock:
        if _state["status"] in ("starting", "downloading", "ready"):
            return
        _state["status"] = "starting"
    port = port or int(os.environ.get("ECHEOS_PORT", "8765"))
    threading.Thread(target=_run, args=(port,), daemon=True).start()


def stop() -> None:
    proc = _state.get("proc")
    if proc is not None and proc.poll() is None:
        proc.terminate()
    _state.update(status="idle", url=None, proc=None)
