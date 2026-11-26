"""Location, geofencing and alerts.

Deliberate design rules, all taken from the brief's own warnings:

1. A location is never described as "current" unless it is recent.
2. A stale or missing location is NOT evidence a person is in danger.
3. Alerts are de-duplicated so the family is not spammed.
4. Every alert carries the last reliable position and when it was recorded.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

from .db import connect

# A fix older than this is reported as stale, never as live.
FRESH_SECONDS = 15 * 60
# If no fix in this window, raise a "no recent location" alert.
STALE_ALERT_SECONDS = 60 * 60
# Alerts of the same kind for the same device cannot repeat within this window.
DEDUPE_WINDOW_SECONDS = 30 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime:
    """Parse SQLite's 'YYYY-MM-DD HH:MM:SS' (UTC) into an aware datetime."""
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def latest_location(device_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    age = (_now() - _parse(d["reported_at"])).total_seconds()
    d["age_seconds"] = int(age)
    d["is_fresh"] = age <= FRESH_SECONDS
    d["freshness_note"] = (
        "حديث" if d["is_fresh"]
        else f"قديم — آخر تحديث قبل {int(age // 60)} دقيقة"
    )
    return d


def record_location(lat: float, lon: float, device_id: int,
                    accuracy_m: float | None = None,
                    simulated: bool = True,
                    altitude_m: float | None = None,
                    reported_at: str | None = None) -> dict:
    """Store one fix.

    `reported_at` lets a device supply its own timestamp; the server keeps it
    only if it parses and is not wildly in the future, so a device with a bad
    clock cannot make a stale fix look fresh.
    """
    # A device clock can be wrong. Accept its timestamp only if it parses and
    # is no more than 2 minutes in the future; otherwise trust the server.
    safe_ts = None
    if reported_at:
        try:
            parsed = datetime.fromisoformat(reported_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed <= _now() + timedelta(minutes=2):
                safe_ts = parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            safe_ts = None

    with connect() as conn:
        if safe_ts:
            conn.execute(
                "INSERT INTO locations(device_id,lat,lon,accuracy_m,altitude_m,reported_at,simulated) "
                "VALUES (?,?,?,?,?,?,?)",
                (device_id, lat, lon, accuracy_m, altitude_m, safe_ts,
                 1 if simulated else 0),
            )
        else:
            conn.execute(
                "INSERT INTO locations(device_id,lat,lon,accuracy_m,altitude_m,simulated) "
                "VALUES (?,?,?,?,?,?)",
                (device_id, lat, lon, accuracy_m, altitude_m, 1 if simulated else 0),
            )
        conn.execute(
            "UPDATE devices SET last_seen_at = datetime('now'), connected = 1 WHERE id = ?",
            (device_id,),
        )
    _evaluate(device_id, lat, lon, accuracy_m)
    _tick_live_location(device_id, lat, lon, accuracy_m)
    conn_state = mark_online(device_id)
    return {"ok": True, "simulated": simulated,
            "reconnected": conn_state["reconnected"]}


def _tick_live_location(device_id: int, lat: float, lon: float,
                        accuracy_m: float | None) -> None:
    """While the patient is outside, move the Telegram live-location pin."""
    with connect() as conn:
        out = conn.execute(
            "SELECT 1 FROM settings WHERE key = ? AND value = 'out' LIMIT 1",
            (f"zone_state:{device_id}",),
        ).fetchone()
    if not out:
        return
    try:
        from . import notify
        notify.telegram_update_live(lat, lon, accuracy_m)
    except Exception:
        pass  # a failed pin update must never block storing the location


def reset_zone_state(device_id: int) -> None:
    """Forget the inside/outside state (used by the test simulator only)."""
    with connect() as conn:
        conn.execute("DELETE FROM settings WHERE key LIKE ? OR key = ?",
                     (f"returned:{device_id}:%", f"zone_state:{device_id}"))


def _raise_alert(conn, kind: str, message: str, device_id: int,
                 lat=None, lon=None, location_at=None, dedupe_suffix: str = "") -> bool:
    """Insert an alert unless an identical one was raised recently."""
    key = f"{kind}:{device_id}:{dedupe_suffix}"
    row = conn.execute(
        "SELECT id, created_at FROM alerts WHERE dedupe_key = ? "
        "ORDER BY id DESC LIMIT 1", (key,)
    ).fetchone()
    if row:
        age = (_now() - _parse(row["created_at"])).total_seconds()
        if age < DEDUPE_WINDOW_SECONDS:
            return False
    conn.execute(
        "INSERT INTO alerts(kind,message,device_id,lat,lon,location_at,dedupe_key) "
        "VALUES (?,?,?,?,?,?,?)",
        (kind, message, device_id, lat, lon, location_at, key),
    )
    return True


DEFAULT_SEED_ZONE = (24.7136, 46.6753)   # placeholder «المنزل» created at first run
MAX_MARGIN_M = 50.0                       # cap on the GPS-uncertainty band
IGNORE_ACCURACY_M = 1500.0                # fixes this vague are not judged at all


def _margin(accuracy_m: float | None, radius_m: float) -> float:
    """GPS uncertainty band, capped. Phones indoors often report 60–500 m
    accuracy; using the full value made exits impossible to confirm (and a
    return home impossible to confirm, which then blocked every later exit)."""
    acc = max(0.0, float(accuracy_m or 0.0))
    return min(acc, MAX_MARGIN_M, max(15.0, 0.3 * float(radius_m)))


def _adopt_first_fix_as_home(conn, device_id: int, lat: float, lon: float) -> None:
    """If the only zone is still the untouched placeholder in Riyadh and the
    tracker's first real fix is far from it, move «المنزل» to that first fix.
    Otherwise the patient is 'outside' from the first second and no exit
    can ever be detected."""
    zones = conn.execute("SELECT * FROM safe_zones").fetchall()
    if len(zones) != 1:
        return
    z = zones[0]
    if (round(z["lat"], 4), round(z["lon"], 4)) != DEFAULT_SEED_ZONE:
        return
    if haversine_m(lat, lon, z["lat"], z["lon"]) < 20000:
        return
    n = conn.execute("SELECT COUNT(*) c FROM locations WHERE device_id=? AND simulated=0",
                     (device_id,)).fetchone()["c"]
    if n > 1:
        return
    conn.execute("UPDATE safe_zones SET lat=?, lon=?, enabled=1 WHERE id=?", (lat, lon, z["id"]))
    conn.execute("DELETE FROM settings WHERE key LIKE 'returned:%' OR key LIKE 'zone_state:%'")


def reset_zone_states() -> None:
    """Forget inside/outside memory (call after zones change)."""
    with connect() as conn:
        conn.execute("DELETE FROM settings WHERE key LIKE 'returned:%' OR key LIKE 'zone_state:%'")


def _evaluate(device_id: int, lat: float, lon: float,
              accuracy_m: float | None = None) -> None:
    """Geofence check. The safe area is the UNION of enabled zones: the patient
    is 'outside' only when he is clearly outside every zone, and an alert is
    raised on each inside→outside transition (never repeated during one trip)."""
    if accuracy_m is not None and float(accuracy_m) > IGNORE_ACCURACY_M:
        return
    with connect() as conn:
        is_sim = conn.execute("SELECT simulated FROM devices WHERE id=?", (device_id,)).fetchone()
        if is_sim is not None and not is_sim["simulated"]:
            _adopt_first_fix_as_home(conn, device_id, lat, lon)
        zones = conn.execute("SELECT * FROM safe_zones WHERE enabled = 1").fetchall()
        if not zones:
            return
        info = []
        for z in zones:
            dist = haversine_m(lat, lon, z["lat"], z["lon"])
            m = _margin(accuracy_m, z["radius_m"])
            info.append((z, dist, dist > z["radius_m"] + m, dist <= z["radius_m"] - m * 0.5))
        outside_all = all(o for _, _, o, _ in info)
        inside_any = any(i for _, _, _, i in info)
        key = f"zone_state:{device_id}"
        prev_row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        prev = prev_row["value"] if prev_row else "in"   # unknown → assume home
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        z, dist = min(((z, d) for z, d, _, _ in info), key=lambda t: t[1] - t[0]["radius_m"])

        def set_state(v):
            conn.execute("INSERT INTO settings(key,value) VALUES (?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, v))

        if outside_all and prev != "out":
            set_state("out")
            if _raise_alert(conn, "exited_safe_zone",
                            f"خرج من النطاق الآمن «{z['name']}» (يبعد {int(dist)} م عن المركز)",
                            device_id, lat, lon, now, dedupe_suffix=f"{z['id']}:{time.time_ns()}"):
                conn.execute(
                    "INSERT INTO pending_notifications"
                    "(kind,zone_id,zone_name,lat,lon,event_at,accuracy_m) VALUES (?,?,?,?,?,?,?)",
                    ("exited_safe_zone", z["id"], z["name"], lat, lon, now, accuracy_m))
        elif inside_any and prev == "out":
            set_state("in")
            zin = min(info, key=lambda t: t[1])[0]
            if _raise_alert(conn, "returned_safe_zone", f"عاد إلى النطاق الآمن «{zin['name']}»",
                            device_id, lat, lon, now, dedupe_suffix=f"ret{time.time_ns()}"):
                conn.execute(
                    "INSERT INTO pending_notifications"
                    "(kind,zone_id,zone_name,lat,lon,event_at,accuracy_m) VALUES (?,?,?,?,?,?,?)",
                    ("returned_safe_zone", zin["id"], zin["name"], lat, lon, now, accuracy_m))
        elif inside_any and prev_row is None:
            set_state("in")


def _flag_zone_exit(zone_id: int, zone_name: str, lat: float, lon: float,
                    when: str) -> None:
    """Mark that a zone exit is pending notification.

    Delivery itself happens after the connection closes (it does network I/O
    and opens its own connection), so we queue the facts here.
    """
    with connect() as conn:
        conn.execute(
            "INSERT INTO pending_notifications(kind,zone_id,zone_name,lat,lon,event_at) "
            "VALUES ('exited_safe_zone',?,?,?,?,?)",
            (zone_id, zone_name, lat, lon, when),
        )


def drain_pending_notifications(patient_name: str = "") -> list[dict]:
    """Send queued notifications and clear them. Returns what was attempted."""
    from . import notify

    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_notifications ORDER BY id"
        ).fetchall()
        pending = [dict(r) for r in rows]

    results = []
    for p in pending:
        with connect() as conn:
            alert = conn.execute(
                "SELECT id FROM alerts WHERE kind=? ORDER BY id DESC LIMIT 1",
                (p["kind"],),
            ).fetchone()
            dev = conn.execute(
                "SELECT connected, battery FROM devices ORDER BY id LIMIT 1"
            ).fetchone()
        alert_id = alert["id"] if alert else 0
        online = bool(dev["connected"]) if dev else None
        battery = dev["battery"] if dev else None
        acc = p.get("accuracy_m")

        if p["kind"] == "returned_safe_zone":
            r = notify.notify_returned_zone(
                alert_id, patient_name, p["lat"], p["lon"], p["event_at"],
                accuracy_m=acc, device_online=online, battery=battery,
            )
        else:
            r = notify.notify_geofence_exit(
                alert_id, patient_name, p["lat"], p["lon"], p["event_at"],
                p["zone_name"] or "",
                accuracy_m=acc, device_online=online, battery=battery,
            )
        results.append(r)
        with connect() as conn:
            conn.execute("DELETE FROM pending_notifications WHERE id = ?", (p["id"],))
    return results


def _state(conn, device_id: int):
    row = conn.execute("SELECT * FROM device_state WHERE device_id = ?", (device_id,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO device_state(device_id,online) VALUES (?,1)", (device_id,))
        row = conn.execute("SELECT * FROM device_state WHERE device_id = ?", (device_id,)).fetchone()
    return row


def mark_online(device_id: int) -> dict:
    """Called on every accepted location. Returns {'reconnected': bool}."""
    with connect() as conn:
        st = _state(conn, device_id)
        was_offline = st["online"] == 0
        conn.execute(
            "UPDATE device_state SET online = 1, offline_since = NULL, "
            "updated_at = datetime('now') WHERE device_id = ?",
            (device_id,),
        )
    return {"reconnected": was_offline}


def mark_offline_if_silent(device_id: int, silent_seconds: int,
                           threshold_seconds: int = STALE_ALERT_SECONDS) -> dict:
    """Flip to offline exactly once when a device goes quiet for too long."""
    if silent_seconds <= threshold_seconds:
        return {"offline": False, "transitioned": False}
    with connect() as conn:
        st = _state(conn, device_id)
        if st["online"] == 0:
            return {"offline": True, "transitioned": False}
        conn.execute(
            "UPDATE device_state SET online = 0, offline_since = datetime('now'), "
            "updated_at = datetime('now') WHERE device_id = ?",
            (device_id,),
        )
    return {"offline": True, "transitioned": True}


def _silence_seconds(d, last) -> float | None:
    """How long the device has been quiet. A watch in «report on exit» mode
    proves it is alive with heartbeats, so those count too."""
    times = []
    if last:
        times.append(_parse(last["reported_at"]))
    keys = d.keys() if hasattr(d, "keys") else []
    if "report_mode" in keys and d["report_mode"] == "on_exit" and d["zone_checked_at"]:
        times.append(_parse(d["zone_checked_at"]))
    if not times:
        return None
    return (_now() - max(times)).total_seconds()


def check_connection_events(patient_name: str = "") -> dict:
    """Scan devices; alert on transitions only. Returns what happened."""
    from . import notify

    results = {"offline": [], "reconnected": []}
    with connect() as conn:
        devices = conn.execute("SELECT * FROM devices").fetchall()
        for d in devices:
            last = conn.execute(
                "SELECT * FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT 1",
                (d["id"],),
            ).fetchone()
            if not last and not ("report_mode" in d.keys() and d["report_mode"] == "on_exit"):
                continue
            silent = _silence_seconds(d, last)
            if silent is not None and silent > STALE_ALERT_SECONDS:
                tr = mark_offline_if_silent(d["id"], silent)
                if tr["transitioned"]:
                    with connect() as c2:
                        aid = _raise_alert(
                            c2, "device_offline",
                            f"انقطاع اتصال الجهاز منذ {int(silent // 60)} دقيقة",
                            d["id"], last["lat"] if last else None,
                            last["lon"] if last else None,
                            last["reported_at"] if last else None,
                            dedupe_suffix=(last["reported_at"] if last else str(int(_now().timestamp() // 3600))),
                        )
                    results["offline"].append(
                        notify.notify_connection_lost(
                            0, patient_name, last["lat"] if last else None,
                            last["lon"] if last else None, int(silent // 60),
                        )
                    )
    return results


def check_staleness() -> list[dict]:
    """Raise alerts for devices that stopped reporting. Explicitly does NOT
    claim the person is in danger."""
    raised = []
    with connect() as conn:
        devices = conn.execute("SELECT * FROM devices").fetchall()
        for d in devices:
            last = conn.execute(
                "SELECT * FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT 1",
                (d["id"],),
            ).fetchone()
            on_exit = "report_mode" in d.keys() and d["report_mode"] == "on_exit"
            if on_exit:
                # silent by design while inside the safe zone: only worry if
                # the heartbeat itself stopped (handled as device_offline)
                continue
            if not last:
                if _raise_alert(conn, "no_recent_location",
                                "لا يوجد موقع مسجّل لهذا الجهاز",
                                d["id"], dedupe_suffix="none"):
                    raised.append({"device_id": d["id"], "kind": "no_recent_location"})
                continue
            age = (_now() - _parse(last["reported_at"])).total_seconds()
            if age > STALE_ALERT_SECONDS:
                if _raise_alert(
                    conn, "stale_location",
                    f"لا يوجد تحديث موقع منذ {int(age // 60)} دقيقة — الموقع الحالي غير متاح",
                    d["id"], last["lat"], last["lon"], last["reported_at"],
                    dedupe_suffix=str(last["id"]),
                ):
                    raised.append({"device_id": d["id"], "kind": "stale_location"})
    return raised


def family_ask_where(device_id: int) -> dict:
    """The family's 'where is he now?' question (brief section 14).

    Returns language that never asserts danger and never calls a stale fix live.
    """
    with connect() as conn:
        dev = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not dev:
            return {"ok": False, "detail": "unknown device"}
        last = latest_location(device_id)
        alerts = _recent_alerts(conn, device_id, limit=3)

    if last is None:
        return {
            "ok": True,
            "status": "no_location",
            "answer": "لا يوجد موقع مسجّل. لا نعرف مكانه، ولا نفترض أنه في خطر.",
            "location": None,
            "device_connected": bool(dev["connected"]),
            "recent_alerts": alerts,
        }

    if last["is_fresh"]:
        answer = (
            f"آخر موقع قبل {max(1, last['age_seconds'] // 60)} دقيقة. "
            f"الموقع حديث لكنه ليس بثًّا مباشرًا."
        )
        status = "fresh"
    else:
        answer = (
            f"آخر موقع معروف من قبل {last['age_seconds'] // 60} دقيقة. "
            "الموقع الحالي غير متاح — هذا لا يعني أنه في خطر."
        )
        status = "stale"

    return {
        "ok": True,
        "status": status,
        "answer": answer,
        "location": last,
        "device_connected": bool(dev["connected"]),
        "recent_alerts": alerts,
    }


def _recent_alerts(conn, device_id: int, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        "SELECT id, kind, message, lat, lon, location_at, created_at, read_at "
        "FROM alerts WHERE device_id = ? ORDER BY id DESC LIMIT ?",
        (device_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_alerts(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def request_help(device_id: int) -> dict:
    """Patient pressed help. Raises one alert, deduplicated."""
    with connect() as conn:
        last = conn.execute(
            "SELECT * FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
        created = _raise_alert(
            conn, "help_requested",
            "طلب مساعدة من الجهاز",
            device_id,
            last["lat"] if last else None,
            last["lon"] if last else None,
            last["reported_at"] if last else None,
            dedupe_suffix="help",
        )
    return {"ok": True, "alert_created": created}


BATTERY_LOW_PCT = 15


def check_battery_alerts(patient_name: str = "") -> list[dict]:
    """Alert once when a device battery drops below the threshold."""
    from . import notify

    raised = []
    with connect() as conn:
        devices = conn.execute(
            "SELECT * FROM devices WHERE battery IS NOT NULL").fetchall()
        for d in devices:
            if d["battery"] is None or d["battery"] > BATTERY_LOW_PCT:
                continue
            with connect() as c2:
                created = _raise_alert(
                    c2, "battery_low",
                    f"بطارية الجهاز منخفضة ({d['battery']}%)",
                    d["id"], None, None, None,
                    dedupe_suffix=f"b{d['battery'] // 5}",
                )
            if created:
                loc = latest_location(d["id"])
                msg = notify.compose(
                    "battery_low", patient_name,
                    loc["lat"] if loc else None,
                    loc["lon"] if loc else None,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    extra=f"بطارية الجهاز {d['battery']}% — يُفضّل الشحن.",
                    device_online=bool(d["connected"]), battery=d["battery"],
                )
                raised.append({**msg, **notify.deliver(0, msg, patient_name)})
    return raised
