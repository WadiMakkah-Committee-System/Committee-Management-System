r"""
الهدف:
سكربت لمرة واحدة (one-off) لنقل الملفات المرفوعة سابقاً من Supabase Storage
إلى قرص خادم الإنتاج (بارع كلاود)، قبل تفعيل STORAGE_BACKEND=local.

المسؤولية:
- يقرأ من قاعدة البيانات كل مسارات الملفات (storage_path) في جدولي
  documents وmeeting_recordings، بما فيها الملفات المحذوفة حذفاً منطقياً،
  حتى لا يُفقد أي ملف قد يُستعاد لاحقاً.
- يحمّل كل ملف من Supabase ويحفظه على القرص في STORAGE_LOCAL_PATH.
- يتخطى الملف الموجود مسبقاً على القرص، فيمكن إعادة تشغيل السكربت بأمان.

المدخلات (من ملف .env على الخادم):
- DATABASE_URL: قاعدة البيانات على الخادم بعد نقل البيانات إليها.
- SUPABASE_URL وSUPABASE_SERVICE_ROLE_KEY وSUPABASE_STORAGE_BUCKET: مصدر الملفات.
- STORAGE_LOCAL_PATH: مجلد الحفظ على القرص.

التأثيرات الجانبية:
- يكتب ملفات على قرص الخادم فقط، ولا يعدّل قاعدة البيانات ولا يحذف أي شيء
  من Supabase.

الأخطاء المحتملة:
- فشل ملف واحد لا يوقف الباقي، ويُطبع ملخص بعدد الملفات الفاشلة في النهاية.

طريقة التشغيل (على الخادم، من مجلد المشروع):
    docker compose -f docker-compose.prod.yml exec backend python -m scripts.migrate_storage_to_local
"""

import asyncio
import logging

from sqlalchemy import select

from app.core import storage_client
from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.models.meeting_draft import MeetingRecording

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate_storage_to_local")


async def _collect_storage_paths() -> list[str]:
    """
    الهدف: جمع كل مسارات الملفات المسجلة في قاعدة البيانات.

    المخرجات: قائمة مسارات فريدة ومرتبة.
    """
    async with AsyncSessionLocal() as db:
        documents = (await db.execute(select(Document.storage_path))).scalars().all()
        recordings = (await db.execute(select(MeetingRecording.storage_path))).scalars().all()
    return sorted({path for path in [*documents, *recordings] if path})


async def main() -> None:
    """
    الهدف: نقل كل الملفات من Supabase Storage إلى قرص الخادم.

    التأثيرات الجانبية: يكتب الملفات على القرص ويطبع ملخص النتيجة.
    """
    paths = await _collect_storage_paths()
    logger.info("عدد الملفات المسجلة في قاعدة البيانات: %d", len(paths))

    copied = skipped = failed = 0
    for index, storage_path in enumerate(paths, start=1):
        try:
            target = storage_client._safe_local_path(storage_path)
            if target.exists():
                skipped += 1
                continue
            content = await storage_client._supabase_download_object(storage_path)
            await asyncio.to_thread(storage_client._local_write_new, target, content)
            copied += 1
            logger.info("(%d/%d) تم نقل: %s", index, len(paths), storage_path)
        except Exception:  # noqa: BLE001 — فشل ملف واحد لا يوقف نقل الباقي
            failed += 1
            logger.exception("(%d/%d) فشل نقل: %s", index, len(paths), storage_path)

    logger.info("انتهى النقل — تم نقل: %d، موجود مسبقاً: %d، فشل: %d", copied, skipped, failed)
    if failed:
        logger.warning("لا تفعّلي STORAGE_BACKEND=local قبل معالجة الملفات الفاشلة.")


if __name__ == "__main__":
    asyncio.run(main())
