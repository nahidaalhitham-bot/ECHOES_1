package app.echoes.watch

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Small HTTP helpers. Runs on a background thread only. */
object Api {
    data class Resp(val code: Int, val body: String)

    fun request(method: String, url: String, json: String?, token: String?): Resp {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = 15000
            conn.readTimeout = 15000
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            if (token != null) conn.setRequestProperty("Authorization", "Bearer $token")
            if (json != null) {
                conn.doOutput = true
                conn.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val stream = if (code >= 400) conn.errorStream else conn.inputStream
            val body = stream?.bufferedReader()?.use { it.readText() } ?: ""
            return Resp(code, body)
        } finally {
            conn.disconnect()
        }
    }

    /**
     * The laptop's public link changes on every restart. The ECHOES app posts
     * the current one to a private ntfy.sh channel; read the latest from there.
     */
    fun latestUrlFromTopic(topic: String): String? {
        val r = try {
            request("GET", "https://ntfy.sh/$topic/json?poll=1&since=24h", null, null)
        } catch (e: Exception) {
            return null
        }
        if (r.code != 200) return null
        var found: String? = null
        r.body.lineSequence().filter { it.isNotBlank() }.forEach { line ->
            try {
                val o = JSONObject(line)
                if (o.optString("event") == "message") {
                    val u = JSONObject(o.getString("message")).optString("url")
                    if (u.startsWith("https://")) found = u.trimEnd('/')
                }
            } catch (_: Exception) {
            }
        }
        return found
    }

    /** {url, code} that the dashboard sent after scanning this watch's QR. */
    fun pendingClaim(pairId: String): Pair<String, String>? {
        val r = try {
            request("GET", "https://ntfy.sh/echoes-claim-$pairId/json?poll=1&since=15m", null, null)
        } catch (e: Exception) {
            return null
        }
        if (r.code != 200) return null
        var found: Pair<String, String>? = null
        r.body.lineSequence().filter { it.isNotBlank() }.forEach { line ->
            try {
                val o = JSONObject(line)
                if (o.optString("event") == "message") {
                    val m = JSONObject(o.getString("message"))
                    val u = m.optString("url")
                    val code = m.optString("code")
                    if (u.startsWith("https://") && code.length == 6) found = Pair(u.trimEnd('/'), code)
                }
            } catch (_: Exception) {
            }
        }
        return found
    }

    /**
     * POST with the device token. If the saved address no longer answers,
     * fetch the new one from the relay channel and try once more.
     * Returns the HTTP status, or null when there is no connection.
     */
    fun postToEchoes(c: Context, path: String, json: String?): Int? {
        val token = Prefs.token(c) ?: return null
        fun attempt(): Int? = try {
            request("POST", (Prefs.url(c) ?: return null) + path, json, token).code
        } catch (e: Exception) {
            null
        }
        var status = attempt()
        if (status == null || status == 404 || status == 502 || status == 503 || status == 530) {
            val topic = Prefs.topic(c)
            val fresh = if (topic != null) latestUrlFromTopic(topic) else null
            if (fresh != null && fresh != Prefs.url(c)) {
                Prefs.setUrl(c, fresh)
                status = attempt()
            }
        }
        return status
    }
}
