"""
الهدف:
التخاطب مع Supabase Storage (تخزين الملف الفعلي لوحدة "إدارة الوثائق")
عبر REST API مباشرة بواسطة httpx — بدون إضافة حزمة supabase-py كـ
Dependency جديدة، لأن كل ما نحتاجه هو ثلاث عمليات بسيطة (رفع/تحميل/حذف
كائن واحد داخل Bucket واحد)، و httpx موجودة أصلًا بمشروعنا.

المسؤولية:
- upload_object / download_object / delete_object: عمليات الملف الفعلي.
- كل الاستدعاءات تستخدم SUPABASE_SERVICE_ROLE_KEY (يتجاوز RLS) — ولا
  يصل هذا المفتاح للـ Frontend أبدًا؛ العميل يتعامل فقط مع الـ Backend
    (قرار عمل موثّق: رفع/تحميل الملف يمر بالكامل عبر الـ Backend، وليس
      عبر روابط Supabase موقّعة تُعطى مباشرة للعميل، حتى يبقى فحص صلاحيات
        الرؤية المركّبة documents.* بمكان واحد قابل للتدقيق).

        ملاحظات أمنية:
        - لا نثق بامتداد اسم الملف وحده لتحديد Content-Type عند التحميل — نخزّن
          mime_type بجدول documents وقت الرفع ونرجعه كما هو.
          - StorageError تُستخدم كـ Exception عام تلتقطه طبقة API وتحوّله لاستجابة
            HTTP مناسبة (502 عادة — خطأ بخدمة خارجية) بدل تسريب تفاصيل httpx.
            """

import httpx

from app.core.config import settings


class StorageError(Exception):
      """خطأ عام أثناء التخاطب مع Supabase Storage (رفع/تحميل/حذف فشل)."""


class StorageNotConfiguredError(StorageError):
      """SUPABASE_URL أو SUPABASE_SERVICE_ROLE_KEY غير مُعبّأين في البيئة الحالية."""


def _require_config() -> tuple[str, str, str]:
      if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
                raise StorageNotConfiguredError(
                              "إعدادات Supabase Storage غير مكتملة (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)"
                )
            return settings.SUPABASE_URL.rstrip("/"), settings.SUPABASE_SERVICE_ROLE_KEY, settings.SUPABASE_STORAGE_BUCKET


def _headers(service_key: str, *, content_type: str | None = None) -> dict[str, str]:
      headers = {
          "Authorization": f"Bearer {service_key}",
          "apikey": service_key,
}
    if content_type is not None:
              headers["Content-Type"] = content_type
          return headers


async def upload_object(storage_path: str, content: bytes, *, content_type: str) -> None:
      """رفع ملف جديد. upsert=false عمدًا — storage_path يحمل document_id فريدًا أصلًا،
          فأي تعارض يعني خطأ منطقي يجب أن يظهر بدل الكتابة فوق ملف موجود بصمت."""
    base_url, service_key, bucket = _require_config()
    url = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
              try:
                            response = await client.post(
                                              url, content=content, headers=_headers(service_key, content_type=content_type)
                            )
except httpx.HTTPError as exc:
            raise StorageError(f"تعذّر الاتصال بخدمة تخزين الملفات: {exc}") from exc
    if response.status_code >= 400:
              raise StorageError(f"فشل رفع الملف ({response.status_code}): {response.text}")


async def download_object(storage_path: str) -> bytes:
      base_url, service_key, bucket = _require_config()
    url = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
              try:
                            response = await client.get(url, headers=_headers(service_key))
except httpx.HTTPError as exc:
            raise StorageError(f"تعذّر الاتصال بخدمة تخزين الملفات: {exc}") from exc
    if response.status_code >= 400:
              raise StorageError(f"فشل تحميل الملف ({response.status_code}): {response.text}")
          return response.content


async def delete_object(storage_path: str) -> None:
      base_url, service_key, bucket = _require_config()
    url = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
              try:
                            response = await client.delete(url, headers=_headers(service_key))
except httpx.HTTPError as exc:
            raise StorageError(f"تعذّر الاتصال بخدمة تخزين الملفات: {exc}") from exc
    if response.status_code >= 400 and response.status_code != 404:
              raise StorageError(f"فشل حذف الملف ({response.status_code}): {response.text}")
      
