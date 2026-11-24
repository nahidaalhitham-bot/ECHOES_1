# ECHOES — Public live-location link from the laptop

## What this does
- The ECHOES Python server stays on your laptop and binds only to `127.0.0.1`.
- Cloudflare Quick Tunnel creates a temporary HTTPS address that forwards to the laptop.
- When a real GPS update triggers a safe-zone exit, the configured notification channel receives a Google Maps point link and a temporary read-only ECHOES live-link.
- The ECHOES live-link expires after 24 hours and can be revoked from the app's live-sharing list.
- The live page updates about every 4 seconds and labels stale data as last-known. Simulated coordinates are explicitly labelled.

## Windows setup
1. Install Python 3.11 or newer and run the existing `install_windows.bat` once.
2. Install Cloudflare Tunnel (cloudflared) from PowerShell:
   `winget install --id Cloudflare.cloudflared -e`
3. Close and reopen PowerShell/Windows Terminal after installation.
4. First run the local app and create the owner account if you have not already. The public launcher refuses to start a tunnel while first-owner registration is open.
5. Double-click `run_public_windows.bat`.
6. Wait for the printed `https://...trycloudflare.com` URL. That is the public HTTPS app address for this session.
7. Log in locally. Configure Telegram, email, or another supported delivery channel in Settings and test delivery with fictional data.
8. When a real (consented) location report exits the safe zone, the caregiver alert includes a temporary live-link. The laptop, app, and internet connection must stay on.

## GitHub
- Create a **private** repository for the source code.
- Never commit `app/.secret_key`, `.env`, any database, or `app/uploads/` / `app/uploads.zip`.
- The `.gitignore` in this patch excludes those files. Before pushing, inspect `git status` and the staged file list.
- GitHub stores the source. It does not run the laptop server or keep the tunnel online.

## Important limitations
- Quick Tunnel URL is random and generally changes after restarting. The current session's ECHOES_PUBLIC_URL is set automatically by `run_public.py`; old links using the prior hostname won't work after the tunnel changes.
- The laptop must remain awake, ECHOES must remain running, and the location-sharing device/page must continue reporting. Browser GPS is not guaranteed in the background after closing the page.
- A public tunnel exposes the web app to the internet. Authentication protects caregiver pages; live-share links are bearer links and anyone who receives/forwards them can view location until expiry or revocation.
- This prototype has not been hardened for real medical/emergency use. Use fictional data for demos; real tracking requires informed consent and a caregiver-approved setup.
- If cloudflared cannot start, use the local launcher `run.py` for local-only testing.
