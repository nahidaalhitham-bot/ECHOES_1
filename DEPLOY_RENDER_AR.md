# نشر ECHOES على GitHub + Render (رابطين ثابتين)

النتيجة:
- رابط المسؤول:  https://echoes-XXXX.onrender.com          (لوحة التحكم)
- رابط المريض:   https://echoes-patient-XXXX.onrender.com   (شاشة المريض فقط)

## 1) GitHub
1. github.com ← Sign up (أو Sign in).
2. زر + أعلى اليمين ← New repository ← الاسم: echoes ← اختاري **Private** ← Create repository.
3. اضغطي «uploading an existing file».
4. افتحي مجلد ECHOES_GitHub (بعد فكّه مرة واحدة)، حدّدي **كل ما بداخله** واسحبيه إلى الصفحة ← Commit changes.

## 2) Render
1. render.com ← Get Started ← سجّلي بحساب GitHub.
2. New ← **Blueprint** ← اختاري مستودع echoes ← Connect.
3. يطلب Render ثلاث قيم:
   - ECHOES_OWNER_EMAIL: بريد المسؤول للدخول
   - ECHOES_OWNER_PASSWORD: كلمة مرور قوية (8 أحرف على الأقل)
   - TELEGRAM_BOT_TOKEN: رمز البوت من @BotFather
4. Apply ← انتظري حتى تصبح الخدمتان Live (5–10 دقائق أول مرة).

## 3) الاستخدام
- خدمة **echoes** ← رابطها أعلى الصفحة = رابط المسؤول. سجّلي الدخول بالبريد وكلمة المرور.
- الإعدادات ← «ربط تيليجرام بضغطة» ← Start.
- «حالة الجهاز» ← كرت «📲 تطبيق المريض» ← رابط/QR المريض (على خدمة echoes-patient).

## مهم
- الخطة المجانية: الخادم ينام بعد 15 دقيقة بلا استخدام (أول فتح يأخذ ~دقيقة)، والبيانات تُمسح عند إعادة تشغيله.
  للحفظ الدائم وتنبيهات فورية: غيّري خدمة echoes إلى خطة مدفوعة وأضيفي Disk مسار /var/data، ثم متغير ECHEOS_DB=/var/data/echoes.db.
- لا ترفعي ملف telegram_token.txt أو أي ملف .db إلى GitHub.
