"""
الهدف:
"توقيعي" — التوقيع المحفوظ لكل مستخدم في المنصة (migration 0049)، يُستخدم
للتوقيع على المحاضر بدل رسمه كل مرة (قرار صاحب المشروع 2026-11-15).

المسؤولية:
- قراءة/حفظ/حذف توقيع المستخدم الحالي فقط (لا أحد يقرأ توقيع غيره).
- التحقق من صورة التوقيع (PNG data URL حقيقي وبحجم معقول).
- تسجيل التدقيق (audit_logs) لكل حفظ/حذف — تغيير على بيانات حساب.

قواعد العمل:
- لكل مستخدم توقيع محفوظ واحد، يقدر يستبدله أو يحذفه.
- حسابات الضيوف (users.is_guest) ممنوعة — الضيوف لا يوقّعون على المحاضر.
- التوقيع بالمحفوظ في المحضر يقرأ الصورة من هنا بالخادم (meeting_minutes_service).
"""

import base64
import binascii
import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_saved_signature import UserSavedSignature
from app.services import audit_service

_PREFIX = "data:image/png;base64,"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_CHARS = 300_000


class SignatureValidationError(ValueError):
    """صورة توقيع غير صالحة — رسالة عربية (400)."""


class SignatureForbiddenError(Exception):
    """العملية غير مسموحة لهذا الحساب (مثل حساب ضيف) — 403."""


def validate_signature_image(value: str) -> str:
    """
    الهدف: التحقق من صورة توقيع قبل حفظها.

    القواعد: تبدأ بـdata:image/png;base64، طولها بين 30 و300 ألف حرف (نفس
    قيود الجدول)، وbase64 صالح يبدأ ببصمة PNG.
    المخرجات: نفس القيمة. الأخطاء: SignatureValidationError.
    """
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        raise SignatureValidationError("صيغة التوقيع غير صالحة — المطلوب صورة PNG")
    if not (30 <= len(value) <= MAX_IMAGE_CHARS):
        raise SignatureValidationError("حجم صورة التوقيع غير مقبول")
    try:
        raw = base64.b64decode(value[len(_PREFIX):], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureValidationError("صورة التوقيع تالفة") from exc
    if not raw.startswith(_PNG_MAGIC):
        raise SignatureValidationError("صورة التوقيع ليست PNG")
    return value


def _require_not_guest(actor: User) -> None:
    """الضيوف ما لهم توقيع محفوظ (ولا يوقّعون على المحاضر)."""
    if actor.is_guest:
        raise SignatureForbiddenError("حسابات الضيوف لا تملك توقيعًا محفوظًا")


async def get_saved_signature_image(db: AsyncSession, *, user_id: uuid.UUID) -> str | None:
    """
    الهدف: صورة التوقيع المحفوظ لمستخدم (للاستخدام الداخلي بالخادم فقط —
    التوقيع على المحضر بالمحفوظ). المخرجات: الصورة أو None.
    """
    result = await db.execute(
        select(UserSavedSignature.signature_image).where(UserSavedSignature.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_my_signature(db: AsyncSession, *, actor: User) -> UserSavedSignature | None:
    """
    الهدف: توقيع المستخدم الحالي المحفوظ (لصفحة "توقيعي" وخانة التوقيع).
    الصلاحيات: المستخدم نفسه فقط (المعرّف من التوكن). الأخطاء: SignatureForbiddenError للضيف.
    """
    _require_not_guest(actor)
    result = await db.execute(select(UserSavedSignature).where(UserSavedSignature.user_id == actor.user_id))
    return result.scalar_one_or_none()


async def upsert_saved_signature(db: AsyncSession, *, actor: User, signature_image: str) -> None:
    """
    الهدف: حفظ/استبدال توقيع المستخدم الحالي — بدون commit (يُستدعى أيضًا ضمن
    معاملة التوقيع على المحضر مع خيار "احفظه للمرات الجاية").

    التأثيرات الجانبية: INSERT ... ON CONFLICT DO UPDATE على user_saved_signatures
    + سجل تدقيق (update/user، event=saved_signature_set).
    الأخطاء: SignatureValidationError، SignatureForbiddenError.
    """
    _require_not_guest(actor)
    image = validate_signature_image(signature_image)
    statement = insert(UserSavedSignature).values(user_id=actor.user_id, signature_image=image)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[UserSavedSignature.user_id], set_={"signature_image": statement.excluded.signature_image}
        )
    )
    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="update",
        target_type="user",
        target_id=actor.user_id,
        metadata={"event": "saved_signature_set"},
    )


async def save_my_signature(db: AsyncSession, *, actor: User, signature_image: str) -> UserSavedSignature:
    """
    الهدف: حفظ توقيع المستخدم الحالي من صفحة "توقيعي" (مع commit).
    المخرجات: الصف المحفوظ. الأخطاء: نفس upsert_saved_signature.
    """
    await upsert_saved_signature(db, actor=actor, signature_image=signature_image)
    await db.commit()
    saved = await get_my_signature(db, actor=actor)
    assert saved is not None
    return saved


async def delete_my_signature(db: AsyncSession, *, actor: User) -> bool:
    """
    الهدف: حذف توقيع المستخدم الحالي المحفوظ.
    المخرجات: True لو كان موجودًا وانحذف، False لو ما كان عنده توقيع.
    التأثيرات الجانبية: DELETE + سجل تدقيق (delete/user، event=saved_signature_deleted).
    التوقيعات اللي سبق ووقّعها على محاضر لا تتأثر (منسوخة في المحضر نفسه).
    """
    _require_not_guest(actor)
    result = await db.execute(
        delete(UserSavedSignature).where(UserSavedSignature.user_id == actor.user_id)
    )
    if not result.rowcount:
        return False
    await audit_service.log_action(
        db,
        actor_user_id=actor.user_id,
        action_type="delete",
        target_type="user",
        target_id=actor.user_id,
        metadata={"event": "saved_signature_deleted"},
    )
    await db.commit()
    return True
