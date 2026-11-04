"""
الهدف:
تجميع كل إعدادات التطبيق (متغيرات البيئة) في مكان واحد مركزي، بدل ما تكون
متناثرة داخل الكود. يطبّق قاعدة "Environment Variables" و"عدم وضع Secrets
داخل الكود" المذكورة في CLAUDE.md.

المسؤولية:
قراءة متغيرات البيئة (من ملف .env أو من بيئة التشغيل الفعلية) والتحقق من
وجودها، مع توفير قيم افتراضية آمنة للإعدادات غير الحساسة فقط.

الاعتماديات:
pydantic-settings لقراءة والتحقق من متغيرات البيئة.

ملاحظات:
- DATABASE_URL و JWT_SECRET و REDIS_URL إلزامية ولا قيمة افتراضية لها عمدًا.
- ACCOUNT_LOCKOUT_MINUTES قابل للتعديل بدون تعديل الكود (قرار موثق في
  docs/database/erd-users-departments.md: 15 دقيقة افتراضيًا).
  - SUPABASE_* اختيارية بقيمة افتراضية فارغة (نفس نمط SMTP_*) حتى لا تنكسر
    بيئات .env القديمة التي أُنشئت قبل وحدة الوثائق. تُستخدم من
      app.core.storage_client لرفع/تحميل/حذف ملفات الوثائق عبر Supabase
        Storage REST API مباشرة (بدون حزمة supabase-py — httpx فقط، وهي
          موجودة أصلًا بالمشروع)، دائمًا عبر الـ Backend (قرار موثّق: لا روابط
            موقّعة تُعطى للعميل مباشرة، حفاظًا على مركزية فحص صلاحيات الرؤية
              المركّبة documents.* في مكان واحد).
              """

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
      model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database ---
      DATABASE_URL: str
    # مشغّل قاعدة البيانات (تحسين أداء 2026-10-28، راجعي app/db/session.py):
    # فارغ = اختيار تلقائي (psycopg، أو asyncpg على Windows بدون --reload).
    # "asyncpg" = الرجوع للمشغّل القديم فورًا بدون تعديل كود.
      DB_DRIVER: str = ""

    # --- Auth / JWT ---
      JWT_SECRET: str
      JWT_ALGORITHM: str = "HS256"
      ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
      REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Redis (تتبع الجلسات وإبطال التوكن) ---
      REDIS_URL: str

    # --- Idle session timeout (إنهاء الجلسة تلقائيًا بعد فترة خمول) ---
      SESSION_IDLE_TIMEOUT_MINUTES: int = 30

    # --- سياسة قفل الحساب (FR-UM-019) ---
      MAX_FAILED_LOGIN_ATTEMPTS: int = 5
      ACCOUNT_LOCKOUT_MINUTES: int = 15

    # --- نسيت كلمة المرور عبر OTP (FR-UM-018 — قرارات لاما 2026-10-31) ---
    # صلاحية الرمز، أقصى عدد محاولات خاطئة قبل إبطاله (نفس حد FR-UM-019)،
    # وأقل مدة بين طلبين لنفس البريد (منع إغراق البريد واستهلاك حصة المزوّد).
      PASSWORD_RESET_OTP_MINUTES: int = 15
      PASSWORD_RESET_MAX_ATTEMPTS: int = 5
      PASSWORD_RESET_RESEND_SECONDS: int = 60

    # --- Email / SMTP (لإرسال OTP واسترجاع كلمة المرور - FR-UM-018 -
    # ولإشعارات الاجتماعات إنشاء/تعديل/حذف - قرار لاما 2026-09-06) ---
      SMTP_HOST: str = ""
      SMTP_PORT: int = 587
      SMTP_USER: str = ""
      SMTP_PASSWORD: str = ""
      # اسم/عنوان المُرسِل الظاهر بالبريد — افتراضيًا نفس SMTP_USER لو تُرك فارغًا.
      SMTP_FROM_EMAIL: str = ""
      SMTP_FROM_NAME: str = "نظام إدارة اللجان"
      # True لـ Gmail/Outlook القياسي (STARTTLS على المنفذ 587).
      SMTP_USE_TLS: bool = True
      # مزوّد الإرسال (تحديث 2026-10-31 — Render free يحجب منافذ SMTP، راجعي
      # رأس core/email_client.py): "smtp" (الافتراضي، السلوك القديم) أو
      # "resend" أو "brevo" (عبر HTTP API). EMAIL_API_KEY مفتاح المزوّد المختار
      # فقط (غير مستخدم مع smtp)، والمُرسِل من SMTP_FROM_EMAIL/SMTP_FROM_NAME.
      EMAIL_PROVIDER: str = "smtp"
      EMAIL_API_KEY: str = ""

    # --- الذكاء الاصطناعي (مراحل لاحقة) ---
      CLAUDE_API_KEY: str = ""

    # --- Supabase Storage (وحدة إدارة الوثائق) ---
      SUPABASE_URL: str = ""
      SUPABASE_SERVICE_ROLE_KEY: str = ""
      SUPABASE_STORAGE_BUCKET: str = "documents"
      MAX_DOCUMENT_UPLOAD_MB: int = 25

    # --- مزوّد الاجتماعات عن بعد (قرار لاما 2026-11-04 — الرجوع لـAgora مع حفظ Teams) ---
    # MEETING_PROVIDER: "agora" (الافتراضي) أو "teams". يتحكم فقط بالاجتماعات
    # الجديدة: "teams" ⇒ يُنشأ لها اجتماع Teams (يتطلب TEAMS_* أدناه)، "agora" ⇒
    # غرفة Agora داخل المنصة. الاجتماعات القديمة المربوطة بـTeams تبقى تفتح بـTeams
    # بغض النظر عن هذا الإعداد. الرجوع لـTeams = تغيير هذا الإعداد بـRender فقط
    # (راجعي docs/meeting-provider-switch.md).
      MEETING_PROVIDER: str = "agora"

    # --- Agora (اجتماعات الفيديو/الصوت داخل المنصة) ---
    # AGORA_APP_ID/AGORA_APP_CERTIFICATE من Agora Console → Projects. الشهادة سر —
    # على الباك-إند فقط (app.core.agora_client يبني توكن قصير العمر)، ولا تصل
    # للواجهة أبدًا. فارغة ⇒ الانضمام لاجتماعات Agora معطّل (503 واضح).
      AGORA_APP_ID: str = ""
      AGORA_APP_CERTIFICATE: str = ""
      AGORA_TOKEN_TTL_SECONDS: int = 4 * 60 * 60

    # --- Microsoft Teams (الاجتماعات عن بعد — migration 0041، قرار لاما
    # 2026-11-02 بالانتقال من Agora إلى Teams) ---
    # بيانات تطبيق "Committee Management System" المسجّل بـEntra ID (Client
    # Credentials عبر app.core.teams_client) — لا تصل للـFrontend أبدًا.
    # اختيارية بقيمة فارغة (نفس نمط GEMINI_*/SUPABASE_*): لو أي منها فارغ يبقى
    # التكامل معطّلًا ويُنشأ الاجتماع عن بعد بلا رابط Teams (بيئات التطوير
    # فقط — Teams هو وسيلة الاجتماع عن بعد الوحيدة منذ إزالة Agora 2026-11-02).
    # TEAMS_ORGANIZER_EMAIL: الحساب الذي تُنشأ الاجتماعات باسمه — يجب أن
    # تشمله Application Access Policy بـTeams PowerShell. تغييره لاحقًا (مثلًا
    # لحساب مخصص meetings@...) لا يكسر الاجتماعات القديمة (meetings.teams_organizer_id).
      TEAMS_TENANT_ID: str = ""
      TEAMS_CLIENT_ID: str = ""
      TEAMS_CLIENT_SECRET: str = ""
      TEAMS_ORGANIZER_EMAIL: str = ""

    # --- الدخول بحساب Microsoft 365 (migration 0042، قرار لاما 2026-11-02) ---
    # يستخدم نفس تطبيق Entra أعلاه (TEAMS_TENANT_ID/TEAMS_CLIENT_ID) — مفعّل
    # تلقائيًا متى ما عُبّئا. MICROSOFT_LOGIN_DOMAINS: نطاقات بريد الشركة
    # مفصولة بفواصل (مثل "wadimakkah.sa") — من يكتب بريدًا منها بصفحة الدخول
    # يُحوَّل لنافذة Microsoft تلقائيًا بدل خانة كلمة المرور. ليست أسرارًا
    # (تُرجَع للواجهة عبر GET /auth/login-options).
      MICROSOFT_LOGIN_DOMAINS: str = ""
    # MICROSOFT_LOGIN_ENABLED (قرار لاما 2026-11-04): مفتاح إظهار/إخفاء الدخول
    # بـMicrosoft بصفحة الدخول. False (الافتراضي) ⇒ مخفي ومرفوض حتى لو مفاتيح
    # Entra موجودة — الكود محفوظ، والرجوع له = True بـRender.
      MICROSOFT_LOGIN_ENABLED: bool = False

    # --- Azure Communication Services (تجربة: فيديو اجتماع Teams داخل واجهة
    # المنصة نفسها — 2026-11-02، فرع poc/acs-teams-embed) ---
    # Connection string لمورد ACS (Azure Portal → Communication Services →
    # Keys). سر — على الباك-إند فقط؛ الواجهة تستلم توكن قصير العمر فقط.
    # فارغ ⇒ الانضمام المدمج معطّل، ويبقى زر "فتح في تيمز" فقط.
      ACS_CONNECTION_STRING: str = ""

    # --- Google Gemini (تحويل تسجيل الاجتماع الصوتي إلى مسودة —
    # meetings.record_audio/draft.summarize، migration 0025) ---
    # GEMINI_API_KEY اختياري بقيمة افتراضية فارغة (نفس نمط CLAUDE_API_KEY/
    # TEAMS_*/SUPABASE_* أعلاه) — لا يصل للـFrontend أبدًا، يُستخدَم من
    # app.core.gemini_client فقط. GEMINI_MODEL قابل للتغيير بدون تعديل
    # الكود (أسماء نماذج Gemini تتحدّث بمرور الوقت).
      GEMINI_API_KEY: str = ""
      GEMINI_MODEL: str = "gemini-3.6-flash"

    # --- عام ---
      ENVIRONMENT: str = "development"

    # --- CORS (تحديث 2026-09-12 — قرار لاما: نشر المنصة على
    # استضافة عامة): قائمة نطاقات الواجهة الأمامية المسموح لها بالاتصال
    # بالـAPI، مفصولة بفواصل بدون مسافات — إلزامية فعليًا بالإنتاج لأن
    # CORSMiddleware بـmain.py يمنع كل شي افتراضيًا لو ENVIRONMENT != development
    # (مثال: https://committee-app.vercel.app,https://custom-domain.com). ---
      CORS_ORIGINS: str = ""

    # --- رابط الواجهة الأمامية (رفع ملف المستخدمين 2026-11-01): يظهر كرابط
    # "الدخول إلى النظام" ببريد بيانات الدخول. اختياري — الفارغ يُخفي الرابط
    # (مثال: https://cms.wadimakkah.sa). ---
      FRONTEND_URL: str = ""

      @property
      def cors_origins_list(self) -> list[str]:
          return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
