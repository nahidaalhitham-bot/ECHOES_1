"""What the patient app may reach (shared by patient_app and patient_proxy)."""

ALLOWED_PREFIXES = (
    "/static/", "/i18n/", "/health",
    "/api/agent/chat", "/api/companion/", "/api/tracker/pair",
    "/api/device/report", "/api/auth/status",
)
ALLOWED_EXACT = {"/patient", "/tracker", "/favicon.ico", "/patient.webmanifest", "/sw.js"}

_NOT_HERE = ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             "<body style='font-family:system-ui,sans-serif;text-align:center;padding:18vh 20px;color:#3b1d5c'>"
             "<div style='font-size:46px'>👴</div><h2>هذا رابط تطبيق المريض</h2>"
             "<p style='color:#6b5a80'>لوحة المسؤول لها رابط مختلف.</p>"
             "<p><a href='/'>فتح شاشة المريض</a></p></body>").encode("utf-8")
