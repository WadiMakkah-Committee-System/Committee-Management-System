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

    # --- الذكاء الاصطناعي (مراحل لاحقة) ---
      CLAUDE_API_KEY: str = ""

    # --- Supabase Storage (وحدة إدارة الوثائق) ---
      SUPABASE_URL: str = ""
      SUPABASE_SERVICE_ROLE_KEY: str = ""
      SUPABASE_STORAGE_BUCKET: str = "documents"
      MAX_DOCUMENT_UPLOAD_MB: int = 25

    # --- Agora (اجتماعات الفيديو عن بعد — meetings.join) ---
    # AGORA_APP_ID/AGORA_APP_CERTIFICATE اختياريان بقيمة افتراضية فارغة (نفس
    # نمط SUPABASE_*/SMTP_* أعلاه) حتى لا تنكسر بيئات .env القديمة. يُستخدَمان
    # من app.core.agora_client فقط لإصدار Token قصير العمر (Server-Side)، ولا
    # يصلان للـFrontend أبدًا (نفس مبدأ SUPABASE_SERVICE_ROLE_KEY أعلاه) —
    # العميل يستلم Token جاهز فقط عبر POST /meetings/{id}/join.
      AGORA_APP_ID: str = ""
      AGORA_APP_CERTIFICATE: str = ""
      AGORA_TOKEN_TTL_SECONDS: int = 3600

    # --- Google Gemini (تحويل تسجيل الاجتماع الصوتي إلى مسودة —
    # meetings.record_audio/draft.summarize، migration 0025) ---
    # GEMINI_API_KEY اختياري بقيمة افتراضية فارغة (نفس نمط CLAUDE_API_KEY/
    # AGORA_*/SUPABASE_* أعلاه) — لا يصل للـFrontend أبدًا، يُستخدَم من
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

      @property
      def cors_origins_list(self) -> list[str]:
          return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
