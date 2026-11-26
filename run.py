"""Echeos launcher — one file to start the app.

Double-click (or `python run.py`): starts the server, opens the browser,
and keeps running until you press Ctrl+C or close the window.

This is what turns the project from "a folder of Python files" into
"an application you launch".
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

HOST = os.environ.get("ECHEOS_HOST", "127.0.0.1")
DEFAULT_PORT = 8765
BANNER = """
  ╔══════════════════════════════════════════╗
  ║   Echeos — أصداء الذاكرة                  ║
  ║   echoes of memory                        ║
  ╚══════════════════════════════════════════╝
"""


def _free_port(start: int) -> int:
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    return start


def _open_later(url: str, delay: float = 2.0) -> None:
    def go():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0

    global HOST
    if os.environ.get("PORT"):   # hosting service (Railway/Render/…): listen where it says
        HOST = "0.0.0.0"
        os.environ.setdefault("ECHOES_AUTO_TUNNEL", "0")
        os.environ.setdefault("ECHOES_CLOUD", "1")
        port = int(os.environ["PORT"])
    else:
        port = _free_port(int(os.environ.get("ECHEOS_PORT", DEFAULT_PORT)))
    # The app's automatic public tunnel (app/tunnel.py) forwards to this port.
    os.environ["ECHEOS_PORT"] = str(port)
    url = f"http://{HOST}:{port}/"

    print(BANNER)
    print("  تم التشغيل. الخادم يعمل على:")
    print(f"   → لوحة التحكم   {url}dashboard  (تسجيل الدخول أولًا)")
    print(f"   → واجهة المريض   {url}")
    print(f"   → الكاميرا       {url}camera")
    print(f"   → الأمان          {url}safety")
    print()
    if os.environ.get("ECHEOS_DEMO") == "1":
        print("  نسخة العرض: الحساب demo@echoes.app / Echoes2026 (يُعبّأ تلقائيًا).")
    else:
        print("  أول مرة: سيُطلب منك إنشاء حساب مسؤول (بريد وكلمة مرور).")
    print("  الرابط العام لتيليجرام يُفتح تلقائيًا بعد ثوانٍ (يتطلب إنترنت).")
    print("  للإيقاف: Ctrl+C")
    print()

    if HOST == "127.0.0.1":
        _open_later(url + "login")

    import uvicorn
    try:
        uvicorn.run("app.main:app", host=HOST, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n  تم الإيقاف.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
