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

    # --- Email / SMTP (لإرسال OTP واسترجاع كلمة المرور - FR-UM-018) ---
      SMTP_HOST: str = ""
      SMTP_USER: str = ""
      SMTP_PASSWORD: str = ""

    # --- الذكاء الاصطناعي (مراحل لاحقة) ---
      CLAUDE_API_KEY: str = ""

    # --- Supabase Storage (وحدة إدارة الوثائق) ---
      SUPABASE_URL: str = ""
      SUPABASE_SERVICE_ROLE_KEY: str = ""
      SUPABASE_STORAGE_BUCKET: str = "documents"
      MAX_DOCUMENT_UPLOAD_MB: int = 25

    # --- عام ---
      ENVIRONMENT: str = "development"


settings = Settings()
