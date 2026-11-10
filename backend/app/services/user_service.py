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

import asyncio
import uuid

from sqlalchemy import delete, func, literal_column, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, noload, raiseload, selectinload

from app.core.security import hash_password
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.role import Permission, Role, RolePermission
from app.models.user import User, UserStatus
from app.models.user_role import UserRole
from app.services import audit_service


async def _count_other_active_super_admins(db: AsyncSession, *, excluding_user_id: uuid.UUID) -> int:
    """
    يحسب عدد حسابات super_admin النشطة (غير محذوفة وغير موقوفة) باستثناء
    مستخدم معيّن — يُستخدم لمنع أي عملية (حذف/إيقاف/تغيير دور) قد تترك
    النظام بدون super_admin واحد قادر على تسجيل الدخول وإدارته.

    "super_admin" هنا يُحدَّد عبر Role.is_super_admin (وليس مقارنة اسم
    نصي ثابت) — لأن الأدوار أصبحت ديناميكية، لكن يبقى دورًا جذريًا واحدًا
    محميًا دائمًا في النظام (مضمون عبر منع تعديل/حذف is_system في role_service).

    تعدد الأدوار (migration 0046): يُعدّ من الأدوار المسندة (user_roles)
    وليس من الدور الحالي — سوبر ادمن بدّل دوره الحالي لدور آخر يبقى قادرًا
    على إدارة النظام (يرجع لدور السوبر ادمن متى شاء)، فيُحسب.
    """
    result = await db.execute(
        select(func.count(func.distinct(User.user_id)))
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.user_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(
            Role.is_super_admin.is_(True),
            User.deleted_at.is_(None),
            User.status == UserStatus.active,
            User.user_id != excluding_user_id,
        )
    )
    return result.scalar_one()


#: أعمدة الدور اللي تحتاجها فحوصات الإسناد — تُقرأ كأعمدة (Row) وليس
#: كائنات Role عمدًا: تحميل Role بلا صلاحياته (noload) يترك نسخة ناقصة في
#: الـidentity map، فأي تحميل لاحق لنفس الدور بنفس الجلسة (مثل الدور الحالي
#: بعد التبديل) يرجع بصلاحيات فارغة. الأعمدة لا تلمس الـidentity map إطلاقًا.
_ROLE_COLUMNS = (Role.role_id, Role.name, Role.kind, Role.is_super_admin)


async def _load_assigned_roles(db: AsyncSession, user_id: uuid.UUID) -> list:
    """
    الأدوار النظامية المسندة لمستخدم (user_roles) — صفوف بأعمدة
    (role_id, name, kind, is_super_admin) بترتيب الإسناد. استعلام واحد.
    """
    result = await db.execute(
        select(*_ROLE_COLUMNS)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id)
        .order_by(UserRole.created_at, Role.name)
    )
    return list(result.all())


async def _has_super_admin_role(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """هل دور super_admin من أدوار المستخدم المسندة (بغض النظر عن دوره الحالي)؟"""
    result = await db.execute(
        select(func.count())
        .select_from(UserRole)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(UserRole.user_id == user_id, Role.is_super_admin.is_(True))
    )
    return result.scalar_one() > 0


def _normalize_role_selection(
    role_ids: list[uuid.UUID] | None, role_id: uuid.UUID | None
) -> tuple[list[uuid.UUID] | None, uuid.UUID | None]:
    """
    الهدف:
    توحيد طريقتي تحديد الأدوار في الطلب: role_ids (قائمة — تعدد الأدوار،
    migration 0046) أو role_id (دور واحد — الطريقة القديمة، محفوظة للتوافق
    مع رفع ملف المستخدمين وأي عميل قديم).

    المخرجات: (قائمة الأدوار المطلوبة بلا تكرار وبنفس الترتيب أو None = "لا
    تغيير"، الدور الحالي المفضَّل أو None).

    قواعد العمل:
    - role_ids وحدها: الأدوار = القائمة، والدور الحالي يُحدَّد لاحقًا.
    - role_id وحده: يعني "دور واحد فقط" = [role_id] (نفس السلوك القديم).
    - الاثنان معًا: role_id هو الدور الحالي المطلوب، ولازم يكون ضمن role_ids.

    الأخطاء: ValueError لو role_id ليس ضمن role_ids.
    """
    if role_ids is None:
        if role_id is None:
            return None, None
        return [role_id], role_id
    unique_ids = list(dict.fromkeys(role_ids))
    if role_id is not None and role_id not in unique_ids:
        raise ValueError("الدور الحالي المحدد يجب أن يكون ضمن أدوار المستخدم")
    return unique_ids, role_id


async def _validate_system_roles(db: AsyncSession, role_ids: list[uuid.UUID]) -> list:
    """
    الهدف: التحقق أن كل الأدوار المطلوبة موجودة ومن نوع "دور نظامي".

    المخرجات: صفوف أعمدة الدور (_ROLE_COLUMNS) بنفس ترتيب role_ids — استعلام
    واحد لكل القائمة.

    الأخطاء: ValueError لو دور غير موجود، أو دور لجنة.

    قواعد العمل (مراجعة لاما 2026-08-31): "رئيس اللجنة"/"عضو اللجنة" ليسا من
    System Roles إطلاقًا — لا يجوز إسنادهما للمستخدم أبدًا، حتى لو أرسل العميل
    معرّفهما مباشرة عبر الـ API (لا يكفي إخفاؤهما من قائمة الاختيار بالفرونت
    فقط). قاعدة البيانات تمنعها أيضًا (Trigger بـmigration 0046)، وهذا الفحص
    يسبقها برسالة واضحة.
    """
    if not role_ids:
        return []
    result = await db.execute(select(*_ROLE_COLUMNS).where(Role.role_id.in_(role_ids)))
    by_id = {row.role_id: row for row in result.all()}
    roles: list = []
    for rid in role_ids:
        role = by_id.get(rid)
        if role is None:
            raise ValueError("الدور المحدد غير موجود")
        if role.kind == "committee":
            raise ValueError("لا يمكن إسناد دور لجنة كدور نظامي للمستخدم")
        roles.append(role)
    return roles


def assigned_roles_profile_column(user_id: uuid.UUID):
    """
    الهدف:
    عمود SQL واحد (scalar subquery → JSONB) يرجّع كل أدوار المستخدم المسندة
    مع أكواد صلاحيات كل دور — لـGET /users/me ورد تسجيل الدخول.

    المخرجات: قائمة JSON بالشكل
    [{"role_id", "name", "description", "is_super_admin", "permissions": [..]}]
    بترتيب الإسناد ([] لمستخدم بلا أدوار).

    سبب التصميم (أداء): يُدمج بنفس استعلام أعلام عضوية اللجان الموجود أصلًا
    بـbuild_my_profile، فـ/users/me يبقى استعلامين فقط (المصادقة + هذا)، بلا
    أي استعلام إضافي. الواجهة تحتاج صلاحيات كل دور لتعرف أي دور من أدوار
    المستخدم يفتح صفحة معيّنة (رسالة "هذه الصفحة تتبع دورًا آخر").
    """
    codes = (
        select(
            func.coalesce(
                func.jsonb_agg(aggregate_order_by(Permission.code, Permission.code)),
                literal_column("'[]'::jsonb"),
            )
        )
        .select_from(RolePermission)
        .join(Permission, Permission.permission_id == RolePermission.permission_id)
        .where(RolePermission.role_id == Role.role_id)
        .correlate(Role)
        .scalar_subquery()
    )
    role_obj = func.jsonb_build_object(
        "role_id", Role.role_id,
        "name", Role.name,
        "description", Role.description,
        "is_super_admin", Role.is_super_admin,
        "permissions", codes,
    )
    aggregated = (
        select(
            func.coalesce(
                func.jsonb_agg(aggregate_order_by(role_obj, UserRole.created_at, Role.name)),
                literal_column("'[]'::jsonb"),
            )
        )
        .select_from(UserRole)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
        .scalar_subquery()
    )
    return type_coerce(aggregated, JSONB)


async def load_profile_extras(db: AsyncSession, *, user_id: uuid.UUID) -> dict:
    """
    الهدف:
    البيانات الإضافية لشكل /users/me ورد تسجيل الدخول — أعلام عضوية اللجان
    الثلاثة + أدوار المستخدم المسندة مع صلاحيات كل دور (تعدد الأدوار،
    migration 0046).

    المخرجات: dict بمفاتيح UserDetailOut نفسها:
    has_committee_membership_access, has_any_committee_membership,
    has_committee_documents_view_access, roles (أعمدة RoleSummaryOut)،
    roles_permissions ({role_id: [codes]}).

    الأداء: استعلام واحد فقط — نفس عدد الاستعلامات قبل تعدد الأدوار (كان
    committee_membership_flags وحده)؛ أعمدة الأعلام وعمود الأدوار كلها
    scalar subqueries داخل SELECT واحد.

    الاعتماديات: committee_service.committee_membership_flag_columns.
    """
    from app.services import committee_service  # استيراد متأخر: تفادي أي دورة استيراد مستقبلية

    row = (
        await db.execute(
            select(
                *committee_service.committee_membership_flag_columns(user_id),
                assigned_roles_profile_column(user_id),
            )
        )
    ).one()
    assigned = row[3] or []
    return {
        "has_committee_membership_access": (row[0] or 0) > 0,
        "has_any_committee_membership": (row[1] or 0) > 0,
        "has_committee_documents_view_access": (row[2] or 0) > 0,
        "roles": [
            {
                "role_id": r["role_id"],
                "name": r["name"],
                "description": r["description"],
                "is_super_admin": r["is_super_admin"],
            }
            for r in assigned
        ],
        "roles_permissions": {str(r["role_id"]): list(r["permissions"] or []) for r in assigned},
    }


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
    role_ids: list[uuid.UUID] | None = None,
    dep_id: uuid.UUID | None = None,
    job_title_id: uuid.UUID | None = None,
    status: UserStatus = UserStatus.active,
) -> User | None:
    """
    إنشاء مستخدم جديد. يرفع ValueError إذا كان username أو email مستخدمًا
    مسبقًا لحساب نشط (غير محذوف)، أو إذا كان أحد الأدوار المحددة غير موجود
    أو دور لجنة.

    الأدوار اختيارية (مراجعة لاما 2026-08-30 — "لا تجعل حقل الدور إجباريًا
    عند إضافة مستخدم"): مستخدم بلا دور يُنشأ بنجاح، ويدخل النظام بلا أي
    صلاحيات إضافية (فقط GET /users/me) لحين تعيين دور له لاحقًا.

    تعدد الأدوار (migration 0046): role_ids = كل أدوار المستخدم (دور واحد أو
    أكثر)، وrole_id (اختياري) = دوره الحالي عند أول دخول (وإلا أول دور
    بالقائمة). role_id وحده = دور واحد (الطريقة القديمة). راجعي
    _normalize_role_selection.

    التأثيرات الجانبية: صف users + صف user_roles لكل دور + سجل تدقيق — كلها
    بمعاملة واحدة.
    """
    requested_ids, preferred_active = _normalize_role_selection(role_ids, role_id)
    requested_ids = requested_ids or []

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

    roles = await _validate_system_roles(db, requested_ids)
    active_role_id = preferred_active or (roles[0].role_id if roles else None)

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
        password_hash=await asyncio.to_thread(hash_password, password),
        role_id=active_role_id,
        dep_id=dep_id,
        job_title_id=job_title_id,
        status=status,
        must_change_password=True,  # FR-UM-016: يُفرض تغيير كلمة المرور عند أول دخول
    )
    db.add(user)
    await db.flush()
    # قيد users_active_role_assigned_fkey مؤجَّل لحد COMMIT، فترتيب الإدراج
    # (users ثم user_roles) داخل نفس المعاملة سليم.
    db.add_all(
        [UserRole(user_id=user.user_id, role_id=role.role_id, assigned_by=actor_user_id) for role in roles]
    )

    active_name = next((r.name for r in roles if r.role_id == active_role_id), None)
    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="create",
        target_type="user",
        target_id=user.user_id,
        metadata={
            "username": username,
            "role": active_name,
            "roles": [r.name for r in roles],
        },
    )

    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    result = await get_user_with_roles(db, user.user_id)
    await db.commit()
    return result


async def list_users(
    db: AsyncSession, *, dep_id: uuid.UUID | None = None
) -> list[User]:
    """عرض المستخدمين النشطين (غير المحذوفين)، مع تصفية اختيارية حسب الإدارة."""
    # نفس تحسين get_user أعلاه، لكن بحذر إضافي هنا: department/manager
    # علاقة واحد-لواحد فتجميعها بـjoinedload آمن دائمًا (رحلة شبكة واحدة
    # بدل اثنتين). أما role_permission_links/permission فعلاقة واحد-لعدة
    # (كل دور قد يملك عشرات الصلاحيات) — تركناها selectin (تحميلها التلقائي
    # من مستوى الموديل، بدون .options() صريح) بدل joinedload هنا تحديدًا،
    # لأن joinedload لعلاقة "عدة" مع استعلام يرجّع *قائمة* مستخدمين (وليس
    # مستخدمًا واحدًا كـget_user) يضاعف صفوف النتيجة الخام بعدد صلاحيات كل
    # دور × عدد المستخدمين المشتركين بنفس الدور — selectin هنا يبقى فعليًا
    # رحلة شبكة واحدة فقط تغطي كل الأدوار المسحوبة دفعة واحدة، فلا داعٍ
    # لتحمّل مخاطرة تضخّم النتيجة مقابل نفس الفائدة تقريبًا.
    # إعادة هيكلة 2026-10-24: استعلام واحد بشكل UserOut بالضبط — الدور
    # (RoleSummaryOut: أعمدته فقط) والمسمى والإدارة ومديرها بـJOIN، بدل
    # selectin الافتراضي على User.role الذي كان يجرّ روابط صلاحيات كل دور
    # وكل صلاحية (لا تُعرض بالقائمة إطلاقًا).
    manager = joinedload(User.department).joinedload(Department.manager)
    stmt = (
        select(User)
        .options(
            joinedload(User.role).raiseload("*", sql_only=True),
            joinedload(User.job_title).raiseload("*", sql_only=True),
            joinedload(User.department).raiseload("*", sql_only=True),
            manager,
            manager.raiseload("*", sql_only=True),
            # تعدد الأدوار (migration 0046): كل أدوار كل المستخدمين المعروضين
            # باستعلام واحد إضافي فقط (selectin = IN على كل المعرّفات)، بأعمدة
            # الدور فقط بلا صلاحياته — تعرضها صفحة المستخدمين ونموذج التعديل.
            selectinload(User.assigned_roles).raiseload("*", sql_only=True),
            raiseload("*", sql_only=True),
        )
        .where(User.deleted_at.is_(None))
    )
    if dep_id is not None:
        stmt = stmt.where(User.dep_id == dep_id)
    result = await db.execute(stmt.order_by(User.created_at.desc()))
    return list(result.unique().scalars().all())


def _profile_options() -> tuple:
    """شكل المستخدم الكامل (UserDetailOut / المصادقة): إدارته (ومديرها بأعمدته
    فقط) + دوره بكل صلاحياته + مسماه — كلها JOIN باستعلام واحد."""
    manager = joinedload(User.department).joinedload(Department.manager)
    return (
        manager.noload(User.role),
        manager.noload(User.job_title),
        joinedload(User.role).joinedload(Role.role_permission_links).joinedload(
            RolePermission.permission
        ),
        joinedload(User.job_title),
    )


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """
    جلب مستخدم واحد (النشط فقط) عبر معرّفه، مع تحميل بيانات إدارته
    (selectinload) في نفس الاستعلام — عشان UserOut يقدر يُرجع اسم الإدارة
    مباشرة بدون الحاجة لطلب API منفصل لصفحة الإدارات.
    """
    # إصلاح 2026-09-13 (تحقيق أداء لاما — 6 استعلامات لـget_user وحدها
    # على مسار المصادقة بكل طلب): department.manager هو User آخر (مدير
    # الإدارة)، وUser.role/User.job_title كلاهما lazy="selectin" افتراضي
    # بالموديل — يعني بمجرد تحميل manager تلقائيًا يتحمّل .role و.job_title
    # الخاصين فيه (ثم .role يجرّ role_permission_links ثم permission).
    # تحقّقتُ من app/schemas/department.py (DepartmentManagerOut): يحتوي
    # فقط user_id/first_name/middle_name/last_name/email — بلا دور أو
    # مسمى وظيفي إطلاقًا، بأي مكان يُستخدَم فيه get_user (المصادقة بكل
    # طلب، وendpoints /users). noload صريح يمنع هذا التحميل التلقائي غير
    # المُستهلَك.
    #
    # تحسين إضافي 2026-09-13: user.job_title الخاص بالمستخدم نفسه (لا
    # المدير) فعليًا مطلوب (UserOut.job_title) وكان يتحمّل عبر round trip
    # منفصل (lazy="selectin" الافتراضي بدون .options() صريح له). scalar
    # بحتة (many-to-one) — joinedload صريح هنا يدمجه بنفس استعلام users
    # الرئيسي فيلغي هذا الـround trip كليًا بدل تحسينه فقط.
    result = await db.execute(
        select(User)
        .options(*_profile_options())
        .where(User.user_id == user_id, User.deleted_at.is_(None))
    )
    # .unique() إلزامي هنا لأن role_permission_links مجموعة (one-to-many)
    # مُحمَّلة بـjoinedload — بدونها SQLAlchemy يرمي خطأ لاحتمال تكرار صف
    # User الواحد بعدد صلاحيات دوره بنتيجة الـJOIN الخام.
    return result.unique().scalar_one_or_none()


async def get_user_with_roles(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """
    نفس get_user + كل أدوار المستخدم المسندة (User.assigned_roles → UserOut.roles)
    — لمسارات إدارة المستخدمين (تفاصيل مستخدم، رد الإنشاء/التعديل) فقط.

    منفصلة عن get_user عمدًا: get_user هي مسار المصادقة بكل طلب، فلا نضيف
    عليها استعلام الأدوار (+1) اللي ما يحتاجه أي فحص صلاحيات (الفحوصات كلها
    على الدور الحالي فقط).
    """
    result = await db.execute(
        select(User)
        .options(
            *_profile_options(),
            selectinload(User.assigned_roles).raiseload("*", sql_only=True),
        )
        .where(User.user_id == user_id, User.deleted_at.is_(None))
    )
    return result.unique().scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """جلب مستخدم عبر username — يُستخدم عند تسجيل الدخول.

    تحسين أداء 2026-10-24: كان select(User) يجرّ تلقائيًا (lazy="selectin")
    الدور ثم روابط صلاحياته ثم الصلاحيات ثم المسمى = 4-5 استعلامات متتالية
    قبل حتى التحقق من كلمة المرور.

    تحديث 2026-10-25: يُحمَّل المستخدم بشكله الكامل (نفس get_user) بنفس
    الاستعلام الواحد (JOIN)، لأن رد تسجيل الدخول صار يتضمن بيانات المستخدم
    (UserDetailOut) — فالواجهة لا تحتاج طلب /users/me منفصلًا بعده.
    """
    result = await db.execute(
        select(User)
        .options(*_profile_options())
        .where(func.lower(User.username) == username.lower(), User.deleted_at.is_(None))
    )
    return result.unique().scalar_one_or_none()


async def get_user_by_login_identifier(db: AsyncSession, identifier: str) -> User | None:
    """
    الهدف:
    جلب المستخدم اللي يحاول تسجيل الدخول بكلمة المرور — باسم المستخدم أو
    بالبريد الإلكتروني (طلب صاحب المشروع 2026-11-10).

    المدخلات: identifier — النص المكتوب بخانة الدخول (اسم مستخدم أو بريد).

    المخرجات: المستخدم بشكله الكامل (نفس get_user_by_username) أو None.

    قواعد العمل:
    - المقارنة بدون حساسية لحالة الأحرف وبعد حذف المسافات الطرفية، وللحسابات
      غير المحذوفة فقط.
    - لو طابق النص اسم مستخدم لحساب وبريد حساب آخر (حالة نادرة: اسم مستخدم
      فيه @)، الأولوية لاسم المستخدم — نفس سلوك الدخول قبل هذه الميزة، فلا
      يتغيّر دخول أي حساب قائم.

    الأداء: استعلام واحد (OR) بنفس خيارات التحميل — يرجع صفًا أو صفين على
    الأكثر، والاختيار بينهما بالذاكرة. عمود البريد عليه فهرس
    idx_users_email_lower_active (migration 0042).
    """
    value = identifier.strip().lower()
    if not value:
        return None
    result = await db.execute(
        select(User)
        .options(*_profile_options())
        .where(
            or_(func.lower(User.username) == value, func.lower(User.email) == value),
            User.deleted_at.is_(None),
        )
    )
    candidates = result.unique().scalars().all()
    by_username = next((u for u in candidates if u.username.lower() == value), None)
    if by_username is not None:
        return by_username
    by_email = [u for u in candidates if u.email.lower() == value]
    # أكثر من حساب بنفس البريد (لا يُفترض — الإنشاء يمنعه) ⇒ لا نخمّن أيهم.
    return by_email[0] if len(by_email) == 1 else None


async def find_users_for_microsoft_login(db: AsyncSession, email: str, object_id: uuid.UUID) -> list[User]:
    """
    الهدف: المرشحون للدخول بحساب Microsoft (migration 0042) — المستخدمون غير
    المحذوفين اللي بريدهم يطابق بريد Microsoft (بدون حساسية لحالة الأحرف) أو
    المرتبطون مسبقًا بنفس Object ID.
    المخرجات: قائمة بالشكل الكامل (نفس get_user_by_username) — المنطق
    (تعارض/تكرار/ربط) بـauth_service.authenticate_microsoft.
    """
    result = await db.execute(
        select(User)
        .options(*_profile_options())
        .where(
            User.deleted_at.is_(None),
            or_(func.lower(User.email) == email.lower(), User.microsoft_object_id == object_id),
        )
    )
    return list(result.unique().scalars().all())


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
    role_ids: list[uuid.UUID] | None = None,
    dep_id: uuid.UUID | None = None,
    job_title_id: uuid.UUID | None = None,
) -> User | None:
    """
    تعديل بيانات مستخدم موجود. يرجع None إذا لم يوجد.

    الأدوار (تعدد الأدوار — migration 0046):
    - role_ids = None و role_id = None: الأدوار بلا تغيير.
    - role_ids = قائمة: تستبدل أدوار المستخدم بالكامل ([] = إزالة كل
      أدواره). الدور الحالي يبقى كما هو لو ما زال ضمن القائمة، وإلا يصير
      أول دور بالقائمة (أو بلا دور لو القائمة فارغة).
    - role_id وحده: دور واحد فقط (نفس السلوك القديم قبل تعدد الأدوار).
    - role_ids + role_id: role_id يصير الدور الحالي (ولازم يكون ضمنها).

    يرفع ValueError إذا كان التعديل سيزيل دور super_admin عن آخر super_admin
    نشط في النظام — حماية من ترك النظام بدون أي حساب قادر على إدارته.
    """
    user = await get_user(db, user_id)
    if user is None:
        return None

    requested_ids, preferred_active = _normalize_role_selection(role_ids, role_id)

    current_roles = await _load_assigned_roles(db, user.user_id)
    before = {
        "role": user.role.name if user.role else None,
        "roles": [r.name for r in current_roles],
        "dep_id": str(user.dep_id) if user.dep_id else None,
    }

    new_roles: list | None = None
    if requested_ids is not None:
        new_roles = await _validate_system_roles(db, requested_ids)
        had_super = any(r.is_super_admin for r in current_roles)
        keeps_super = any(r.is_super_admin for r in new_roles)
        if had_super and not keeps_super:
            remaining = await _count_other_active_super_admins(db, excluding_user_id=user.user_id)
            if remaining == 0:
                raise ValueError(
                    "لا يمكن تغيير دور هذا المستخدم — إنه آخر super_admin نشط في النظام"
                )

    if first_name is not None:
        user.first_name = first_name
    if middle_name is not None:
        user.middle_name = middle_name
    if last_name is not None:
        user.last_name = last_name
    if email is not None:
        user.email = email
    if new_roles is not None:
        await _replace_user_roles(
            db,
            user=user,
            current_role_ids=[r.role_id for r in current_roles],
            new_roles=new_roles,
            preferred_active=preferred_active,
            actor_user_id=actor_user_id,
        )
    if dep_id is not None:
        user.dep_id = dep_id
    if job_title_id is not None:
        job_title = await db.get(JobTitle, job_title_id)
        if job_title is None:
            raise ValueError("المسمى الوظيفي المحدد غير موجود")
        user.job_title_id = job_title_id

    await db.flush()
    await db.refresh(user, attribute_names=["role", "job_title"])

    after_roles = new_roles if new_roles is not None else current_roles
    await audit_service.log_action(
        db,
        actor_user_id=actor_user_id,
        action_type="update",
        target_type="user",
        target_id=user.user_id,
        metadata={
            "before": before,
            "after": {
                "role": user.role.name if user.role else None,
                "roles": [r.name for r in after_roles],
            },
        },
    )

    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    result = await get_user_with_roles(db, user.user_id)
    await db.commit()
    return result


async def _replace_user_roles(
    db: AsyncSession,
    *,
    user: User,
    current_role_ids: list[uuid.UUID],
    new_roles: list,
    preferred_active: uuid.UUID | None,
    actor_user_id: uuid.UUID,
) -> None:
    """
    الهدف: استبدال أدوار مستخدم المسندة بقائمة جديدة، وضبط دوره الحالي.

    التأثيرات الجانبية: حذف صفوف user_roles المُزالة، إدراج الجديدة، وتعديل
    user.role_id — بدون commit (ضمن معاملة update_user).

    قواعد العمل:
    - الدور الحالي: preferred_active لو أُرسل، وإلا يبقى الحالي لو ما زال
      مسندًا، وإلا أول دور بالقائمة الجديدة، وإلا None (بلا دور).
    - القيد المؤجَّل users_active_role_assigned_fkey يُفحص عند COMMIT، فلا
      يهم ترتيب الحذف/الإدراج/تعديل الدور الحالي هنا.
    """
    new_ids = [r.role_id for r in new_roles]
    removed = [rid for rid in current_role_ids if rid not in new_ids]
    added = [rid for rid in new_ids if rid not in current_role_ids]

    if removed:
        await db.execute(
            delete(UserRole).where(UserRole.user_id == user.user_id, UserRole.role_id.in_(removed))
        )
    if added:
        db.add_all([UserRole(user_id=user.user_id, role_id=rid, assigned_by=actor_user_id) for rid in added])

    if preferred_active is not None:
        user.role_id = preferred_active
    elif user.role_id not in new_ids:
        user.role_id = new_ids[0] if new_ids else None


async def set_active_role(db: AsyncSession, *, user_id: uuid.UUID, role_id: uuid.UUID) -> User | None:
    """
    الهدف:
    تبديل "الدور الحالي" للمستخدم نفسه (مبدّل الأدوار بالشريط العلوي —
    تعدد الأدوار، migration 0046).

    المدخلات: user_id (المستخدم الحالي نفسه — لا يُقبل من العميل)، role_id
    (الدور المطلوب).

    المخرجات: المستخدم بشكله الكامل بعد التبديل (get_user) — أو None لو لم
    يوجد.

    التأثيرات الجانبية: تعديل users.role_id + سجل تدقيق (update، الحدث
    switch_active_role) بنفس المعاملة.

    الصلاحيات: أي مستخدم مسجَّل الدخول، على نفسه فقط، وللأدوار المسندة له
    فقط. لا يمنح أي دور جديد — مجرد اختيار بين أدواره.

    الأخطاء: ValueError لو الدور غير مسند لهذا المستخدم (قاعدة البيانات
    ترفضه أيضًا بقيد users_active_role_assigned_fkey).
    """
    user = await get_user(db, user_id)
    if user is None:
        return None

    target = await db.execute(
        select(*_ROLE_COLUMNS)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id, UserRole.role_id == role_id)
    )
    new_role = target.one_or_none()
    if new_role is None:
        raise ValueError("هذا الدور غير مسند لك")

    if user.role_id == role_id:
        return user

    from_name = user.role.name if user.role else None
    user.role_id = role_id
    await audit_service.log_action(
        db,
        actor_user_id=user.user_id,
        action_type="update",
        target_type="user",
        target_id=user.user_id,
        metadata={"event": "switch_active_role", "from": from_name, "to": new_role.name},
        # الصفة المسجَّلة = الدور الجديد بعد التبديل.
        actor_role_id=role_id,
    )
    await db.flush()
    # إعادة التحميل داخل نفس المعاملة: الدور الجديد بكل صلاحياته (نفس شكل
    # المصادقة) قبل commit — تحسين 2026-10-28 نفسه.
    db.expire(user)
    result = await get_user(db, user_id)
    await db.commit()
    return result


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

    # الأدوار المسندة وليس الدور الحالي فقط (تعدد الأدوار — migration 0046).
    if await _has_super_admin_role(db, user.user_id):
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

    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    await db.refresh(user)
    await db.commit()
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

    # الأدوار المسندة وليس الدور الحالي فقط (تعدد الأدوار — migration 0046).
    if status == UserStatus.suspended and await _has_super_admin_role(db, user.user_id):
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

    # تحسين أداء 2026-10-28: إعادة التحميل داخل نفس المعاملة قبل commit (بعد flush) بدل بعده — توفّر رحلتي BEGIN/ROLLBACK لمعاملة قراءة ثانية.
    await db.flush()
    result = await get_user(db, user.user_id)
    await db.commit()
    return result
