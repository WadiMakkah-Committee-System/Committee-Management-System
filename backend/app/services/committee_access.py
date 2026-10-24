"""
تحقق الصلاحية المشترك لكل الوحدات المرتبطة بلجنة (الاجتماعات، القرارات،
المهام، ...) — إعادة هيكلة 2026-10-24.

النمط الهجين نفسه المطبَّق بكل وحدة سابقًا (كان منسوخًا حرفيًا بكل ملف
خدمة): الوصول = صلاحية System Role (own/department/all من دور المستخدم
العام) **أو** صلاحية Committee Role (رئيس/عضو) من عضوية المستخدم بهذه
اللجنة تحديدًا، تُقرأ حيًا من role_permissions. لا شيء ثابت بالكود.

الجديد هنا: CommitteeAccess يجلب أكواد أدوار اللجان للمستخدم **مرة واحدة
لكل طلب** (استعلام واحد لكل عضوياته)، بدل استعلام مستقل لكل (عنصر × كود).
قوائم مثل القرارات كانت تفحص صلاحيتين لكل قرار = استعلامان لكل قرار
(N+1)، وكل استعلام ≈ 355ms على الإنتاج.

متطلبات التحميل: الفحص لا يقرأ من اللجنة إلا committee_id وchair.dep_id
(لنطاق "department")، فيكفي تحميل اللجنة + رئيسها.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.committee import Committee, committee_members
from app.models.role import Permission, RolePermission
from app.models.user import User


def system_scope_allows(actor: User, committee: Committee, code: str) -> bool:
    scope = actor.scope_for(code)
    if scope == "all":
        return True
    if scope == "department":
        committee_dep_id = committee.chair.dep_id if committee.chair else None
        return actor.dep_id is not None and actor.dep_id == committee_dep_id
    return False


async def committee_role_codes_by_committee(
    db: AsyncSession, actor: User
) -> dict[uuid.UUID, set[str]]:
    """{committee_id: أكواد دور المستخدم بتلك اللجنة} لكل لجنة هو عضو/رئيس
    فيها — استعلام واحد. نفس مصدر committee_service.
    get_committee_role_permission_codes بالضبط (committee_members →
    committee_role → role_permissions → permissions)، لكل اللجان دفعة واحدة."""
    result = await db.execute(
        select(committee_members.c.committee_id, Permission.code)
        .select_from(committee_members)
        .join(RolePermission, RolePermission.role_id == committee_members.c.committee_role_id)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(committee_members.c.user_id == actor.user_id)
    )
    codes: dict[uuid.UUID, set[str]] = {}
    for committee_id, code in result.all():
        codes.setdefault(committee_id, set()).add(code)
    return codes


class CommitteeAccess:
    """
    فاحص صلاحيات لطلب واحد (لمستخدم واحد). أكواد أدوار اللجان تُجلب
    كسولًا عند أول حاجة فعلية (لو نطاق الـSystem Role كفى، لا استعلام
    إطلاقًا)، ثم تُعاد من الذاكرة لكل لجنة/كود بعدها.

    لا يُعاد استخدامه بين الطلبات: الصلاحيات تُقرأ حيّة بكل طلب (تعديل
    صلاحيات دور من شاشة "الأدوار والصلاحيات" ينعكس فورًا بالطلب التالي).
    """

    def __init__(self, db: AsyncSession, actor: User) -> None:
        self._db = db
        self._actor = actor
        self._codes: dict[uuid.UUID, set[str]] | None = None

    @property
    def actor(self) -> User:
        return self._actor

    @property
    def actor_id(self) -> uuid.UUID:
        return self._actor.user_id

    async def _committee_codes(self, committee_id: uuid.UUID) -> set[str]:
        if self._codes is None:
            self._codes = await committee_role_codes_by_committee(self._db, self._actor)
        return self._codes.get(committee_id, set())

    async def has(self, committee: Committee, code: str) -> bool:
        if system_scope_allows(self._actor, committee, code):
            return True
        return code in await self._committee_codes(committee.committee_id)

    async def committee_ids_with_code(self, code: str) -> set[uuid.UUID]:
        """اللجان التي يملك فيها المستخدم code عبر دور اللجنة (للقوائم)."""
        if self._codes is None:
            self._codes = await committee_role_codes_by_committee(self._db, self._actor)
        return {cid for cid, codes in self._codes.items() if code in codes}
