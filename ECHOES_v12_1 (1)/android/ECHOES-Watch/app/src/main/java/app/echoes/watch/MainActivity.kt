package app.echoes.watch

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.text.InputFilter
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.view.WindowManager
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Two screens, built in code (no layout files):
 *  - not paired: type the 6-character code shown in the ECHOES dashboard;
 *  - paired: status + a big «أحتاج مساعدة» button.
 */
class MainActivity : Activity() {

    private val ui = Handler(Looper.getMainLooper())
    private lateinit var root: LinearLayout
    private var statusView: TextView? = null
    private var sosArmedUntil = 0L
    @Volatile private var listening = false
    @Volatile private var pairing = false

    private val refresher = object : Runnable {
        override fun run() {
            updateStatus()
            ui.postDelayed(this, 5000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val scroll = ScrollView(this)
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            val p = dp(22)
            setPadding(p, dp(28), p, dp(40))
            layoutDirection = View.LAYOUT_DIRECTION_RTL
        }
        scroll.addView(root)
        scroll.setBackgroundColor(Color.parseColor("#1E1530"))
        setContentView(scroll)
        render()
    }

    override fun onResume() {
        super.onResume()
        render()
        ui.post(refresher)
        if (Prefs.paired(this) && hasLocation()) startTracking()
    }

    override fun onPause() {
        ui.removeCallbacks(refresher)
        listening = false
        super.onPause()
    }

    // ------------------------------------------------------------ screens --

    private fun render() {
        root.removeAllViews()
        statusView = null
        if (Prefs.paired(this)) renderPaired() else renderPairing()
    }

    private fun renderPairing() {
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        root.addView(title("ECHOES"))
        root.addView(text("امسحي هذا الرمز من لوحة التحكم ← حالة الجهاز ← «مسح QR الساعة»", 12f, "#CBB8E6"))
        val qrSize = dp(150)
        val qr = ImageView(this).apply {
            setImageBitmap(qrBitmap("ECHOES:" + Prefs.pairId(this@MainActivity), 300))
            setBackgroundColor(Color.WHITE)
            val pad = dp(6)
            setPadding(pad, pad, pad, pad)
        }
        root.addView(qr, LinearLayout.LayoutParams(qrSize, qrSize))
        val listenMsg = text("بانتظار المسح…", 12f, "#9FE3B0")
        root.addView(listenMsg)
        startListening(listenMsg)

        root.addView(text("أو اكتبي رمزًا من 6 حروف:", 12f, "#7C6A99"))
        val input = EditText(this).apply {
            hint = "ABC-123"
            textSize = 20f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setHintTextColor(Color.parseColor("#7C6A99"))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
            filters = arrayOf<InputFilter>(InputFilter.AllCaps(), InputFilter.LengthFilter(7))
            layoutDirection = View.LAYOUT_DIRECTION_LTR
        }
        root.addView(input, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        val msg = text("", 12f, "#FFB4A8")
        val btn = button("ربط الساعة", "#7628B8")
        btn.setOnClickListener {
            val code = input.text.toString().uppercase().replace("-", "").replace(" ", "")
            if (code.length != 6) {
                msg.text = "الرمز من 6 حروف"
                return@setOnClickListener
            }
            btn.isEnabled = false
            msg.setTextColor(Color.parseColor("#CBB8E6"))
            msg.text = "جارٍ الربط…"
            Thread { pair(code, null, msg, btn) }.start()
        }
        root.addView(btn)
        root.addView(msg)
    }

    private fun renderPaired() {
        val name = Prefs.patient(this)
        root.addView(title(if (name.isNotBlank()) name.split(" ").first() else "ECHOES"))
        val sv = text("", 13f, "#CBB8E6")
        statusView = sv
        root.addView(sv)
        updateStatus()

        val sos = button("أحتاج مساعدة", "#D92D20").apply {
            textSize = 18f
            minHeight = dp(78)
        }
        sos.setOnClickListener {
            val now = System.currentTimeMillis()
            if (now > sosArmedUntil) {
                // two taps, so a brush of the sleeve does not alarm the family
                sosArmedUntil = now + 4000
                sos.text = "اضغط مرة ثانية للتأكيد"
                ui.postDelayed({ sos.text = "أحتاج مساعدة" }, 4000)
                return@setOnClickListener
            }
            sosArmedUntil = 0
            sos.text = "جارٍ الإرسال…"
            Thread {
                val st = Api.postToEchoes(this, "/api/device/sos", null)
                ui.post {
                    vibrate()
                    sos.text = if (st != null && st in 200..299) "تم إبلاغ أهلك ✓" else "تعذّر الإرسال — حاول مجددًا"
                    ui.postDelayed({ sos.text = "أحتاج مساعدة" }, 6000)
                }
            }.start()
        }
        root.addView(sos)

        if (!hasLocation()) {
            val allow = button("السماح بالموقع", "#3B2A57")
            allow.setOnClickListener { askPermissions() }
            root.addView(allow)
        }

        val unpair = TextView(this).apply {
            text = "إلغاء الربط (اضغط مطولًا)"
            textSize = 11f
            setTextColor(Color.parseColor("#7C6A99"))
            gravity = Gravity.CENTER
            setPadding(0, dp(18), 0, 0)
            setOnLongClickListener {
                stopService(Intent(this@MainActivity, TrackerService::class.java))
                Prefs.clear(this@MainActivity)
                render()
                true
            }
        }
        root.addView(unpair)
    }

    private fun updateStatus() {
        val v = statusView ?: return
        val last = Prefs.lastSentAt(this)
        val time = if (last > 0)
            " · آخر إرسال " + SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(last))
        else ""
        v.text = (Prefs.lastStatus(this).ifBlank { "جاهز" }) + time
    }

    // ------------------------------------------------------------ pairing --

    /** Poll the watch's own channel until the dashboard scans the QR. */
    private fun startListening(msg: TextView) {
        if (listening) return
        listening = true
        Thread {
            while (listening && !Prefs.paired(this)) {
                val claim = Api.pendingClaim(Prefs.pairId(this))
                if (claim != null && !pairing) {
                    listening = false
                    ui.post { msg.text = "تم المسح — جارٍ الربط…" }
                    pair(claim.second, claim.first, msg, null)
                    break
                }
                try { Thread.sleep(3000) } catch (_: InterruptedException) { break }
            }
        }.start()
    }

    private fun qrBitmap(content: String, size: Int): Bitmap {
        val hints = mapOf(EncodeHintType.MARGIN to 0)
        val m = QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, size, size, hints)
        val px = IntArray(size * size)
        for (y in 0 until size) for (x in 0 until size) {
            px[y * size + x] = if (m.get(x, y)) Color.BLACK else Color.WHITE
        }
        return Bitmap.createBitmap(px, size, size, Bitmap.Config.ARGB_8888)
    }

    private fun pair(code: String, knownUrl: String?, msg: TextView, btn: Button?) {
        pairing = true
        fun fail(t: String) = ui.post {
            pairing = false
            msg.setTextColor(Color.parseColor("#FFB4A8")); msg.text = t; btn?.isEnabled = true
            if (btn == null) startListening(msg)
        }
        val url = knownUrl ?: Api.latestUrlFromTopic("echoes-pair-$code")
        if (url == null) {
            fail("لم أجد هذا الرمز. تأكدي منه ومن اتصال الساعة بالإنترنت.")
            return
        }
        val resp: Api.Resp
        try {
            resp = Api.request("POST", "$url/api/devices/claim",
                JSONObject().put("code", code).toString(), null)
        } catch (e: Exception) {
            fail("تعذّر الوصول للتطبيق على الكمبيوتر. تأكدي أنه شغّال.")
            return
        }
        if (resp.code != 200) {
            fail("الرمز غير صحيح أو انتهت صلاحيته. أنشئي رمزًا جديدًا.")
            return
        }
        val o = JSONObject(resp.body)
        Prefs.savePairing(this, url, o.getString("token"), o.getString("relay_topic"),
            o.optString("patient_name", ""))
        Prefs.setLast(this, null, "تم الربط ✓")
        pairing = false
        ui.post {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            vibrate()
            render()
            askPermissions()
        }
    }

    // -------------------------------------------------------- permissions --

    private fun hasLocation() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun askPermissions() {
        val wanted = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
        )
        if (android.os.Build.VERSION.SDK_INT >= 33) wanted.add(Manifest.permission.POST_NOTIFICATIONS)
        requestPermissions(wanted.toTypedArray(), 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>,
                                            grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 1 && hasLocation()) {
            startTracking()
            // «Allow all the time» keeps sharing after a reboot. Asked separately,
            // as Android requires.
            if (checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) !=
                PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION), 2)
            }
        }
        render()
    }

    private fun startTracking() {
        try {
            startForegroundService(Intent(this, TrackerService::class.java))
        } catch (_: Exception) {
        }
    }

    // ---------------------------------------------------------------- ui ---

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun title(t: String) = TextView(this).apply {
        text = t
        textSize = 20f
        setTypeface(typeface, Typeface.BOLD)
        setTextColor(Color.WHITE)
        gravity = Gravity.CENTER
        setPadding(0, 0, 0, dp(6))
    }

    private fun text(t: String, size: Float, color: String) = TextView(this).apply {
        text = t
        textSize = size
        setTextColor(Color.parseColor(color))
        gravity = Gravity.CENTER
        setPadding(0, dp(4), 0, dp(8))
    }

    private fun button(t: String, color: String) = Button(this).apply {
        text = t
        textSize = 15f
        isAllCaps = false
        setTextColor(Color.WHITE)
        background = GradientDrawable().apply {
            cornerRadius = dp(28).toFloat()
            setColor(Color.parseColor(color))
        }
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(10) }
    }

    private fun vibrate() {
        try {
            val v = getSystemService(Vibrator::class.java)
            v?.vibrate(VibrationEffect.createOneShot(180, VibrationEffect.DEFAULT_AMPLITUDE))
        } catch (_: Exception) {
        }
    }
}
