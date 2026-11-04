# مزوّد الاجتماعات عن بعد: Agora ↔ Microsoft Teams

**القرار الحالي (لاما 2026-11-04):** الاجتماعات عن بعد بـ **Agora** داخل المنصة، والدخول للمنصة باسم المستخدم وكلمة المرور.
تكامل Microsoft Teams والدخول بحساب Microsoft **محفوظين بالكود ومعطّلين** بإعدادين — الرجوع لهم تغيير إعدادات فقط.

## نقاط الحفظ

| الشي | وين |
| --- | --- |
| آخر نسخة كانت تعتمد Teams بالكامل | الفرع `archive/teams-integration` |
| كود Teams (إنشاء الاجتماعات، الانضمام المدمج ACS، التسجيلات، التفريغ) | باقي بـ`main`، يشتغل لو `MEETING_PROVIDER=teams` |
| الدخول بحساب Microsoft | باقي بـ`main`، يشتغل لو `MICROSOFT_LOGIN_ENABLED=true` |
| أعمدة `teams_*` بجدول `meetings` و`users.microsoft_object_id` | ما انحذفت (0041، 0042) |

## الإعدادات (Render → Environment)

| الإعداد | Agora (الحالي) | Teams |
| --- | --- | --- |
| `MEETING_PROVIDER` | `agora` | `teams` |
| `MICROSOFT_LOGIN_ENABLED` | `false` | `true` |
| `AGORA_APP_ID` / `AGORA_APP_CERTIFICATE` | مطلوبة (سر — Render فقط) | اختيارية |
| `TEAMS_TENANT_ID` / `TEAMS_CLIENT_ID` / `TEAMS_CLIENT_SECRET` / `TEAMS_ORGANIZER_EMAIL` | تُترك (لفتح اجتماعات Teams القديمة وتسجيلاتها) | مطلوبة |
| `ACS_CONNECTION_STRING` | تُترك (لاجتماعات Teams القديمة) | مطلوبة |
| `MICROSOFT_LOGIN_DOMAINS` | لا تأثير | `wadimakkah.sa` |

`MEETING_PROVIDER` يتحكم **بالاجتماعات الجديدة فقط**: أي اجتماع انربط بـTeams قبل يبقى يفتح بـTeams، والاجتماعات اللي انسوت بـAgora تبقى Agora.

## الرجوع لـTeams — الخطوات

1. Render: `MEETING_PROVIDER=teams` و`MICROSOFT_LOGIN_ENABLED=true` (والتأكد من مفاتيح `TEAMS_*` و`ACS_CONNECTION_STRING`).
2. المتطلبات خارج الكود (موثّقة برأس `backend/app/core/teams_client.py`):
   - صلاحيات تطبيق Entra "Committee Management System" + Admin consent.
   - Application Access Policy لحساب المنظِّم.
   - **تفعيل قراءة التفريغ بـTeams Admin Center** (كان مقفل وقت القرار):
     Meetings ← Meeting settings ← Transcript API access ← Microsoft Graph access = On.
3. إعادة تشغيل الخدمة بـRender. الواجهة ما تحتاج نشر — تقرأ الإعدادات من الباك-إند.

## تنبيه قبل إيقاف الدخول بـMicrosoft

المستخدم اللي ربط حسابه بـMicrosoft أول مرة، المنصة **لغت كلمة المرور المؤقتة حقته** (`authenticate_microsoft`).
قبل `MICROSOFT_LOGIN_ENABLED=false` لازم يعاد تعيين كلمة المرور لهؤلاء من إدارة المستخدمين، وإلا ما يقدرون يدخلون.
للمعرفة: `select username, email from users where microsoft_object_id is not null and deleted_at is null;`
