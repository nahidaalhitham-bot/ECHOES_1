"""ECHOES — simulated demo version (نسخة العرض المحاكية).

Starts the same app with fictional data that is filled in automatically:
a patient, his family, memories, places, photos the camera can recognise,
conversations, alerts and a location trail.

It uses its own database (echoes_demo.db) and uploads folder, so the real
data is never touched. The demo is rebuilt fresh on every start; pass
--keep to continue from the last demo session.

Login:  demo@echoes.app   /   Echoes2026
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
DB = ROOT / "echoes_demo.db"
UPLOADS = ROOT / "app" / "uploads_demo"

os.environ["ECHEOS_DEMO"] = "1"
os.environ["ECHEOS_DB"] = str(DB)
os.environ["ECHEOS_UPLOADS"] = str(UPLOADS)
os.environ["ECHEOS_ALLOW_SIMULATOR"] = "1"
os.environ.setdefault("ECHEOS_PORT", "8790")

if "--keep" not in sys.argv:
    for p in (DB, Path(str(DB) + "-wal"), Path(str(DB) + "-shm")):
        if p.exists():
            p.unlink()
    if UPLOADS.exists():
        shutil.rmtree(UPLOADS)

print("""
  ╔══════════════════════════════════════════════╗
  ║   ECHOES — نسخة العرض المحاكية (بيانات وهمية)  ║
  ╚══════════════════════════════════════════════╝
   الحساب:        demo@echoes.app
   كلمة المرور:   Echoes2026
   صور للكاميرا:  مجلد demo_images (اعرضيها أمام الكاميرا)
""")

if os.environ.get("ECHOES_DEMO_PUBLIC") == "1":
    # Print the public https link as soon as Cloudflare gives it.
    import threading, time, webbrowser

    def _announce():
        from app import tunnel
        for _ in range(240):
            time.sleep(1)
            url = tunnel.public_base()
            if url:
                print("\n  ===========================================================")
                print("   الرابط العام (يفتح من أي جوال أو جهاز):")
                print(f"   {url}")
                print(f"   الكاميرا من الجوال:  {url}/camera")
                print("   يبقى شغالًا ما دام هذا الجهاز وهذه النافذة مفتوحة.")
                print("  ===========================================================\n")
                try:
                    with open(ROOT / "PUBLIC_LINK.txt", "w", encoding="utf-8") as f:
                        f.write(url + "\n")
                except Exception:
                    pass
                return
            d = tunnel.status().get("detail")
            if _ and _ % 30 == 0 and d:
                print("   [الرابط العام]", d)
        print("   تعذّر فتح الرابط العام (تحققي من الإنترنت). التطبيق يعمل محليًا.")

    threading.Thread(target=_announce, daemon=True).start()

import run  # noqa: E402  (the normal launcher, now pointing at the demo data)

raise SystemExit(run.main())
