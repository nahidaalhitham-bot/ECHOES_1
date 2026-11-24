"""Run ECHOES on this laptop and expose it through a temporary HTTPS tunnel.

The laptop remains the server. Cloudflare Quick Tunnel creates a temporary public
HTTPS hostname; ECHOES uses that hostname for expiring, read-only live-location
links sent on safe-zone exit. The app itself binds only to localhost.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import webbrowser

import uvicorn

DEFAULT_PORT = 8765
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)


def free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("لم أجد منفذًا محليًا متاحًا.")


def wait_for_server(url: str, timeout: float = 30) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        print("cloudflared غير مثبت.")
        print("ثبتيه من PowerShell باستخدام:")
        print("  winget install --id Cloudflare.cloudflared -e")
        print("ثم افتحي هذه النافذة من جديد.")
        return 2

    port = free_port()
    # This launcher manages its own tunnel; stop the app from opening a second.
    os.environ["ECHOES_AUTO_TUNNEL"] = "0"
    local = f"http://127.0.0.1:{port}"
    config = uvicorn.Config("app.main:app", host="127.0.0.1",
                            port=port, log_level="info")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not wait_for_server(local + "/health"):
        server.should_exit = True
        print("تعذر بدء ECHOES محليًا. راجعي رسالة الخطأ أعلاه.")
        return 1

    # Never expose the first-owner registration page to the public tunnel.
    from app import auth
    if auth.count_users() == 0:
        server.should_exit = True
        print("لم يُنشأ حساب المسؤول بعد. أوقفت نشر الرابط العام.")
        print("شغّلي install_windows.bat أو run.py محليًا، أنشئي حساب المسؤول،")
        print("ثم أغلقي التطبيق وأعيدي تشغيل run_public_windows.bat.")
        return 2
    if os.environ.get("ECHEOS_DEMO", "0") == "1":
        server.should_exit = True
        print("وضع DEMO مفعّل. لا أفتح نفقًا عامًا على بيانات محاكاة.")
        print("أوقفي ECHEOS_DEMO ثم أعيدي التشغيل، واستخدمي بيانات وهمية للعرض.")
        return 2

    output: queue.Queue[str] = queue.Queue()
    tunnel = subprocess.Popen(
        [cloudflared, "tunnel", "--url", local, "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )

    def read_tunnel():
        if tunnel.stdout:
            for line in tunnel.stdout:
                output.put(line.rstrip())

    reader = threading.Thread(target=read_tunnel, daemon=True)
    reader.start()

    public_url = None
    deadline = time.time() + 60
    while time.time() < deadline and tunnel.poll() is None:
        try:
            line = output.get(timeout=0.5)
        except queue.Empty:
            continue
        print("[Cloudflare]", line)
        match = URL_RE.search(line)
        if match:
            public_url = match.group(0).rstrip("/")
            break

    if not public_url:
        print("لم أحصل على رابط عام خلال 60 ثانية.")
        print("تأكدي من اتصال الإنترنت ومن أن cloudflared يعمل.")
        tunnel.terminate()
        server.should_exit = True
        return 1

    # The notification module reads this at the time of an exit event.
    os.environ["ECHOES_PUBLIC_URL"] = public_url

    print()
    print("=" * 64)
    print("ECHOES يعمل على اللابتوب، والرابط العام عبر HTTPS:")
    print(public_url)
    print("الرابط المحلي: " + local + "/login")
    print("تنبيه: الرابط العام مؤقت وقد يتغير عند إعادة التشغيل.")
    print("رابط الموقع المباشر للمريض يُنشأ عند خروج نطاق الأمان.")
    print("استخدمي بيانات وهمية للاختبار ولا تشاركي الرابط إلا مع مسؤول مصرح.")
    print("للإيقاف: Ctrl+C")
    print("=" * 64)
    try:
        webbrowser.open(local + "/login")
        server_thread.join()
    except KeyboardInterrupt:
        print("\nإيقاف ECHOES...")
    finally:
        server.should_exit = True
        if tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
        server_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
