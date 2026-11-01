"""
صلاحيات الرؤية المركّبة للوثائق (منفصلة عن RBAC العام) + أهداف النشر.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.committee import Committee, committee_members
from app.models.committee_request import CommitteeFormationRequest
from app.models.department import Department
from app.models.document import Document
from app.models.user import User
from app.services.document_service.loading import committees_query, departments_query, load_department


async def _user_committee_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    result = await db.execute(
        select(committee_members.c.committee_id).where(committee_members.c.user_id == user_id)
    )
    return {row[0] for row in result.all()}


async def _department_committee_ids(db: AsyncSession, dep_id: uuid.UUID) -> set[uuid.UUID]:
    """
    اللجان اللي "تتبع" إدارة معينة — تُعرَّف بإدارة مَن طلب تشكيلها
    (CommitteeFormationRequest.requested_by)، وليس بعمود مباشر على
    Committee (غير موجود بالنموذج أصلًا). قرار عمل موثّق مع لجينـ
    2026-09-09: الأدمن هو مَن يطلب تشكيل لجان إدارته (committees.request.create
    بنطاق all)، فهذا هو الرابط الطبيعي بين اللجنة وإدارتها — راجعي
    can_view_document أدناه لاستخدامها.
    """
    result = await db.execute(
        select(Committee.committee_id)
        .join(
            CommitteeFormationRequest,
            CommitteeFormationRequest.request_id == Committee.source_request_id,
        )
        .join(User, User.user_id == CommitteeFormationRequest.requested_by)
        .where(User.dep_id == dep_id, Committee.deleted_at.is_(None))
    )
    return {row[0] for row in result.all()}


class DocumentViewer:
    """
    ما يحتاجه فحص الرؤية عن المستخدم نفسه (لجانه، ولجان إدارته) — يُجلب
    كسولًا مرة واحدة لكل طلب ويُعاد استخدامه لكل وثيقة (إعادة هيكلة
    2026-10-24). كان يُستعلَم مرة أو مرتين **لكل وثيقة** مشتركة مع لجنة.
    """

    def __init__(self, db: AsyncSession, current_user: User) -> None:
        self._db = db
        self._user = current_user
        self._committee_ids: set[uuid.UUID] | None = None
        self._department_committee_ids: set[uuid.UUID] | None = None

    async def user_committee_ids(self) -> set[uuid.UUID]:
        if self._committee_ids is None:
            self._committee_ids = await _user_committee_ids(self._db, self._user.user_id)
        return self._committee_ids

    async def department_committee_ids(self, dep_id: uuid.UUID) -> set[uuid.UUID]:
        if self._department_committee_ids is None:
            self._department_committee_ids = await _department_committee_ids(self._db, dep_id)
        return self._department_committee_ids


async def can_view_document(
    db: AsyncSession,
    *,
    current_user: User,
    document: Document,
    viewer: DocumentViewer | None = None,
) -> bool:
    """
    قرار منتج (طلب صريح من المستخدمة 2026-09-02): تجاوز super_admin
    التلقائي لفحص الرؤية يبقى فقط للفئتين "الروتينيتين/التنظيميتين" —
    عامة (is_public) وإدارة محددة (أي إدارة، وليس إدارته فقط) — لأن
    الإدارات بيانات تنظيمية عادة. أمّا اللجان فقد تحمل أحيانًا مسائل أكثر
    حساسية، ومشاركة وثيقة مع مستخدمين محددين تحديدًا تعني أنها ليست
    موجَّهة لسوبر أدمن تحديدًا — فكلا الفئتين (لجنة/مستخدمون محددون)
    تُفحص لسوبر أدمن بنفس القاعدة المطبَّقة على أي مستخدم آخر (عضوية
    فعلية باللجنة، أو كونه أحد المستخدمين المحددين أنفسهم) بدل تجاوز
    شامل تلقائي. الرافع دائمًا يرى وثيقته (بصرف النظر عن نطاقها).

    viewer (اختياري): مرّري نفس DocumentViewer لكل وثائق القائمة الواحدة
    لتفادي إعادة الاستعلام عن لجان المستخدم لكل وثيقة.
    """
    if viewer is None:
        viewer = DocumentViewer(db, current_user)
    if document.is_public:
        return True
    if document.uploaded_by == current_user.user_id:
        return True
    if any(u.user_id == current_user.user_id for u in document.visible_users):
        return True
    if document.visible_departments:
        if current_user.is_super_admin:
            return True
        if current_user.dep_id is not None and any(
            d.dep_id == current_user.dep_id for d in document.visible_departments
        ):
            return True
    if document.visible_committees:
        visible_committee_ids = {c.committee_id for c in document.visible_committees}
        user_committee_ids = await viewer.user_committee_ids()
        if visible_committee_ids & user_committee_ids:
            return True
        # إضافة موثّقة مع لجينـ 2026-09-09: مَن يملك صلاحية طلب تشكيل
        # لجنة بنطاق "all" (الأدمن حاليًا) يشوف وثائق لجان إدارته حتى لو
        # ما كان عضوًا فيها فعليًا — لأنه هو مَن يطلب تشكيلها أصلًا.
        # مقيَّدة بإدارته هو تحديدًا (dep_id)، وليست تجاوزًا شاملًا لكل
        # اللجان. راجعي _department_committee_ids أعلاه لتعريف "لجان
        # الإدارة".
        if (
            current_user.dep_id is not None
            and current_user.scope_for("committees.request.create") == "all"
        ):
            department_committee_ids = await viewer.department_committee_ids(
                current_user.dep_id
            )
            if visible_committee_ids & department_committee_ids:
                return True
    return False


async def get_publish_targets(
    db: AsyncSession, *, current_user: User
) -> tuple[list[Department], list[Committee]]:
    """
    الإدارات واللجان اللي يحق فعليًا لـcurrent_user إتاحة وثيقة لها عند
    الرفع/التعديل (مبدأ أقل صلاحية ممكنة) — راجعي docstring
    DocumentPublishTargetsOut بـ app/schemas/document.py. لا علاقة لها
    بفحص "رؤية" وثيقة موجودة أصلًا (can_view_document أعلاه) — هذه فقط
    لتضييق خيارات المستخدم وقت الرفع/التعديل بدل عرض قوائم الإدارات/اللجان
    الكاملة له.

    النطاق (documents.upload/update، أوسعهما عبر scope_for — بنفس منطق
    committee_service) هو ما يحدد الاتساع:
    - 'all' (أو super_admin): كل الإدارات وكل اللجان (غير المحذوفة).
    - 'department': إدارته فقط (إن وُجدت) + اللجان اللي هو عضو فيها.
    - 'own' أو بلا نطاق مسجَّل إطلاقًا: بلا إدارات (لا يقدر يشارك إدارة
      كاملة بوثيقة)، فقط اللجان اللي هو عضو فيها.
    """
    scope = current_user.scope_for("documents.upload", "documents.update")

    if current_user.is_super_admin or scope == "all":
        department_result = await db.execute(
            departments_query().where(Department.deleted_at.is_(None)).order_by(Department.name)
        )
        committee_result = await db.execute(
            committees_query().where(Committee.deleted_at.is_(None)).order_by(Committee.name)
        )
        return list(department_result.scalars().all()), list(committee_result.scalars().all())

    departments: list[Department] = []
    if scope == "department" and current_user.dep_id is not None:
        department = await load_department(db, current_user.dep_id)
        if department is not None and not department.is_deleted:
            departments = [department]

    committee_ids = await _user_committee_ids(db, current_user.user_id)
    committees: list[Committee] = []
    if committee_ids:
        committee_result = await db.execute(
            committees_query()
            .where(Committee.committee_id.in_(committee_ids), Committee.deleted_at.is_(None))
            .order_by(Committee.name)
        )
        committees = list(committee_result.scalars().all())

    return departments, committees
