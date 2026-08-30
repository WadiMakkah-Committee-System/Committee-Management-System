"""
الهدف:
منطق العمل (Business Logic) الخاص بإدارة المستخدمين — FR-UM-001 → FR-UM-006،
FR-UM-021 → FR-UM-022 (إنشاء، عرض، تعديل، حذف، إيقاف، إعادة تفعيل).

المسؤولية:
- إنشاء مستخدمين جدد (بكلمة مرور مؤقتة تفرض تغييرها عند أول دخول —
  FR-UM-016)، مع تشفير كلمة المرور عبر core.security.
- عرض/تعديل/حذف (Soft Delete) المستخدمين.
- إيقاف/إعادة تفعيل الحساب (status) — FR-UM-004.
- تسجيل كل عملية في audit_logs.

ملاحظات:
- لا يوجد أي تحقق من الصلاحيات (RBAC) هنا — هذا مسؤولية core/dependencies.py
  وطبقة الـ API. هذه الخدمة تفترض أن الاستدعاء مصرّح له مسبقًا.
- قاعدة عمل مهمة (موثّقة في ERD): كل مستخدم ينتمي لإدارة واحدة فقط
  (dep_id مفرد، وليس علاقة متعددة).
"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.role import Role
from app.models.user import User, UserStatus
from app.services import audit_service


async def _count_other_active_super_admins(db: AsyncSession, *, excluding_user_id: uuid.UUID) -> int:
    """
    يحسب عدد حسابات super_admin النشطة (غير محذوفة وغير موقوفة) باستثناء
    مستخدم معيّن — يُستخدم لمنع أي عملية (حذف/إيقاف/تغيير دور) قد تترك
    النظام بدون super_admin واحد قادر على تسجيل الدخول وإدارته.

    "super_admin" هنا يُحدَّد عبر Role.is_super_admin (وليس مقارنة اسم
    نصي ثابت) — لأن الأدوار أصبحت ديناميكية، لكن يبقى دورًا جذريًا واحدًا
    محميًا دائمًا في النظام (مضمون عبر منع تعديل/حذف is_system في role_service).
    """
    result = await db.execute(
        select(func.count())
        .select_from(User)
        .join(Role, Role.role_id == User.role_id)
        .where(
            Role.is_super_admin.is_(True),
            User.deleted_at.is_(None),
            User.status == UserStatus.active,
            User.user_id != excluding_user_id,
        )
    )
    return result.scalar_one()


async def create_user(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    first_name: str,
    middle_name: str,
    last_name: str,
    username: str,
    email: str,
    password: str,
    role_id: uuid.UUID | None = None,
    dep_id: uuid.UUID | None = None,
    job_title_id: uuid.UUID | None = None,
    status: UserStatus = UserStatus.active,
) -> User | None:
    """
    إنشاء مستخدم جديد. يرفع ValueError إذا كان username أو email مستخدمًا
    مسبقًا لحساب نشط (غير محذوف)، أو إذا كان الدور المحدد غير موجود.

    role_id اختياري (مراجعة لاما 2026-08-30 — "لا تجعل حقل الدور إجباريًا
    عند إضافة مستخدم"): مستخدم بلا دور يُنشأ بنجاح، ويدخل النظام بلا أي
    صلاحيات إضافية (فقط GET /users/me) لحين تعيين دور له لاحقًا.
    """
    existing = await db.execute(
        select(User).where(
            or_(
                func.lower(User.username) == username.lower(),
                func.lower(User.email) == email.lower(),
            ),
            User.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("اسم المستخدم أو البريد الإلكتروني مستخدم مسبقًا")

    role: Role | None = None
    if role_id is not None:
        role = await db.get(Role, role_id)
        if role is None:
            raise ValueError("الدور المحدد غير موجود")

    if job_title_id is not None:
        job_title = await db.get(JobTitle, job_title_id)
        if job_title is None:
            raise ValueError("المسمى الوظيفي المحدد غير موجود")

    user = User(
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role_id=role_id,
        dep_id=dep_id,
        job_title_id=job_title_id,
        status=status,
        must_change_password=True,  # FR-UM-016: يُفرض تغيير كلمة المرور عند أول دخول
    )
    db.add(user)
    await db.flush()

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="user",
        target_id=user.user_id,
        metadata={"username": username, "role": role.name if role else None},
    )

    await db.commit()
    return await get_user(db, user.user_id)


async def list_users(
    db: AsyncSession, *, dep_id: uuid.UUID | None = None
) -> list[User]:
    """عرض المستخدمين النشطين (غير المحذوفين)، مع تصفية اختيارية حسب الإدارة."""
    stmt = (
        select(User)
        .options(selectinload(User.department).selectinload(Department.manager))
        .where(User.deleted_at.is_(None))
    )
    if dep_id is not None:
        stmt = stmt.where(User.dep_id == dep_id)
    result = await db.execute(stmt.order_by(User.created_at.desc()))
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """
    جلب مستخدم واحد (النشط فقط) عبر معرّفه، مع تحميل بيانات إدارته
    (selectinload) في نفس الاستعلام — عشان UserOut يقدر يُرجع اسم الإدارة
    مباشرة بدون الحاجة لطلب API منفصل لصفحة الإدارات.
    """
    result = await db.execute(
        select(User)
        .options(selectinload(User.department).selectinload(Department.manager))
        .where(User.user_id == user_id, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """جلب مستخدم عبر username — يُستخدم عند تسجيل الدخول."""
    result = await db.execute(
        select(User).where(
            func.lower(User.username) == username.lower(), User.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """جلب مستخدم عبر البريد الإلكتروني — يُستخدم في نسيت كلمة المرور."""
    result = await db.execute(
        select(User).where(func.lower(User.email) == email.lower(), User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_user(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    user_id: uuid.UUID,
    first_name: str | None = None,
    middle_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    role_id: uuid.UUID | None = None,
    dep_id: uuid.UUID | None = None,
    job_title_id: uuid.UUID | None = None,
) -> User | None:
    """
    تعديل بيانات مستخدم موجود. يرجع None إذا لم يوجد.

    يرفع ValueError إذا كان التعديل سيغيّر دور آخر super_admin نشط في
    النظام إلى دور آخر — حماية من ترك النظام بدون أي حساب قادر على إدارته.
    """
    user = await get_user(db, user_id)
    if user is None:
        return None

    new_role: Role | None = None
    if role_id is not None:
        new_role = await db.get(Role, role_id)
        if new_role is None:
            raise ValueError("الدور المحدد غير موجود")

        if not new_role.is_super_admin and user.is_super_admin:
            remaining = await _count_other_active_super_admins(db, excluding_user_id=user.user_id)
            if remaining == 0:
                raise ValueError(
                    "لا يمكن تغيير دور هذا المستخدم — إنه آخر super_admin نشط في النظام"
                )

    before = {
        "role": user.role.name if user.role else None,
        "dep_id": str(user.dep_id) if user.dep_id else None,
    }

    if first_name is not None:
        user.first_name = first_name
    if middle_name is not None:
        user.middle_name = middle_name
    if last_name is not None:
        user.last_name = last_name
    if email is not None:
        user.email = email
    if new_role is not None:
        user.role_id = new_role.role_id
    if dep_id is not None:
        user.dep_id = dep_id
    if job_title_id is not None:
        job_title = await db.get(JobTitle, job_title_id)
        if job_title is None:
            raise ValueError("المسمى الوظيفي المحدد غير موجود")
        user.job_title_id = job_title_id

    await db.flush()
    await db.refresh(user, attribute_names=["role", "job_title"])

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="update",
        target_type="user",
        target_id=user.user_id,
        metadata={"before": before, "after": {"role": user.role.name if user.role else None}},
    )

    await db.commit()
    return await get_user(db, user.user_id)


async def soft_delete_user(
    db: AsyncSession, *, actor_user_id: uuid.UUID, user_id: uuid.UUID
) -> User | None:
    """
    حذف مستخدم (Soft Delete) — FR-UM-005.

    يرفع ValueError إذا كان المستخدم آخر super_admin نشط في النظام — حذفه
    يترك النظام بدون أي حساب قادر على إدارته (لا أحد يقدر يضيف حسابات أو
    إدارات بعدها).
    """
    user = await get_user(db, user_id)
    if user is None:
        return None

    if user.is_super_admin:
        remaining = await _count_other_active_super_admins(db, excluding_user_id=user.user_id)
        if remaining == 0:
            raise ValueError("لا يمكن حذف هذا المستخدم — إنه آخر super_admin نشط في النظام")

    user.deleted_at = func.now()

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="delete",
        target_type="user",
        target_id=user.user_id,
        metadata={"username": user.username},
    )

    await db.commit()
    await db.refresh(user)
    return user


async def set_user_status(
    db: AsyncSession, *, actor_user_id: uuid.UUID, user_id: uuid.UUID, status: UserStatus
) -> User | None:
    """
    إيقاف/إعادة تفعيل حساب — FR-UM-004. الإيقاف يمنع تسجيل الدخول فقط،
    ولا يخفي بيانات المستخدم من الشاشات الأخرى (مثل عضويات اللجان).

    يرفع ValueError عند محاولة إيقاف آخر super_admin نشط (الإيقاف يمنع
    الدخول تمامًا، فله نفس أثر الحذف على قدرة النظام على أن يُدار).
    إعادة التفعيل لا تحتاج هذا الفحص أبدًا (لا يمكن أن تُنقص العدد).
    """
    user = await get_user(db, user_id)
    if user is None:
        return None

    if status == UserStatus.suspended and user.is_super_admin:
        remaining = await _count_other_active_super_admins(db, excluding_user_id=user.user_id)
        if remaining == 0:
            raise ValueError("لا يمكن إيقاف هذا الحساب — إنه آخر super_admin نشط في النظام")

    user.status = status
    action = "suspend" if status == UserStatus.suspended else "reactivate"

    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type=action,
        target_type="user",
        target_id=user.user_id,
        metadata={"username": user.username},
    )

    await db.commit()
    return await get_user(db, user.user_id)
