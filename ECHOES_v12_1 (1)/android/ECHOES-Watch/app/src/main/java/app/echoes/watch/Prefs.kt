package app.echoes.watch

import android.content.Context

/** Everything the watch remembers after pairing. */
object Prefs {
    private fun sp(c: Context) = c.getSharedPreferences("echoes", Context.MODE_PRIVATE)

    fun url(c: Context): String? = sp(c).getString("url", null)
    fun token(c: Context): String? = sp(c).getString("token", null)
    fun topic(c: Context): String? = sp(c).getString("topic", null)
    fun patient(c: Context): String = sp(c).getString("patient", "") ?: ""
    fun lastSentAt(c: Context): Long = sp(c).getLong("last_sent", 0L)
    fun lastStatus(c: Context): String = sp(c).getString("last_status", "") ?: ""
    fun paired(c: Context): Boolean = token(c) != null && url(c) != null

    fun setUrl(c: Context, url: String) = sp(c).edit().putString("url", url).apply()

    /** Random id shown in the pairing QR (new one after every unpair). */
    fun pairId(c: Context): String {
        sp(c).getString("pair_id", null)?.let { return it }
        val chars = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
        val rnd = java.security.SecureRandom()
        val id = (1..20).map { chars[rnd.nextInt(chars.length)] }.joinToString("")
        sp(c).edit().putString("pair_id", id).apply()
        return id
    }

    fun savePairing(c: Context, url: String, token: String, topic: String, patient: String) {
        sp(c).edit()
            .putString("url", url).putString("token", token)
            .putString("topic", topic).putString("patient", patient)
            .apply()
    }

    fun setLast(c: Context, sentAt: Long?, status: String) {
        val e = sp(c).edit().putString("last_status", status)
        if (sentAt != null) e.putLong("last_sent", sentAt)
        e.apply()
    }

    fun clear(c: Context) = sp(c).edit().clear().apply()
}
