from __future__ import annotations

from pathlib import Path

import pytest

from app import db, notify, safety


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test_echeos.db"))
    db.init_db()
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO devices(name, kind, simulated, connected) VALUES (?,?,?,?)",
            ("test-tracker", "wearable", 0, 1),
        )
        device_id = cur.lastrowid
        conn.execute(
            "INSERT INTO safe_zones(name, lat, lon, radius_m, enabled) VALUES (?,?,?,?,1)",
            ("home", 0.0, 0.0, 100.0),
        )
    return device_id


def test_geofence_respects_gps_accuracy_margin(isolated_db, monkeypatch):
    device_id = isolated_db
    sent = []

    def fake_exit(*args, **kwargs):
        sent.append((args, kwargs))
        return {"delivered": False, "channel": "none"}

    monkeypatch.setattr(notify, "notify_geofence_exit", fake_exit)

    # About 110 m from the zone center: the 30 m accuracy circle overlaps
    # the 100 m boundary, so this is uncertain and must not trigger an alert.
    lat_110m = 110.0 / 111_195.0
    safety.record_location(lat_110m, 0.0, device_id, accuracy_m=30.0, simulated=False)
    with db.connect() as conn:
        pending = conn.execute("SELECT COUNT(*) FROM pending_notifications").fetchone()[0]
    assert pending == 0

    # About 150 m away: the entire 30 m accuracy circle is outside the 100 m zone.
    lat_150m = 150.0 / 111_195.0
    safety.record_location(lat_150m, 0.0, device_id, accuracy_m=30.0, simulated=False)
    with db.connect() as conn:
        pending = conn.execute("SELECT COUNT(*) FROM pending_notifications").fetchone()[0]
    assert pending == 1

    results = safety.drain_pending_notifications("Test Patient")
    assert len(results) == 1
    assert len(sent) == 1


def test_temporary_live_link_requires_public_https(isolated_db, monkeypatch):
    monkeypatch.setenv("ECHOES_PUBLIC_URL", "http://not-secure.example")
    assert notify.create_temporary_live_share(hours=1) is None

    monkeypatch.setenv("ECHOES_PUBLIC_URL", "https://echoes.example")
    url = notify.create_temporary_live_share(hours=1)
    assert url is not None
    assert url.startswith("https://echoes.example/live/")
    token = url.rsplit("/", 1)[-1]
    with db.connect() as conn:
        row = conn.execute(
            "SELECT token, expires_at, revoked_at FROM share_links WHERE token = ?",
            (token,),
        ).fetchone()
    assert row is not None
    assert row["revoked_at"] is None
    assert row["expires_at"]


def test_exit_message_contains_live_link_and_arabic(isolated_db):
    url = "https://echoes.example/live/test-token"
    message = notify.compose(
        "exited_safe_zone", "اسم تجريبي", 24.7, 46.6,
        "2026-11-21T12:00:00+00:00", live_url=url,
    )
    assert url in message["text"]
    assert "خروج من النطاق الآمن" in message["text"]
    assert "افتح موقع المريض على الخريطة" in message["text"]


def test_public_endpoint_returns_latest_fix_and_honors_revocation(isolated_db):
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from starlette.responses import Response
    from app import main

    token = "unit-test-live-token"
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO share_links(token, expires_at) VALUES (?,?)",
            (token, "2099-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO locations(device_id, lat, lon, accuracy_m, simulated) "
            "VALUES (?,?,?,?,0)",
            (isolated_db, 24.7, 46.6, 8.0),
        )

    payload = main.public_live_data(token, Response())
    assert payload["ok"] is True
    assert payload["location"]["lat"] == pytest.approx(24.7)
    assert payload["location"]["lon"] == pytest.approx(46.6)
    assert payload["location"]["map_link"].startswith("https://www.google.com/maps/")

    with db.connect() as conn:
        conn.execute(
            "UPDATE share_links SET revoked_at = ? WHERE token = ?",
            (now, token),
        )
    with pytest.raises(HTTPException) as exc:
        main.public_live_data(token, Response())
    assert exc.value.status_code == 404


def test_geofence_exit_creates_public_link_in_outbox(isolated_db, monkeypatch):
    monkeypatch.setenv("ECHOES_PUBLIC_URL", "https://echoes.example")
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)

    lat_150m = 150.0 / 111_195.0
    safety.record_location(lat_150m, 0.0, isolated_db, accuracy_m=0.0, simulated=False)
    results = safety.drain_pending_notifications("Test Patient")

    assert len(results) == 1
    result = results[0]
    assert result["live_share_url"].startswith("https://echoes.example/live/")
    assert result["live_share_url"] in result["text"]
    assert result["channel"] == "none"
    assert result["delivered"] is False  # no channel was configured in this test
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM share_links").fetchone()[0] == 1
        outbox = conn.execute("SELECT payload, delivered FROM notif_outbox").fetchone()
    assert result["live_share_url"] in outbox["payload"]
    assert outbox["delivered"] == 0


# ---------------------------------------------------------------------------
# Exit message format, public link, Telegram live location, repeat exits
# ---------------------------------------------------------------------------

def _tg_setup(monkeypatch, calls):
    monkeypatch.setattr(notify, "_settings", lambda: {
        "channel": "telegram", "telegram_token": "T", "telegram_chat_id": "42"})

    def fake_send(token, chat_id, text):
        calls.append(("sendMessage", {"text": text}))
        return True, "sent"

    def fake_call(token, method, params):
        calls.append((method, params))
        return True, {"message_id": 9}

    monkeypatch.setattr(notify, "_send_telegram", fake_send)
    monkeypatch.setattr(notify, "_tg_call", fake_call)
    monkeypatch.setattr(notify, "LIVE_EDIT_MIN_SECONDS", 0)


def _set_name(name):
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO patient_profile(id, full_name) VALUES (1, ?)", (name,))


def test_exit_message_exact_format_with_public_link(isolated_db, monkeypatch):
    monkeypatch.setenv("ECHOES_PUBLIC_URL", "https://abc.trycloudflare.com")
    calls = []
    _tg_setup(monkeypatch, calls)
    out_lat = 500.0 / 111_195.0
    safety.record_location(0.0, 0.0, isolated_db, accuracy_m=5.0, simulated=False)
    safety.record_location(out_lat, 0.0, isolated_db, accuracy_m=5.0, simulated=False)
    safety.drain_pending_notifications("أبو محمد")

    text = [c for c in calls if c[0] == "sendMessage"][0][1]["text"]
    first, link = text.split("\n")
    assert first == "خرج أبو محمد من المنزل وهو هنا الآن !"
    assert link.startswith("https://abc.trycloudflare.com/live/")
    # Telegram live-location pin follows the text
    assert any(c[0] == "sendLocation" and c[1]["live_period"] == notify.LIVE_PERIOD_SECONDS
               for c in calls)
    # The public link really serves location without login
    from fastapi.testclient import TestClient
    from app.main import app
    token = link.rsplit("/", 1)[1]
    r = TestClient(app).get(f"/api/public/live/{token}")
    assert r.status_code == 200 and r.json()["location"]["lat"] == pytest.approx(out_lat)


def test_exit_without_public_host_falls_back_to_maps_link(isolated_db, monkeypatch):
    monkeypatch.delenv("ECHOES_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setenv("ECHOES_AUTO_TUNNEL", "0")
    calls = []
    _tg_setup(monkeypatch, calls)
    safety.record_location(500.0 / 111_195.0, 0.0, isolated_db, accuracy_m=5.0, simulated=False)
    safety.drain_pending_notifications("")
    text = [c for c in calls if c[0] == "sendMessage"][0][1]["text"]
    assert text.startswith("خرج المريض من المنزل وهو هنا الآن !\nhttps://www.google.com/maps/")
    assert "127.0.0.1" not in text


def test_every_new_exit_notifies_and_live_pin_moves(isolated_db, monkeypatch):
    monkeypatch.setenv("ECHOES_PUBLIC_URL", "https://abc.trycloudflare.com")
    calls = []
    _tg_setup(monkeypatch, calls)
    out1, out2 = 500.0 / 111_195.0, 700.0 / 111_195.0
    dev = isolated_db

    safety.record_location(out1, 0.0, dev, accuracy_m=5.0, simulated=False)
    safety.drain_pending_notifications("X")
    # still outside: no new text, but the live pin is moved
    safety.record_location(out2, 0.0, dev, accuracy_m=5.0, simulated=False)
    safety.drain_pending_notifications("X")
    assert sum(1 for c in calls if c[0] == "sendMessage") == 1
    assert any(c[0] == "editMessageLiveLocation" for c in calls)

    # back home, then out again within minutes: must notify again
    safety.record_location(0.0, 0.0, dev, accuracy_m=5.0, simulated=False)
    safety.drain_pending_notifications("X")
    assert any(c[0] == "stopMessageLiveLocation" for c in calls)
    safety.record_location(out1, 0.0, dev, accuracy_m=5.0, simulated=False)
    safety.drain_pending_notifications("X")
    exits = [c for c in calls if c[0] == "sendMessage" and c[1]["text"].startswith("خرج")]
    assert len(exits) == 2
