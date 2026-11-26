# طريقة تطبيق تحديث تتبع الموقع على نسخة ECHOES الحالية

## التحديث الآمن على المجلد الحالي

1. أوقفي ECHOES من نافذة PowerShell بالضغط على `Ctrl+C`.
2. خذي نسخة احتياطية من قاعدة البيانات قبل أي نسخ:

   ```powershell
   Copy-Item .\echeos.db ".\echeos.db.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
   ```

3. افتحي ملف `ECHOES_Laptop_PublicLink_v8_LiveTracking_Patch.zip`.
4. استخرجي محتوياته فوق مجلد المشروع الحالي `ECHOES_Laptop_PublicLink_v8` مع السماح باستبدال الملفات عند الطلب.
5. لن يستبدل هذا التحديث `echeos.db` أو ملفات إعدادات القنوات؛ التعديل البرمجي الفعلي محصور في `app/safety.py` و`app/templates/live.html`، مع إضافة اختبارات وتقارير.
6. من PowerShell داخل مجلد المشروع شغّلي:

   ```powershell
   python -m pip install -r requirements-dev.txt
   python -m pytest -q
   python run.py
   ```

7. لاختبار الرابط العام، أوقفي التشغيل المحلي ثم شغّلي `run_public_windows.bat` بعد التأكد من إعداد Cloudflare Tunnel. استخدمي ملفا تجريبيا وموقعا وهميا، ولا تشاركي رابط الموقع إلا مع مقدم رعاية مخوّل.

## تنبيه

الرابط العام يتيح لمن يمتلكه مشاهدة الموقع حتى انتهاء صلاحيته أو إلغائه. لا تستخدمي بيانات مريض حقيقية في العرض العام، ولا ترفعي قاعدة البيانات أو مفاتيح Telegram/WhatsApp إلى مستودع عام.
