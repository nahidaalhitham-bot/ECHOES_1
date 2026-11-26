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
    for key in ("ECHOES_PUBLIC_URL", "RENDER_EXTERNAL_URL", "RAILWAY_PUBLIC_DOMAIN"):
        v = (os.environ.get(key) or "").strip().rstrip("/")
        if v and not v.startswith("http") and "." in v:
            v = "https://" + v
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
            start_patient_async(binary)   # the patient app gets its own address
            try:   # watches + family (Telegram) learn the new address
                from . import announce
                announce.public_url_ready(url)
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


# ---------------------------------------------------------------------------
# Second, separate address for the PATIENT app (app/patient_app.py).
_patient: dict = {"status": "idle", "url": None, "proc": None}


def patient_base(wait_seconds: float = 0) -> str | None:
    v = (os.environ.get("ECHOES_PATIENT_URL") or "").strip().rstrip("/")
    if v and not v.startswith("http"):
        v = "https://" + (v if "." in v else v + ".onrender.com")
    if v.startswith("https://"):
        return v
    end = time.time() + max(0.0, wait_seconds)
    while True:
        if _patient["url"]:
            return _patient["url"]
        if _patient["status"] != "starting" or time.time() >= end:
            return None
        time.sleep(0.5)


def _free_port(start: int = 8800) -> int:
    import socket
    for port in range(start, start + 60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port")


def _run_patient(binary: str | None) -> None:
    try:
        import uvicorn
        from .patient_app import app as patient_asgi
        port = _free_port()
        srv = uvicorn.Server(uvicorn.Config(patient_asgi, host="127.0.0.1", port=port,
                                            log_level="warning", lifespan="on"))
        threading.Thread(target=srv.run, daemon=True).start()
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                    break
            except Exception:
                time.sleep(0.3)
        binary = binary or _find_binary() or _download_binary()
        if not binary:
            _patient["status"] = "failed"; return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system().lower() == "windows" else 0
        proc = subprocess.Popen(
            [binary, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=flags)
        _patient["proc"] = proc
        deadline = time.time() + 60
        for line in proc.stdout or []:
            m = URL_RE.search(line)
            if m:
                url = m.group(0).rstrip("/")
                _patient.update(status="ready", url=url)
                os.environ["ECHOES_PATIENT_URL"] = url
                print(f"\n  👴 رابط تطبيق المريض (منفصل): {url}\n", flush=True)
                threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
                return
            if time.time() > deadline:
                break
        _patient["status"] = "failed"
    except Exception as e:  # noqa: BLE001
        _patient["status"] = "failed"
        print("patient link:", e, flush=True)


def start_patient_async(binary: str | None = None) -> None:
    """Open the patient app's own public address (once)."""
    with _lock:
        if _patient["status"] in ("starting", "ready"):
            return
        _patient["status"] = "starting"
    threading.Thread(target=_run_patient, args=(binary,), daemon=True).start()


def stop() -> None:
    for st in (_state, _patient):
        proc = st.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate()
    _state.update(status="idle", url=None, proc=None)
    _patient.update(status="idle", url=None, proc=None)
