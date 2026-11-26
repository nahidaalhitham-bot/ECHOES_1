/* ECHOES — link the patient's own screen as his tracker.
 * Not linked → this screen shows a QR; the caregiver scans it from
 *   «حالة الجهاز» → «📷 مسح QR جوال المريض».
 * Linked → this screen shares its location while it is open.
 * Same storage key as /tracker, so both pages share one link. */
(function () {
  const KEY = 'echoes_device_token', HIDE = 'echoes_pair_hidden';
  const box = document.getElementById('trackerPair');
  if (!box) return;
  const ls = {
    get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} },
    del: k => { try { localStorage.removeItem(k); } catch (e) {} },
  };
  let timer = null, watchId = null, battery = null;
  if (navigator.getBattery) navigator.getBattery().then(b => {
    battery = Math.round(b.level * 100);
    b.onlevelchange = () => { battery = Math.round(b.level * 100); };
  }).catch(() => {});

  function card(html) { box.innerHTML = html; box.hidden = false; }

  async function showQR() {
    clearInterval(timer);
    if (ls.get(HIDE) === '1') {
      card('<button class="ghost tp-small" id="tpShow">📱 ربط هذا الجهاز كتراكر للمريض</button>');
      document.getElementById('tpShow').onclick = () => { ls.del(HIDE); showQR(); };
      return;
    }
    card('<p class="tp-note">جارٍ تجهيز رمز الربط…</p>');
    let d;
    try { d = await fetch('/api/tracker/pair/new', { method: 'POST' }).then(r => r.json()); }
    catch (e) { card('<p class="tp-note">تعذّر الاتصال بالخادم — حدّث الصفحة.</p>'); return; }
    card(`<div class="tp-card">
        <div class="tp-title">📱 اربط هذا الجهاز كتراكر للمريض</div>
        <div class="tp-note">من لوحة التحكم ← «حالة الجهاز» ← <b>«📷 مسح QR جوال المريض»</b> ثم وجّه الكاميرا لهذا الرمز.</div>
        <div class="tp-qr">${d.qr_svg || ''}</div>
        <div class="tp-note">أو اكتب الرمز في لوحة التحكم:</div>
        <div class="tp-code">${d.code.slice(0, 4)}-${d.code.slice(4)}</div>
        <div class="tp-note" id="tpMsg">بانتظار المسح… (صالح 15 دقيقة)</div>
        <button class="ghost tp-small" id="tpHide">ليس جهاز المريض — إخفاء</button>
      </div>`);
    const sv = box.querySelector('.tp-qr svg');
    if (sv) { sv.style.width = 'min(70vw,280px)'; sv.style.height = 'auto'; }
    document.getElementById('tpHide').onclick = () => { ls.set(HIDE, '1'); showQR(); };
    const t0 = Date.now();
    timer = setInterval(async () => {
      if (Date.now() - t0 > (d.expires_in - 20) * 1000) return showQR();
      try {
        const st = await fetch('/api/tracker/pair/' + d.code).then(r => r.json());
        if (st.status === 'linked' && st.token) {
          clearInterval(timer);
          ls.set(KEY, st.token);
          startTracking(true);
        } else if (st.status === 'expired') showQR();
      } catch (e) {}
    }, 2000);
  }

  function status(text, ok) {
    card(`<div class="tp-pill ${ok ? 'on' : 'off'}">📍 ${text}</div>`);
  }

  function startTracking(justLinked) {
    const token = ls.get(KEY);
    if (!token) return showQR();
    if (!navigator.geolocation) return status('هذا الجهاز لا يدعم تحديد الموقع', false);
    status(justLinked ? '✔ تم الربط — اسمح بالموقع' : 'جارٍ تشغيل مشاركة الموقع…', true);
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    watchId = navigator.geolocation.watchPosition(async pos => {
      const c = pos.coords;
      try {
        const r = await fetch('/api/device/report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
          body: JSON.stringify({ lat: c.latitude, lon: c.longitude, accuracy_m: c.accuracy, battery }),
        });
        if (r.status === 401) {          // link cancelled from the dashboard
          navigator.geolocation.clearWatch(watchId); watchId = null;
          ls.del(KEY); return showQR();
        }
        status(r.ok ? 'هذا الجهاز يشارك موقع المريض' : 'تعذّر إرسال الموقع (' + r.status + ')', r.ok);
      } catch (e) { status('لا يوجد اتصال — سيُعاد الإرسال تلقائيًا', false); }
    }, e => {
      status(e.code === 1 ? 'إذن الموقع مرفوض — اسمح بالموقع من إعدادات المتصفح'
                          : 'لا توجد إشارة موقع حاليًا', false);
    }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
  }

  // Shown inside the app's patient screen (logged in or not). On a device that
  // is not the patient's, «إخفاء» collapses it to one small button.
  if (ls.get(KEY)) startTracking(false);
  else showQR();
})();
