package app.echoes.watch

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Restart location sharing after the watch reboots. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED && Prefs.paired(context)) {
            try {
                context.startForegroundService(Intent(context, TrackerService::class.java))
            } catch (_: Exception) {
            }
        }
    }
}
