package app.echoes.watch

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.BatteryManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Sends the location ONLY when the patient leaves the safe zone.
 *
 *  - Inside the zone: the watch checks its position quietly every minute and
 *    sends nothing — just a tiny «I'm on, inside» heartbeat every 15 minutes
 *    (no coordinates), so the family knows the watch still works.
 *  - Leaves the zone: sends the location immediately (the family gets the
 *    «left the safe zone» alert), then keeps sending every ~20 s so they can
 *    follow him on the map.
 *  - Back inside: sends one last fix (the family is told he returned) and goes
 *    quiet again.
 *  - No safe zone set in the dashboard: sends nothing and says so.
 */
class TrackerService : Service(), LocationListener {

    companion object {
        const val CHANNEL = "echoes_tracking"
        const val CHECK_INSIDE_MS = 60_000L       // quiet check while home
        const val SEND_OUTSIDE_MS = 20_000L       // live updates while outside
        const val HEARTBEAT_MS = 15 * 60_000L
        const val ZONES_REFRESH_MS = 30 * 60_000L
        const val MAX_ACCURACY_M = 150f           // ignore very rough fixes
        const val EXIT_MARGIN_M = 25f             // hysteresis, no flapping at the door
    }

    private data class Zone(val name: String, val lat: Double, val lon: Double, val radius: Double)

    private lateinit var lm: LocationManager
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var zones: List<Zone> = emptyList()
    @Volatile private var zonesLoaded = false
    @Volatile private var outside: Boolean? = null   // null = not known yet
    @Volatile private var currentZone: String? = null
    private var lastSentAt = 0L
    private var providers: List<String> = emptyList()
    private var currentInterval = 0L

    private val heartbeat = object : Runnable {
        override fun run() {
            sendHeartbeat()
            main.postDelayed(this, HEARTBEAT_MS)
        }
    }
    private val zonesRefresher = object : Runnable {
        override fun run() {
            io.execute { loadZones() }
            main.postDelayed(this, ZONES_REFRESH_MS)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "ECHOES", NotificationManager.IMPORTANCE_LOW)
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val n = Notification.Builder(this, CHANNEL)
            .setContentTitle("ECHOES")
            .setContentText("يراقب النطاق الآمن — يرسل الموقع عند الخروج فقط")
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        lm = getSystemService(LOCATION_SERVICE) as LocationManager
        if (!hasPermission()) {
            Prefs.setLast(this, null, "لا يوجد إذن الموقع")
            stopSelf()
            return
        }
        val available = lm.allProviders
        providers = when {
            "fused" in available -> listOf("fused")
            else -> listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
                .filter { it in available }
                .ifEmpty { listOf(LocationManager.GPS_PROVIDER) }
        }
        Prefs.setLast(this, null, "يجهّز النطاق الآمن…")
        main.post(zonesRefresher)
        main.postDelayed(heartbeat, 5_000)
        requestUpdates(CHECK_INSIDE_MS)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    private fun hasPermission() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    private fun requestUpdates(intervalMs: Long) {
        if (intervalMs == currentInterval) return
        currentInterval = intervalMs
        try {
            lm.removeUpdates(this)
        } catch (_: Exception) {
        }
        for (p in providers) {
            try {
                lm.requestLocationUpdates(p, intervalMs, 0f, this, Looper.getMainLooper())
            } catch (_: Exception) {
            }
        }
    }

    // ------------------------------------------------------------ zones ---

    private fun loadZones() {
        val token = Prefs.token(this) ?: return
        fun fetch(): Api.Resp? = try {
            Api.request("GET", (Prefs.url(this) ?: return null) + "/api/device/zones", null, token)
        } catch (e: Exception) {
            null
        }
        var r = fetch()
        if (r == null || r.code == 404 || r.code == 502 || r.code == 503 || r.code == 530) {
            val topic = Prefs.topic(this)
            val fresh = if (topic != null) Api.latestUrlFromTopic(topic) else null
            if (fresh != null && fresh != Prefs.url(this)) {
                Prefs.setUrl(this, fresh)
                r = fetch()
            }
        }
        if (r == null || r.code != 200) {
            if (r?.code == 401) Prefs.setLast(this, null, "انتهى الربط — اربطي الساعة برمز جديد")
            return
        }
        try {
            val arr: JSONArray = JSONObject(r.body).getJSONArray("zones")
            zones = (0 until arr.length()).map {
                val z = arr.getJSONObject(it)
                Zone(z.optString("name", "النطاق الآمن"), z.getDouble("lat"),
                    z.getDouble("lon"), z.optDouble("radius_m", 300.0))
            }
            zonesLoaded = true
            if (zones.isEmpty()) Prefs.setLast(this, null, "لا يوجد نطاق آمن — حدديه من لوحة التحكم")
        } catch (_: Exception) {
        }
    }

    /** Distance beyond the nearest zone's edge (negative = inside). */
    private fun beyondEdge(loc: Location): Pair<Float, Zone>? {
        var best: Pair<Float, Zone>? = null
        for (z in zones) {
            val d = FloatArray(1)
            Location.distanceBetween(loc.latitude, loc.longitude, z.lat, z.lon, d)
            val edge = d[0] - z.radius.toFloat()
            if (best == null || edge < best.first) best = Pair(edge, z)
        }
        return best
    }

    // --------------------------------------------------------- locations ---

    override fun onLocationChanged(location: Location) {
        if (!zonesLoaded || zones.isEmpty()) return
        if (location.hasAccuracy() && location.accuracy > MAX_ACCURACY_M) return
        val (edge, zone) = beyondEdge(location) ?: return
        val acc = if (location.hasAccuracy()) location.accuracy else 30f
        val wasOutside = outside
        val nowOutside = when {
            edge - acc > EXIT_MARGIN_M -> true            // clearly outside
            edge + acc < 0f || edge < -EXIT_MARGIN_M -> false  // clearly inside
            else -> wasOutside ?: false                   // at the edge: keep state
        }
        outside = nowOutside
        currentZone = zone.name

        if (nowOutside) {
            requestUpdates(SEND_OUTSIDE_MS)
            val now = System.currentTimeMillis()
            if (wasOutside != true || now - lastSentAt >= SEND_OUTSIDE_MS - 2_000) {
                lastSentAt = now
                io.execute { sendLocation(location, leaving = wasOutside != true) }
            }
        } else {
            if (wasOutside == true) {
                // came back: one last fix so the family is told he returned
                io.execute { sendLocation(location, leaving = false) }
            }
            requestUpdates(CHECK_INSIDE_MS)
            if (wasOutside != false) {
                Prefs.setLast(this, System.currentTimeMillis(), "داخل ${zone.name} — لا يُرسل الموقع ✓")
                io.execute { sendHeartbeat() }
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) {}
    override fun onProviderEnabled(provider: String) {}
    override fun onProviderDisabled(provider: String) {}

    private fun battery(): Int? {
        val bm = getSystemService(BATTERY_SERVICE) as BatteryManager
        val v = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        return if (v in 0..100) v else null
    }

    private fun sendLocation(loc: Location, leaving: Boolean) {
        val json = JSONObject()
            .put("lat", loc.latitude)
            .put("lon", loc.longitude)
            .put("accuracy_m", loc.accuracy.toDouble())
        battery()?.let { json.put("battery", it) }
        val status = Api.postToEchoes(this, "/api/device/report", json.toString())
        when {
            status != null && status in 200..299 -> Prefs.setLast(
                this, System.currentTimeMillis(),
                if (outside == true) "خارج النطاق الآمن — يرسل الموقع للعائلة" else "عاد للنطاق الآمن ✓")
            status == 401 -> Prefs.setLast(this, null, "انتهى الربط — اربطي الساعة برمز جديد")
            status == null -> Prefs.setLast(this, null, "لا يوجد اتصال بالإنترنت")
            else -> Prefs.setLast(this, null, "التطبيق على الكمبيوتر لا يرد ($status)")
        }
        if (leaving) sendHeartbeat()
    }

    private fun sendHeartbeat() {
        io.execute {
            val json = JSONObject()
            battery()?.let { json.put("battery", it) }
            outside?.let { json.put("inside", !it) }
            currentZone?.let { json.put("zone", it) }
            val st = Api.postToEchoes(this, "/api/device/heartbeat", json.toString())
            if (st == 401) Prefs.setLast(this, null, "انتهى الربط — اربطي الساعة برمز جديد")
        }
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        try {
            lm.removeUpdates(this)
        } catch (_: Exception) {
        }
        io.shutdown()
        super.onDestroy()
    }
}
