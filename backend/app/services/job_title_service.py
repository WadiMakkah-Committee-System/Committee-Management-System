"""
الهدف:
منطق العمل الخاص بإدارة المسميات الوظيفية (Job Titles) — وحدة مستقلة
تمامًا عن الأدوار (Roles)، تُستخدم لعرض منصب المستخدم الفعلي بجانب اسمه
(مثال: منتقي أعضاء طلب تشكيل اللجنة)، وكحقل اختياري بنموذج المستخدم.

المسؤولية:
- إنشاء/عرض/تعديل/حذف المسميات الوظيفية.
- تسجيل كل عملية تغيير في audit_logs عبر audit_service.
- منع حذف مسمى وظيفي لا يزال مستخدَمًا من قِبل مستخدم واحد على الأقل
  (نفس نمط role_service.delete_role).

ملاحظات:
- الحذف هنا فعلي (DELETE)، وليس Soft Delete كالإدارات — قرار عمل موثّق،
  لأن المسمى الوظيفي (بعكس الإدارة) لا يحمل تاريخًا تنظيميًا يستدعي
  الاحتفاظ به بعد حذفه.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_title import JobTitle
from app.models.user import User
from app.services import audit_service


async def _assert_unique_name(
    db: AsyncSession, name: str, *, exclude_job_title_id: uuid.UUID | None = None
) -> None:
    stmt = select(JobTitle).where(func.lower(JobTitle.name) == name.lower())
    if exclude_job_title_id is not None:
        stmt = stmt.where(JobTitle.job_title_id != exclude_job_title_id)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none() is not None:
        raise ValueError("هذا المسمى الوظيفي موجود مسبقًا")


async def list_job_titles(db: AsyncSession) -> list[JobTitle]:
    """كل المسميات الوظيفية، مرتبة أبجديًا — تُستخدم بصفحة الإدارة وبالقائمة المنسدلة القابلة للبحث."""
    result = await db.execute(select(JobTitle).order_by(JobTitle.name))
    return list(result.scalars().all())


async def get_job_title(db: AsyncSession, job_title_id: uuid.UUID) -> JobTitle | None:
    return await db.get(JobTitle, job_title_id)


async def create_job_title(db: AsyncSession, *, actor_user_id: uuid.UUID, name: str) -> JobTitle:
    """
    إنشاء مسمى وظيفي جديد. يرفع ValueError إذا كان الاسم مستخدمًا مسبقًا.

    يُستدعى أيضًا من داخل نموذج المستخدم (CreatableSelect) عند إضافة مسمى
    جديد مباشرة بدون مغادرة النموذج — نفس المسار بالضبط.
    """
    await _assert_unique_name(db, name)

    job_title = JobTitle(name=name)
    db.add(job_title)
    await db.flush()

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="job_title",
        target_id=job_title.job_title_id,
        metadata={"name": name},
    )

    await db.commit()
    await db.refresh(job_title)
    return job_title


async def update_job_title(
    db: AsyncSession, *, actor_user_id: uuid.UUID, job_title_id: uuid.UUID, name: str
) -> JobTitle | None:
    """تعديل مسمى وظيفي موجود. يرجع None إذا لم يوجد، ويرفع ValueError إذا الاسم الجديد مستخدَم مسبقًا."""
    job_title = await get_job_title(db, job_title_id)
    if job_title is None:
        return None

    await _assert_unique_name(db, name, exclude_job_title_id=job_title_id)

    before_name = job_title.name
    job_title.name = name

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="update",
        target_type="job_title",
        target_id=job_title.job_title_id,
        metadata={"before": before_name, "after": name},
    )

    await db.commit()
    await db.refresh(job_title)
    return job_title


async def delete_job_title(
    db: AsyncSession, *, actor_user_id: uuid.UUID, job_title_id: uuid.UUID
) -> JobTitle | None:
    """
    حذف مسمى وظيفي (حذف فعلي). يرجع None إذا لم يوجد أصلًا، ويرفع
    ValueError إذا كان لا يزال مستخدَمًا من قِبل مستخدم واحد على الأقل
    (غير محذوف) — نفس نمط الحماية المستخدَم بحذف الأدوار.
    """
    job_title = await get_job_title(db, job_title_id)
    if job_title is None:
        return None

    count_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.job_title_id == job_title_id, User.deleted_at.is_(None))
    )
    if count_result.scalar_one() > 0:
        raise ValueError("لا يمكن حذف هذا المسمى الوظيفي — لا يزال هناك مستخدمون مرتبطون به")

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="delete",
        target_type="job_title",
        target_id=job_title.job_title_id,
        metadata={"name": job_title.name},
    )

    await db.delete(job_title)
    await db.commit()
    return job_title
