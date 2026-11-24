# ECHOES — live tracking and temporary public link

- Safe-zone exit notification includes the current Google Maps point link and, when the public tunnel is running, an expiring read-only ECHOES live link.
- The shared page refreshes every 4 seconds and labels stale fixes as last known.
- The public endpoint returns location only, no patient profile details; responses are marked no-cache.
- Simulated coordinates are explicitly labelled.
- Live sharing requires HTTPS public tunnel, a configured notification channel, location permission, and an authorized/consented source.
- Browser tracking is not guaranteed in the background after closing the tracker page.
