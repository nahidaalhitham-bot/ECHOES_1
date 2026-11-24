# ECHOES Rebuild — Purple release candidate

This rebuild starts from the supplied application and refreshes the visual identity and memory-network interaction. It is a prototype for judging/demo use, not a clinical or emergency-grade product.

**Honest limitations:** browser GPS sharing only while its page is open; WhatsApp automated sending requires Meta WhatsApp Cloud configuration; face/object matching requires enrolled reference media and optional model availability; test media recognition may be unavailable on a machine without vision models. Do not represent test/demo data as real patient location or real notification delivery.

See `START_HERE.md` for installation and setup.

# Echeos — أصداء الذاكرة (echoes of memory)

A working prototype of a memory-support advisor for a person living with Alzheimer's, built for the **WAICY 2026 AI Showcase (Main)** track, category **High**.

## The one design rule

**The advisor answers only from what the family has written down. If nothing matches, it says so.**

There is no language model in this build. That is deliberate: it means the system *cannot* invent a name, a relation, or a place. Every answer carries its provenance (`people:1`, `memories:3`).

An echo is what remains after the sound is gone — late, and possibly distorted. So an uncertain echo is never spoken.

## What is built

### Memory and the advisor
| Area | Status |
|---|---|
| SQLite memory base (people, memories, chat log, devices, locations, zones, alerts, audit) | **Built** |
| Grounded retrieval — answers only from stored rows | **Built** |
| Explicit refusal when the answer is not stored | **Built** |
| Provenance recorded per answer | **Built** |
| Arabic RTL patient interface (large talk button, help button) | **Built** |
| Family dashboard — add people and memories | **Built** |

### Safety, location and alerts
| Area | Status |
|---|---|
| Device registry + location ingest | **Built** |
| Last-known location with **freshness** — stale is never shown as live | **Built** |
| Safe zones (geofence) with distance check and GPS error margin | **Built** |
| Alerts with **de-duplication** so the family is not spammed | **Built** |
| **Outbound message on zone exit** — text, coordinates, map link, exit time | **Built** |
| Telegram / WhatsApp / Email delivery channels | **Built** (needs credentials) |
| Notification outbox — every attempt recorded honestly | **Built** |
| "Where is he now?" question that never asserts danger | **Built** |
| Help request from the device | **Built** |
| Staleness check → *"no recent location"*, explicitly not a danger claim | **Built** |
| **Device simulator** (advances position before hardware arrives) | **Built** |
| Arabic safety page | **Built** |
| **Linked memory network** (typed nodes + typed edges, graph traversal) | **Built** |
| Reminders (medication / appointments) | **Built** |
| Memory-review sessions with scoring + no-medical-claim disclaimer | **Built** |
| Emergency assistance card (approved fields only) | **Built** |
| **Patient profile** — every field editable from the dashboard, no code change | **Built** |
| **Caregivers** — multiple, with primary marking, full CRUD | **Built** |
| **Auto-Reminder Scope** — caregiver-editable list of what to remind about | **Built** |
| **Caregiver UI shell** — sidebar navigation across 9 screens | **Built** |
| Assistant settings (name, wake phrase, language, voice) | **Built** |
| Dashboard overview (status, alerts, caregivers, scope) | **Built** |
| **Automatic caregiver notification on zone exit** (Telegram / WhatsApp / Email) | **Built — delivers when a channel is configured** |
| **Authentication** — PBKDF2 hashes, server-side sessions, HttpOnly cookie | **Built** |
| **Role-based access** — viewer / caregiver / owner | **Built** |
| **Sensitive endpoints require a session** (401 otherwise) | **Built** |
| **Voice assistant never reveals live location** | **Built** |
| **Telegram bot commands** — `/where`, `/status` from the caregiver's phone | **Built** |
| **Connection-loss alert** — fires once, labels the fix "last known" | **Built** |
| **Reconnection alert** | **Built** |
| Google Maps links in every location message | **Built** |
| Credentials from environment variables (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) | **Built** |
| **Real mode by default** — no demo patient, no invented coordinates | **Built** |
| **Photo uploads** — patient portrait + family photos, auth-protected serving | **Built** |
| **Real GPS ingest** — device bearer tokens, `/api/device/report` | **Built** |
| **Device pairing UI** — token shown once | **Built** |
| **Safe zone from browser geolocation** + manual coordinates | **Built** |
| **Simulator** — opt-in only (`ECHEOS_ALLOW_SIMULATOR=1`) | **Built** |
| **Unlimited numbered photos per memory** — «صورة رقم 1، 2، 3…» | **Built** |
| **Unlimited voice notes per memory** — «صوت رقم 1، 2، 3…» with playable audio | **Built** |
| **Actionable Telegram error messages** — says *why* delivery failed | **Built** |
| **Continuous camera** — auto-starts, recognises every 2.5 s, no buttons | **Built** |
| **Live map** — trajectory line, safe-zone circle, auto-refresh every 3 s | **Built** |
| Simulator opt-in (`ECHEOS_ALLOW_SIMULATOR=1`) with start point from the zone | **Built** |
| **WebSocket telemetry** — live fixes over `/ws/device` with device key | **Built** |
| **Altitude + device timestamps** with clock sanity checks | **Built** |
| **Telegram token encrypted at rest** (Fernet) | **Built** |
| **Simulator removed from the main UI** | **Built** |
| **Profile memory album** — photos + audio under «الذكريات المهمة» | **Built** |
| **Live map dot** — moves the instant a fix arrives (WebSocket push) | **Built** |
| **Trash buttons** on every album photo and voice note | **Built** |
| **Family photos drive recognition** — no separate enrolment needed | **Built** |
| **Voice assistant** — real mic in, Arabic TTS out, continuous mode | **Built** |
| Answers about the patient's own name, family and routine | **Built** |
| «مين هذا؟» uses the latest face recognition | **Built** |
| **Map follows the active device** (no hardcoded device id) | **Built** |
| **WhatsApp Cloud API channel** for alerts | **Built** (needs Meta Business) |
| **Phone-only alerts** — SMS / WhatsApp links, no token or account | **Built** |
| **One-click «محاكاة الخروج من المنزل»** test button | **Built** |
| **Email (SMTP) alert channel** — automatic, no business account | **Built** |
| **Shareable live-link** for family — no account, expiring, revocable | **Built** |
| **In-app code viewer** at `/code` — browse every source file | **Built** |
| **Extended personal profile** — 23 history/favourite fields + completion % | **Built** |
| **AI answers age, DOB, occupation, hobbies, favourites** from the profile | **Built** |
| **Google Maps universal link** (`search/?api=1&query=`) + open button | **Built** |
| **Return-to-zone alert** (deduplicated) | **Built** |
| **Low-battery alert** (banded dedupe) | **Built** |
| Alert message carries accuracy, device status, battery, timestamp | **Built** |
| «مين هذا؟» survives a failed frame (2-minute window) | **Built** |
| **Phone-as-tracker** page (`/tracker`) — real browser GPS → backend | **Built** |
| **Family page** — add a person, upload their photo, see readiness | **Built** |
| **Place/object recognition** from memory photos (SIFT matching) | **Built** |
| Voice answers «وين أنا؟» from a registered place | **Built** |
| Automated test suite (242 test functions in `tests/`) | **Built** — run `pytest` to confirm on your machine |
| Browser speech-to-text (voice input) | **Partial** — browser's own SpeechRecognition; accuracy is whatever the browser gives |

## What is NOT built — and is not claimed

- **Object detection** — there is no trained detector; a place or object is recognised only by matching a view the family photographed (SIFT)
- **Wearable hardware sync** (Galaxy Watch / ULHYC) — never installed on a physical device; use the phone tracker or any HTTP/WebSocket device
- **Speaker identification** and a **wake word** — the assistant cannot tell who is talking
- **Server-side speech-to-text** — speech recognition is the browser's own
- **Disorientation detection** and **fall detection** (needs accelerometer data)
- **MFA, password reset, account lockout, database encryption** — see limitations below
- **Background location on phones** — the tracker page must stay open

### Face recognition: built, opt-in, and allowed to refuse

Real recognition runs locally (OpenCV YuNet detection + SFace 128-d embeddings). No image leaves the machine.

Its rules, which matter more than the accuracy:

1. **Consent required.** Enrolment without `consent=true` is rejected with HTTP 400.
2. **Refusal beats a guess.** Below the similarity threshold, the answer is "I'm not sure" — never a name.
3. **Ambiguity is refused.** If the two best matches are close, it will not pick one.
4. **Visible capture.** Recognition runs only while the camera page is open, and the status dot shows whether it is live or paused (one toggle pauses it).
5. **Deletion works.** `DELETE /api/vision/enroll/{person_id}` removes the embedding.

Verified in development: the same face is recognised (similarity 1.0); a near-identical second person produces `ambiguous`; a blank frame produces `no_face`; nothing enrolled produces `nobody_enrolled`. Every attempt is written to `recognition_log`.

### Why the wearable is not connected

Two devices are reported: **Galaxy Watch 7** and **ULHYC**. A Wear OS APK was built and the build succeeded — but it was **never installed on a physical device**. The ULHYC's OS and API capabilities are **unverified**. The **Device Simulator** is the honest path until then, and it is built here.

## Run it

**Windows: double-click `install_windows.bat`.** It creates the environment, installs packages, downloads the face models, and starts the app with the browser opening automatically.

**Any platform:** `python run.py` starts the server on a free port and opens the browser. See `START_HERE.md`.

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt          # add requirements-dev.txt to run the tests
python -m app.fetch_models          # only if app/models/ is empty (~37 MB)
uvicorn app.main:app --reload --port 8000
```

- Patient interface — <http://127.0.0.1:8000/>
- Family dashboard — <http://127.0.0.1:8000/family>
- Safety & location — <http://127.0.0.1:8000/safety>
- Camera recognition — <http://127.0.0.1:8000/camera>
- Emergency card — <http://127.0.0.1:8000/emergency>

Caregiver screens (reachable from the sidebar):
- Dashboard — `/dashboard`
- Patient profile — `/profile`
- Caregivers — `/caregivers`
- Memory network — `/network`
- Device status — `/device`
- Settings — `/settings`
- Safety centre — `/emergency-center`
- API docs — <http://127.0.0.1:8000/docs>

The app starts **empty** (real mode). Set `ECHEOS_DEMO=1` to load sample data for testing; the yellow **وضع العرض التجريبي** banner then marks it.

Ports: `python run.py` uses **8765** (next free port if busy); the `uvicorn` command above uses 8000.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
# all tests should pass
```

The tests assert the safety properties directly: a daughter never entered must be *refused*; a stale fix must never be labelled live; repeated zone exits must not produce repeated alerts.

## Demo conversation (verified against a running server)

```
من أحمد؟        -> أحمد ابنك. أحمد يحب القهوة العربية.   [answered, people:1]
من سارة؟        -> سارة حفيدتك. سارة عمرها ست سنوات.      [answered, people:3]
أين أعيش؟       -> تعيش في بيتك في حي النرجس              [answered, memories:1]
ماذا أفعل اليوم؟ -> تفطر عادة الساعة سبع وتسقي الزرع بعدها  [answered, memories:2]
ما اسم ابنتي؟    -> ما عندي هالمعلومة. ما أبي أخمّن عليك.    [refused]
من خالد؟        -> ما عندي هالمعلومة. ما أبي أخمّن عليك.    [refused]
من سيزورني؟     -> ما عندي هالمعلومة. ما أبي أخمّن عليك.    [refused]
```

Geofence check, verified: moving outside the 300 m home zone raised exactly **1** alert; repeating the exit raised **0** more (de-duplication).

## Files

```
app/db.py            schema + connection handling
app/agent.py         retrieval and refusal logic (the core)
app/safety.py        location freshness, geofence, alerts, help
app/vision.py        face detection, enrolment, identify-or-refuse
app/network.py       the memory NETWORK: nodes, edges, bounded traversal
app/notify.py        outbound caregiver messages: compose + deliver + outbox
app/auth.py          password hashing, sessions, role guards
app/bot.py           Telegram command handling (/where, /status)
app/media.py         photo upload, validation, authenticated serving
app/devices.py       real device pairing, tokens, connection status
run.py               one-file launcher: starts server + opens browser
install_windows.bat  one-click Windows setup
START_HERE.md        plain-language start instructions
app/fetch_models.py  downloads the 37 MB models on first run
app/alerts.py        alert helpers
app/secrets.py       Fernet encryption of stored credentials
app/models/          YuNet + SFace ONNX models (downloaded on first run, ~37 MB)
app/main.py          FastAPI app and endpoints
app/templates/       patient.html, family.html, safety.html (Arabic, RTL)
app/static/style.css calm palette, large type
tests/test_echeos.py automated tests (safety, auth, alerts, vision, media)
```

## The memory network

ECHOES is not a list of facts. Places, people, events and objects are **nodes**,
and the relationships between them are **typed edges**:

```
محمد  --زار-->  الحديقة  --مع-->  الأبناء  --شاركوا في-->  نزهة الجمعة
                                             نزهة الجمعة --لها--> صورة عائلية
```

When the camera recognises a place or person, `recall_from()` walks outward
(bounded to depth 2 and 12 nodes) and returns everything connected — **each item
carrying the path that produced it**, so the family can see why the advisor said
something. If the graph has no path, the result is empty and the caller refuses.

Verified live: recalling from `الحديقة` returns محمد, الأبناء, نزهة الجمعة and
صورة عائلية, each with its own `via` path.

## Honest limitations

1. **No semantic search.** Matching is keyword- and subject-based. Synonyms the family did not use will not match.
2. **Retrieval is rule-based.** It handles common question shapes and refuses on unusual ones — safe, but not the same as understanding.
3. **Authentication is prototype-grade.** Passwords are PBKDF2-hashed and sessions are server-side, but there is no MFA, no password reset, no lockout, and the database is unencrypted on disk. Adequate to keep a location feed off the open network; not adequate for real medical deployment.
4. **Plaintext SQLite.** Fine for a demo; needs encryption and access control before real use.
5. **Face recognition needs enrolment per person, from a clear photo.** Accuracy drops with poor light, side angles, or sunglasses; those cases should refuse, and the threshold is deliberately conservative.
6. **Simulated locations are simulated.** Every point is tagged `محاكي` and the UI says so. No real position is ever displayed.
7. **Alerts reach family only if a channel is configured** (Telegram, WhatsApp, email, or phone links). Otherwise they stay in the app and nobody who is not looking at the screen is told.

## For the submission

This is the working system behind the demo video. The four required Showcase files are separate deliverables:

- `Main_High_Echeos_Presentation.pdf`
- `Main_High_Echeos_Description.pdf`
- `Main_High_Echeos_DemoVideo.mp4`
- `Main_High_Echeos_PresentationVideo.mp4`


## Telegram setup

Either set environment variables (they win over the UI):

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="987654321"
```

…or enter them in **Settings → إشعارات الطوارئ**. Without credentials the app
records `delivered: false` in the outbox and never claims a message was sent.

To let the caregiver ask the bot `/where`, call `POST /api/bot/poll`
periodically (or wire it to a scheduler). Each poll answers pending commands
from the configured chat only; messages from any other chat are ignored.

### Verified end to end

Against a local stand-in for the Telegram Bot API, the app made real HTTP calls
and the receiver confirmed:

1. zone exit → one message with name, warning, coordinates, Google Maps link, time
2. repeated exits → **no duplicate** message
3. 2 hours of silence → connection-loss message, labelled *last known location*
4. device reports again → reconnection message
5. caregiver sends `/where` → reply with coordinates, timestamp and map link


## Real-mode operation

The app now starts empty. There is no demo patient, no invented family, and no
coordinates until a real device reports them. Demo data is opt-in:

```bash
ECHEOS_DEMO=1 python run.py          # load sample data (testing only)
ECHEOS_ALLOW_SIMULATOR=1 python run.py   # enable the simulator device
```

### Connecting a real GPS device

1. **Device page → إضافة جهاز** — enter a name. A token is shown **once**.
2. Configure the device to POST its position:

```http
POST /api/device/report
Authorization: Bearer ech_xxxxxxxx
Content-Type: application/json

{"lat": 24.7136, "lon": 46.6753, "accuracy_m": 10, "battery": 80}
```

3. Any phone, smartwatch, or tracker that can send an HTTP request works —
   including Tasker on Android, a Raspberry Pi, or a custom watch app.
   The simulator device is refused on this endpoint on purpose: only a real
   device can create a real location.

### What still needs external setup

| Requirement | Status |
|---|---|
| Patient profile + photos | Works now |
| Family members + photos | Works now |
| Safe zone (browser geolocation or manual) | Works now |
| Real GPS coordinates | Works — **needs a physical device sending HTTP** |
| Telegram alerts | Works — **needs a bot token and chat id** |
| Fall detection | **Not built** — needs accelerometer data |
| WhatsApp | **Not built** — needs Business API access |
| Voice output (TTS) | **Not built** |


## Memories: photos and voice notes

Each memory can hold **any number** of photos and voice notes. They are
numbered automatically as they are uploaded:

- photos → «صورة رقم 1», «صورة رقم 2», …
- audio → «صوت رقم 1», «صوت رقم 2», … (playable in the browser)

| Endpoint | Purpose |
|---|---|
| `POST /api/memories/{id}/photos` | append a photo (no limit) |
| `GET /api/memories/{id}/photos` | list with labels |
| `GET /api/memory-photo/{photo_id}` | fetch (auth required) |
| `POST /api/memories/{id}/audio` | append a voice note |
| `GET /api/memories/{id}/audio` | list with labels |
| `GET /api/audio/{clip_id}` | stream (auth required) |

Accepted: JPG/PNG/GIF/WEBP up to 8 MB; MP3/M4A/WAV/OGG/FLAC up to 25 MB.
Type is detected from the file signature, not the filename.

## Telegram troubleshooting

If delivery fails the reason is now explicit instead of a bare `404`:

| Message | Meaning |
|---|---|
| `missing_bot_token` | no token entered — get one from @BotFather |
| `missing_chat_id` | no chat id entered |
| `telegram http 401` | token is wrong or incomplete |
| `telegram http 403` | bot blocked — press **Start** in the bot chat |
| `telegram http 400` | chat id is wrong |

The Settings page shows **why** the channel is not ready, rather than
claiming it is.


## Camera: continuous recognition

`/camera` starts the webcam on load and runs recognition every 2.5 seconds.
There is no "start" or "who is this?" button. The status dot shows متوقف /
مباشر, and a single toggle can pause it. Recognition still refuses when it is
not certain — the loop never invents a name.

Note: browsers require a user gesture or a previously granted permission for
camera access on some configurations. If the browser blocks it, the page says
so explicitly rather than showing a black rectangle.

## Live map

`/safety` renders an SVG map from real fixes: the safe-zone circle, the path
travelled, and the latest point in red. It refreshes every 3 seconds while the
auto-refresh box is ticked, and the label states whether the last fix is inside
or outside the zone.

## Simulator (testing only)

```bash
ECHEOS_ALLOW_SIMULATOR=1 python run.py
```

Each press of «تحريك الجهاز» moves the test device ~90 m. On the first press it
starts from the centre of the safe zone, so testing works on a fresh install.
Simulated points are always stored with `simulated = 1` and are shown as
«محاكي» in the UI — never as a real position.


## Live telemetry (WebSocket)

A real device can stream instead of polling:

```
ws://127.0.0.1:8765/ws/device?token=<DEVICE_TOKEN>
```

Send JSON frames:

```json
{"lat": 24.7136, "lon": 46.6753, "altitude": 612, "battery": 88}
```

Each frame is stored, geofenced, and alerts exactly like the REST endpoint.
Unrecognised tokens are closed with code 1008 before any data is accepted.

Clock honesty: a device-supplied `timestamp` is used only if it parses and is
not more than two minutes in the future; otherwise the server clock wins, so a
device with a wrong clock cannot make an old fix look live.

## Secrets at rest

The Telegram bot token is encrypted with Fernet before it is written to the
database (`enc::…`). The key comes from `ECHEOS_SECRET_KEY`; if unset, one is
generated into `app/.secret_key` with owner-only permissions. A database file
copied without that key yields no usable token.

## Simulator

Removed from the caregiver interface entirely. It still exists for automated
tests behind `ECHEOS_ALLOW_SIMULATOR=1`, and never appears in normal operation.


## Where photos and audio live

Both places work, and they are separate albums:

1. **Patient profile → «الذكريات المهمة والأشخاص المقربون»** — attach any number
   of photos and voice notes directly to that field. This is the primary place.

   | Endpoint | Purpose |
   |---|---|
   | `POST /api/patient/memories/photos` | append a photo |
   | `GET /api/patient/memories/photos` | list with «صورة رقم N» labels |
   | `POST /api/patient/memories/audio` | append a voice note |
   | `GET /api/patient/memories/audio` | list with «صوت رقم N» labels |

2. **الذاكرة الشخصية** — per-memory albums, for many separate memories.

The profile album is stored against a hidden anchor row, which is filtered out
of `/api/memories` so it never shows up as a memory of its own.


## The patient dot moves live

The safety map subscribes to `/ws/live`. Every stored fix — from a real device
over REST or WebSocket, or from the opt-in simulator — is pushed to open
caregiver screens immediately, so the marker travels instead of jumping on a
3-second poll.

- The marker element is reused and animated with a CSS transform transition,
  so movement reads as motion, not as a blinking dot.
- The trail grows in place; the map only re-frames when it first loads.
- The socket reconnects automatically with a short backoff.
- Unauthenticated sockets are closed with code 1008 before any data is sent.

A 3-second poll still runs as a fallback if the socket cannot connect.


## Recognition uses the photos you upload

Uploading a family member's photo now also stores a face descriptor for them
(`photo_embeddings`). The camera recognises that person **without any separate
enrolment step**, and — on recognition — pulls their linked memories from the
memory network and shows them.

Precedence: an explicit enrolment (`face_enrollments`, consented) always wins;
photo-derived descriptors fill in for everyone else.

A photo with no detectable face is still saved to the profile, but
`face_descriptor_created` comes back `false` so it is clear it cannot be used
for recognition.

### What this does and does not cover

| Input | Supported |
|---|---|
| A person's face | **Yes** — from an uploaded photo |
| Familiar places | **No visual recognition** — places are recalled by name/text |
| Household objects (kettle, stove) | **No** — not implemented |
| Voices identifying a speaker | **No** — audio is stored and played, not compared |


## Voice assistant (two-way)

`/` is the patient assistant. It uses the browser's own microphone and
speech synthesis — no audio is uploaded, stored, or recorded.

**Flow:** tap → listening (red pulsing orb) → speech recognised → question sent
to the assistant → answer spoken aloud (green orb) → listening resumes
automatically. A stop button and a mute button are always visible.

### What it can answer

| Patient asks | Source |
|---|---|
| «وش اسمي؟» | `patient_profile.full_name` |
| «مين عيالي؟» | the `people` table |
| «وش أسوي الحين؟» | `patient_profile.routine` |
| «من أحمد؟» | people + linked memories |
| «مين هذا؟» | the most recent face recognition |
| location questions | **always refused** — the device cannot verify the speaker |

Every answer is grounded in stored rows. With no data it says it does not know
rather than inventing a name or relationship.

### Honest limits

- **Speech-to-text is the browser's.** Chrome/Edge on desktop and Android give
  good Saudi-Arabic results; Firefox and Safari are weaker. There is no custom
  Arabic ASR model here.
- **Text-to-speech depends on an installed Arabic voice.** The page detects
  when none exists and tells the patient plainly instead of failing silently.
- **No wake word.** The patient taps once to begin; the loop then continues
  until stopped. Always-on hotword detection is not implemented.
- **No speaker identification.** The assistant cannot tell who is talking, so
  private data is never released on voice alone.


## Why the map could show "no location"

The map used to query `device_id=1` everywhere. That works only if your first
paired device happens to be id 1 — after pairing a second device, or when
reporting came from a different one, the map stayed empty while the data was
perfectly fine.

`GET /api/location/active-device` now answers "which device should the map
follow?" — the one that reported most recently, otherwise the newest real
device. The page resolves it once on load and uses it for the trail, the live
feed and the "أين هو الآن" question. Fixes from other devices are ignored by
the live view.


## WhatsApp alerts

Choose **WhatsApp** as the notification channel in Settings, or set:

```bash
export WHATSAPP_TOKEN="EAA..."
export WHATSAPP_PHONE_NUMBER_ID="123456789012345"
export WHATSAPP_TO="9665XXXXXXXX"
```

The token is encrypted at rest like the Telegram one.

### What it really needs (Meta's rules, not ours)

| Requirement | Why |
|---|---|
| A Meta Business account + WhatsApp Business app | Personal WhatsApp has no send API |
| A sender phone number ID | identifies the business number sending |
| Opt-in / approved template for business-initiated messages | free-form text is only allowed within **24 hours** of the recipient's last message |
| Recipient registered on WhatsApp | otherwise Meta returns 131026 |

The app reports Meta's actual error in Arabic instead of a bare code:
`131047` explains the 24-hour window, `131026` explains an unregistered or
non-opted-in recipient, `401/403` explains rejected credentials.

**Telegram remains the simpler channel** — a bot token works immediately with
no business account and no template approval.


## Alerts with only a phone number

**Settings → أرقام هواتف للتنبيه** lets you save caregiver phone numbers — no
token, no business account. Each alert then offers a ready-made link:

| Channel | What happens |
|---|---|
| **SMS** | `sms:+9665...?body=...` opens the phone's messaging app with the message filled in |
| **WhatsApp** | `https://wa.me/9665...?text=...` opens WhatsApp with the message filled in |

Open the link on a phone and press send. There is no server, no provider and
no billing.

**The honest limit: these are not automatic.** The server cannot send an SMS or
a WhatsApp message from a bare phone number — every platform requires either a
gateway account (SMS) or a Meta Business account (WhatsApp). So the app
prepares the message and hands it to the phone; a human presses send.

Fully automatic delivery is available through **Telegram** (bot token, works in
minutes) or **WhatsApp Cloud API** (Meta Business, needs an approved template).

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/alert-contacts` | list saved numbers |
| `POST /api/alert-contacts` | add `{name, phone, channel: sms\|whatsapp_link}` |
| `DELETE /api/alert-contacts/{id}` | remove |
| `GET /api/alerts/{id}/share` | message text + one link per contact |


## Simulating a safe-zone exit (for demos)

The Safety page has a clearly-marked **أداة تجريب** box with
**«محاكاة الخروج من المنزل»**. One click:

1. places the test device ~600 m outside the zone centre,
2. records the fix with `simulated = 1`,
3. raises the `exited_safe_zone` alert,
4. sends the caregiver notification if a channel is configured,
5. draws the point outside the circle on the map.

Requires `ECHEOS_ALLOW_SIMULATOR=1`; otherwise the endpoint answers 403 and the
button reports that simulation is disabled. With no safe zone defined it says
so instead of inventing one.

The generated data is always labelled «محاكي» and never presented as a real
position.


## Email alerts (SMTP)

The easiest **fully automatic** channel: no Meta account, no bot, no gateway.

Settings → قناة الإرسال → **بريد إلكتروني**, then:

| Field | Note |
|---|---|
| SMTP Host | `smtp.gmail.com`, `smtp.office365.com`, … |
| Port | `587` (STARTTLS) or `465` (implicit TLS) |
| SMTP User | the sending address |
| Password | for Gmail use an **App Password**, not the account password |
| From | defaults to the user |
| To | the caregiver's address |

Or set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`,
`SMTP_TO`.

The SMTP password is encrypted at rest like the other credentials.

**Verified with a real SMTP exchange:** the message arrived with
`Content-Type: text/plain; charset="utf-8"`, the Arabic body intact, the
patient's name, coordinates and the Google Maps link.

Options ranked by setup effort:

| Channel | Effort | Automatic |
|---|---|---|
| **Email** | App password, ~2 min | **Yes** |
| Telegram | BotFather token, ~2 min | Yes |
| WhatsApp Cloud | Meta business + template | Yes |
| SMS / wa.me links | just a number | No (one tap) |


## Sending the live location to family

**Safety page → رابط مباشر للعائلة → إنشاء رابط.** Pick 6 h / 24 h / 3 days.
You get a URL like `/live/<token>` plus a **"send on WhatsApp"** button.

The recipient needs **no account and no app**: open the link on any phone and
see the patient's current position, when it was updated, and a map button.

**Privacy boundaries, enforced in code:**

- shows **location only** — no medical data, no photos, no address, no name of
  family members (a test asserts none of those fields appear)
- **expires** automatically; after expiry the page returns 410
- **revocable** at any time from the same panel (404 afterwards)
- one public endpoint only: `GET /api/public/live/{token}`


## Reading the source

Open **`/code`** in the running app (sidebar → **كود المشروع**). It lists every
source file with line counts and shows the contents with syntax colouring.
Read-only.

The file list is an explicit allow-list (`VIEWABLE` in `app/main.py`). Any path
outside it — including `../` traversal and `app/.secret_key` — returns 403, so
the viewer cannot be used to read anything else on the machine.

No account on GitHub is required; the project has no repository and this is the
simplest way to read it.


## Extended patient profile

`/profile` now has two parts:

1. **Core** — name, age, address, medical, allergies, emergency notes, routine,
   preferences, memories, reminder scope.
2. **السيرة والمعلومات الشخصية** — 23 further fields: nickname, date of birth,
   gender, dialect, phone, birthplace, childhood, occupation, education, life
   events, hobbies, favourite activities/foods/drinks/music/places/topics,
   comfort items, confusion triggers, medications, schedule, medical
   instructions, mobility.

A **completion bar** shows the percentage and lists exactly which fields are
still missing (`GET /api/patient/completion`).

Everything is stored in the database and read by the assistant — no hardcoded
sample patient data anywhere.

## Questions the assistant can now answer

| Question | Source |
|---|---|
| «وش اسمي؟» | `full_name` |
| «كم عمري؟» | `age` |
| «متى ولدت؟» | `date_of_birth` + `birthplace` |
| «وش كنت أشتغل؟» | `occupation` |
| «هواياتي؟» | `hobbies` |
| «وش أحب آكل؟» | `favourite_foods` |
| «وش أحب أشرب؟» | `favourite_drinks` |
| «أماكني المفضلة؟» | `favourite_places` |
| «مين عيالي؟» | the `people` table |
| «وش أسوي الحين؟» | `routine` |
| «مين هذا؟» | last face recognition |

Any missing field produces a gentle refusal naming the gap — never an invented
answer.


## Location links and automatic alerts

Every location link uses the documented universal format, so it opens the Maps
app on a phone and the web map elsewhere:

```
https://www.google.com/maps/search/?api=1&query=LAT,LON
```

The Safety page has **افتح موقع المريض في خرائط جوجل**, rebuilt from the latest
fix on every refresh, with the update time and GPS accuracy beside it.

### Alerts raised automatically

| Event | Message |
|---|---|
| leaves the safe zone | ⚠️ خروج من النطاق الآمن |
| returns inside | ⚠️ عاد إلى النطاق الآمن |
| device silent | ⚠️ انقطاع اتصال الجهاز |
| device reports again | ⚠️ عاد الجهاز للاتصال |
| battery at/below 15% | ⚠️ بطارية الجهاز منخفضة |
| help pressed | ⚠️ طلب مساعدة |

Each message contains: patient name, coordinates, **GPS accuracy in metres**,
device connection status, battery, the event time, and the clickable Maps link.

Duplicate suppression: zone exits keyed to the zone, returns keyed to the
inside/outside transition, battery keyed to a 5% band — so a caregiver is never
spammed by the same event.


## Acceptance report (against the 20-row checklist)

Verified against a running server with real records, real photos and real tokens.

| Feature | Result | Evidence |
|---|---|---|
| Caregiver registration | **PASS** | account created + session cookie |
| Patient registration | **PASS** | row persisted, re-read from DB |
| Family registration | **PASS** | row + authorized photo stored |
| Camera | **PASS (browser)** | `getUserMedia` opens, frames captured |
| Face recognition (registered) | **PASS** | similarity 1.0, correct name+relation |
| Unknown face | **PASS** | refused, no identity invented |
| Microphone | **PASS (browser)** | Web Speech API, permission prompt |
| Speech-to-text | **browser-dependent** | Arabic accuracy = Chrome's engine |
| AI assistant | **PASS** | answers from retrieved DB context |
| Text-to-speech | **PASS (browser)** | `speechSynthesis`, Arabic voice |
| Memory retrieval | **PASS** | «من أحمد؟» → stored fact returned |
| GPS ingest | **PASS** | device token → `/api/device/report` |
| Backend location | **PASS** | lat/lon/accuracy/timestamp persisted |
| Google Maps link | **PASS** | documented `search/?api=1&query=` format |
| Live map | **PASS** | WebSocket push moves the marker |
| Safe zone | **PASS** | Haversine inside/outside computed |
| Exit event | **PASS** | `exited_safe_zone` row created |
| Telegram | **needs bot token** | code sends real HTTP; token is yours |
| Automatic alert | **PASS** | exit → message with no manual send |
| Wearable | **needs hardware** | bridge ready; no device present |

Three rows cannot pass without equipment only the caregiver can supply: a
Telegram bot token, and a physical device that reports GPS.


## Using a phone as the GPS source

No wearable needed. The phone that carries the patient opens **`/tracker`**:

1. log in as the caregiver (same account),
2. press **ابدأ مشاركة الموقع**,
3. allow the browser's location prompt.

`watchPosition` with `enableHighAccuracy: true` then streams real fixes to
`POST /api/phone/location`, authenticated by the caregiver **session** rather
than a device token — a browser on a phone cannot hold a bearer token safely.

Each fix is stored with `simulated = 0`, geofenced with Haversine, and can raise
the exit or return alert exactly like a wearable. The page shows latitude,
longitude, accuracy, last send time, and the server's response, plus a
**افتح الموقع في خرائط جوجل** button rebuilt from the live coordinates.

### Requirements and honest limits

- The page must stay open; browsers suspend background tabs on phones. There is
  no background-location service worker here.
- GPS accuracy on phones is typically 5–30 m depending on sky view.
- The caregiver must be logged in on that phone. For a patient's own phone,
  log it in with a caregiver account and keep it charged.


## Adding a face the camera can recognise

**Sidebar → العائلة والأبناء** (`/family`):

1. type a name and relationship, press **إضافة**;
2. press **رفع صورة** on that person's card and choose a photo;
3. the card shows **جاهز للتعرف** once the face descriptor exists.

Until step 2 the card reads **يحتاج صورة**. If a photo is uploaded but no face is
found it reads **الصورة بلا وجه واضح** — the photo is kept but cannot be used for
recognition.

`GET /api/family/{id}/recognition-status` reports `has_photo`,
`face_descriptor` and `ready` per person, so readiness is per-person rather than
a single global counter.

Deleting a person removes their photo, their face descriptor and any explicit
enrolment in one step.


## Recognising places and objects

Memory-album photos are also taught to the camera. Uploading a photo of a place
or object stores a SIFT descriptor (`scene_embeddings`), and the camera can then
match that view.

### What it does

| Case | Result |
|---|---|
| Same place, similar view, different brightness | recognised (measured ~0.55 score) |
| Same place, identical photo | recognised (1.0) |
| A place never registered | refused (`below_threshold`, ~0.01) |
| Nothing registered yet | refused (`nothing_taught`) |

Face recognition runs **first**: a familiar face outranks a familiar room. The
combined endpoint is `POST /api/vision/identify-scene`.

### What it does **not** do — please read

- There is **no trained object detector**. It cannot name an object it was
  never shown ("that is a kettle").
- It does **not** generalise to a very different angle, a different day, or a
  heavy occlusion. It recognises *the same view* it was taught.
- Threshold 0.12 is set between measured noise (~0.01) and a true match (~0.55),
  so unfamiliar scenes are refused rather than guessed.

### Voice

«وين أنا؟» answers with the most recently registered place plus its memory
fact, e.g. «هذا حديقة العائلة. كنا نجلس فيها كل جمعة.» Before any place is
registered it says it does not know.


**Automatic exit-alert link:** with `ECHOES_PUBLIC_URL` configured and a caregiver delivery channel enabled, safe-zone exit notifications include a temporary public live-location page (24-hour expiry) plus a Google Maps point link.

\n## Public live-link from the laptop\n\nUse `run_public_windows.bat` to keep ECHOES running on the laptop and expose it through a temporary HTTPS Cloudflare Tunnel. The app automatically uses that tunnel URL for temporary live-location links on safe-zone exit. See `PUBLIC_DEPLOY_NOTES.md`. GitHub is source storage only; it does not host this laptop server.\n