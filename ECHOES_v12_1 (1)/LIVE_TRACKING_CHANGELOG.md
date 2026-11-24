# ECHOES Laptop PublicLink v8 — live tracking reliability update

- Safe-zone exits now account for the GPS accuracy radius. An exit is only confirmed when the full reported accuracy circle is outside the configured zone. A return is only confirmed when the fix is clearly inside; uncertain boundary fixes preserve the previous state.
- The public live page stops polling after a share token expires or is revoked.
- If the network temporarily fails, the public page labels the displayed point as the last known location instead of leaving a stale "live" label on screen.
- Added automated regression tests for GPS uncertainty, HTTPS-only link creation, Arabic alert composition, public endpoint freshness/revocation, and the exit-to-outbox link flow.
- The update does not include or overwrite `echeos.db`, credentials, or patient records.
