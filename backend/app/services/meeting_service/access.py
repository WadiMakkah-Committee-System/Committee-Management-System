"""
تحقق الصلاحية (Authorization) لوحدة الاجتماعات.

الوصول = صلاحية على مستوى System Role (own/department/all، من دور المستخدم
العام) **أو** صلاحية على مستوى Committee Role (رئيس/عضو — من دور عضويته
بهذه اللجنة تحديدًا، تُقرأ حيًا من role_permissions عبر
committee_service.get_committee_role_permission_codes). لا شيء مكتوب بثبات
بالكود — يُضبط من شاشة "الأدوار والصلاحيات".

متطلبات التحميل: الدوال هنا لا تقرأ من كائن اللجنة إلا committee_id و
committee.chair.dep_id (لنطاق "department") — فأي استعلام يحمّل الاجتماع
لغرض فحص الصلاحية فقط يكفيه تحميل اللجنة + رئيسها (راجعي loading.py).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.committee import Committee, committee_members
from app.models.role import Permission, RolePermission
from app.models.user import User
from app.services import committee_service
from app.services.meeting_service.errors import MeetingForbiddenError


def _system_scope_allows(actor: User, committee: Committee, code: str) -> bool:
    scope = actor.scope_for(code)
    if scope == "all":
        return True
    if scope == "department":
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        return actor.dep_id is not None and actor.dep_id == committee_dep_id
    return False


async def _committee_role_codes(db: AsyncSession, actor: User, committee: Committee) -> set[str]:
    return await committee_service.get_committee_role_permission_codes(
        db, user_id=actor.user_id, committee_id=committee.committee_id
    )


async def _has_access(db: AsyncSession, actor: User, committee: Committee, code: str) -> bool:
    if _system_scope_allows(actor, committee, code):
        return True
    return code in await _committee_role_codes(db, actor, committee)


async def _require_access(
    db: AsyncSession, actor: User, committee: Committee, code: str, message: str
) -> None:
    if not await _has_access(db, actor, committee, code):
        raise MeetingForbiddenError(message)


async def _access_flags(
    db: AsyncSession, actor: User, committee: Committee, codes: list[str]
) -> dict[str, bool]:
    """
    نتيجة فحص عدّة أكواد دفعة واحدة: {code: bool}. نطاق الـSystem Role
    يُفحص بالذاكرة لكل كود، وأكواد دور اللجنة تُجلب **مرة واحدة فقط** عند
    الحاجة (كانت _has_any_access/get_draft تستدعي _has_access لكل كود على
    حدة — استعلام دور لجنة مستقل لكل كود لم تُمنح صلاحيته نظاميًا).
    """
    flags = {code: _system_scope_allows(actor, committee, code) for code in codes}
    if not all(flags.values()):
        committee_codes = await _committee_role_codes(db, actor, committee)
        for code in codes:
            flags[code] = flags[code] or code in committee_codes
    return flags


async def _has_any_access(
    db: AsyncSession, actor: User, committee: Committee, codes: list[str]
) -> bool:
    """يكفي امتلاك واحد من عدّة أكواد بديلة (OR) — تُستخدم لصلاحيات العرض
    الجزئي (meetings.transcript.view/meetings.summary.view/ai_items.view)
    التي تُغني عن meetings.draft.view الكاملة لكل حقل على حدة (تحديث
    2026-09-16، راجعي رأس db/migrations/0035 للخلفية الكاملة)، وأيضًا
    لتوسعة 2026-09-21 على get_latest_recording."""
    return any((await _access_flags(db, actor, committee, codes)).values())


async def _require_any_access(
    db: AsyncSession, actor: User, committee: Committee, codes: list[str], message: str
) -> None:
    if not await _has_any_access(db, actor, committee, codes):
        raise MeetingForbiddenError(message)


async def _committee_ids_with_committee_role_code(
    db: AsyncSession, actor: User, code: str
) -> set[uuid.UUID]:
    stmt = (
        select(committee_members.c.committee_id)
        .select_from(committee_members)
        .join(RolePermission, RolePermission.role_id == committee_members.c.committee_role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(committee_members.c.user_id == actor.user_id, Permission.code == code)
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())
