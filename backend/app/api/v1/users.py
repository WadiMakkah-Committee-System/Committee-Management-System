"""
الهدف:
راوتات إدارة المستخدمين — FR-UM-001 → FR-UM-006, FR-UM-021 → FR-UM-022.

قواعد الوصول:
- كل عمليات الإدارة (إنشاء/عرض/تعديل/حذف/إيقاف/تفعيل) تتطلب صلاحية
  users.* المناسبة، ثم تُطبَّق نطاق الوصول (own/department/all) الفعلي
  المسجَّل لدور المستخدم على تلك الصلاحية — راجعي مراجعة لاما 2026-08-30:
  "لا تجعل نفس صلاحية العرض تعني تلقائيًا الوصول إلى جميع مستخدمي النظام".
- استثناء واحد: GET /users/me — متاح لأي مستخدم مسجّل دخول (بلا قيد
  صلاحية) عشان يشوف بياناته الشخصية + إدارته (اسمها ووصفها) في طلب واحد،
  بدل الحاجة يستدعي endpoint الإدارات (المقيَّد بصلاحية منفصلة أصلًا).

المسؤولية:
تحويل طلبات HTTP لاستدعاءات user_service، وفرض الصلاحية عبر
core.dependencies.require_permission على مستوى كل راوت، ثم تطبيق نطاق
الوصول الفعلي (current_user.scope_for(...)) هنا قبل تمرير الفلترة/الفحص
لطبقة الخدمة — الصلاحية وحدها لا تكفي لتحديد "أي بيانات" (راجعي
core/dependencies.py لشرح الفصل بين الاثنين).
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import run_detached
from app.core.config import settings
from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.models.role import DEPARTMENT_SCOPES
from app.models.user import User, UserStatus
from app.schemas.user import ActiveRoleSwitch, UserCreate, UserDetailOut, UserOut, UserUpdate
from app.schemas.user_import import (
    ImportedDepartmentOut,
    ImportedUserOut,
    ImportPreviewAssignmentOut,
    ImportPreviewDepartmentOut,
    ImportPreviewUserOut,
    ImportRowErrorOut,
    UserImportPreview,
    UserImportResult,
)
from app.services import (
    committee_service,
    notification_service,
    user_assignment_service,
    user_import_service,
    user_service,
)
from app.services.user_assignment_service import Assignment

router = APIRouter(prefix="/users", tags=["Users"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _check_user_scope_access(current_user: User, target: User, *permission_codes: str) -> None:
    """
    تفحص أن current_user مسموح له فعليًا بالوصول لبيانات target وفق نطاق
    الوصول (own/department/all) المسجَّل لدوره على أحد permission_codes —
    وليس فقط أنه يملك الصلاحية (require_permission يفحص هذا مسبقًا).
    ترفع 403 إذا لم يكن الوصول مسموحًا بالنطاق الفعلي.
    """
    scope = current_user.scope_for(*permission_codes)
    if scope == "all":
        return
    if scope in DEPARTMENT_SCOPES:
        # department: إدارات دوره الحالي — department_tree: ومعها توابعها (0048).
        # تعدد الإدارات (0052): يكفي أن يكون target عضوًا بإحدى إدارات النطاق
        # (أساسية أو تعيين) — مدير القانونية يدير معاذ لأنه عضو بالقانونية.
        if target.member_department_ids() & current_user.department_ids_for_scope(scope):
            return
    elif scope == "own":
        if target.user_id == current_user.user_id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="ليست لديك صلاحية للوصول إلى بيانات هذا المستخدم",
    )


def _check_department_assignment(
    current_user: User, dep_id: uuid.UUID | None, *permission_codes: str
) -> None:
    """
    الهدف:
    منع إسناد مستخدم لإدارة خارج نطاق صلاحية من ينشئه/يعدّله (CLAUDE.md §10:
    لا نثق بـDepartment ID القادم من الطرف الآخر) — إصلاح ثغرة موجودة سابقًا،
    بطلب لاما 2026-11-15.

    المدخلات:
    - current_user: المنفّذ.
    - dep_id: الإدارة المطلوب إسناد المستخدم لها (None = بلا إدارة).
    - permission_codes: صلاحية العملية (users.create أو users.update).

    قواعد العمل:
    - super_admin أو نطاق all: أي إدارة (أو بلا إدارة).
    - department: إدارته فقط. department_tree: إدارته أو إحدى إداراتها التابعة.
    - own: إدارته هو فقط.
    - بغير نطاق all لا يُسمح بمستخدم بلا إدارة (يخرج عن نطاق المنفّذ كليًا).

    المخرجات: لا شيء. الأخطاء: HTTPException 403 لو الإدارة خارج النطاق.
    بلا تأثيرات جانبية.
    """
    scope = current_user.scope_for(*permission_codes)
    if current_user.is_super_admin or scope == "all":
        return
    if scope in DEPARTMENT_SCOPES:
        allowed = current_user.department_ids_for_scope(scope)
    else:
        allowed = {current_user.dep_id} if current_user.dep_id is not None else set()
    if dep_id is None or dep_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكنك إسناد المستخدم لإدارة خارج نطاق صلاحيتك",
        )


def _to_assignments(items) -> list[Assignment] | None:
    if items is None:
        return None
    return [Assignment(role_id=a.role_id, dep_id=a.dep_id) for a in items]


def _check_assignments_create(
    current_user: User, assignments: list[Assignment], primary_dep_id: uuid.UUID | None
) -> None:
    """
    إنشاء بتعيينات (migration 0052): كل إدارة بالتعيينات (والإدارة الأساسية)
    لازم تكون ضمن نطاق المنفّذ على users.create. بغير نطاق all لازم إدارة
    واحدة على الأقل (نفس قاعدة "لا مستخدم بلا إدارة" للنطاق المحدود).
    """
    deps = {a.dep_id for a in assignments if a.dep_id is not None}
    if primary_dep_id is not None:
        deps.add(primary_dep_id)
    if not deps:
        _check_department_assignment(current_user, None, "users.create")
    for dep in deps:
        _check_department_assignment(current_user, dep, "users.create")


def _merge_scoped_assignments(
    current_user: User, existing: list[Assignment], incoming: list[Assignment]
) -> list[Assignment]:
    """
    الهدف:
    تعديل تعيينات مستخدم من منفّذ نطاقه محدود (department/department_tree):
    يعدّل فقط التعيينات داخل إدارات نطاقه، وتعيينات المستخدم خارجها تبقى كما
    هي حرفيًا — فمدير القانونية لا يقدر يغيّر دور معاذ في مكتب الرئيس.

    المخرجات: القائمة النهائية = تعيينات خارج النطاق (كما هي) + الواردة داخله.
    الأخطاء: 403 لو وردت تعيينات خارج النطاق غير موجودة أصلًا (إضافة أو تغيير).
    """
    scope = current_user.scope_for("users.update")
    if current_user.is_super_admin or scope == "all":
        return incoming
    allowed = (
        current_user.department_ids_for_scope(scope)
        if scope in DEPARTMENT_SCOPES
        else ({current_user.dep_id} if current_user.dep_id is not None else set())
    )
    outside_existing = [a for a in existing if a.dep_id not in allowed]
    for a in incoming:
        if a.dep_id not in allowed and a not in outside_existing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="لا يمكنك إسناد المستخدم لإدارة خارج نطاق صلاحيتك",
            )
    inside_incoming = [a for a in incoming if a.dep_id in allowed]
    return outside_existing + inside_incoming


@router.get("/me", response_model=UserDetailOut)
async def get_my_profile(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserDetailOut:
    """
    بيانات المستخدم الحالي، بما فيها إدارته كاملة (مضمَّنة عبر
    UserOut.department) وقائمة صلاحياته الفعلية (permissions) — متاح لأي
    دور، بدون قيد RBAC، لأنه يعرض بيانات المستخدم نفسه فقط.

    صلاحيات المستخدم هنا مطلوبة للواجهة الأمامية لتقرير أي شاشات/تبويبات
    تظهر له (مثال: تبويب "الأدوار والصلاحيات" يظهر فقط لمن يملك
    is_super_admin)، دون الاعتماد على أي قائمة أدوار ثابتة في كود الفرونت.
    permission_scopes (مراجعة لاما 2026-08-31) ضرورية أيضًا لإخفاء إجراءات
    مقيَّدة بنطاق (مثال: "إرجاع لمقدّم الطلب" بطلبات تشكيل اللجان — نطاق
    department/all فقط) عن مالك الصلاحية بنطاق own وحده، بدل الاكتفاء
    بفحص "هل يملك كود الصلاحية" فقط (كان يُظهر الزر خطأً لمن يملك الصلاحية
    بنطاق own فقط — كالادمن مقدّم الطلب نفسه).

    ملاحظة تقنية: current_user يصل هنا محمَّلًا مسبقًا بعلاقة department
    (selectinload) من داخل core.dependencies.get_current_user →
    user_service.get_user، فلا حاجة لاستعلام إضافي هنا.
    """
    return await build_my_profile(db, current_user)


async def build_my_profile(db: AsyncSession, user: User) -> UserDetailOut:
    """شكل /users/me — مشترك مع رد تسجيل الدخول (auth.login) حتى يبقى
    الاثنان متطابقين دائمًا. user لازم يكون محمَّلًا بشكله الكامل
    (user_service.get_user / get_user_by_username).

    تعدد الأدوار (migration 0046): أدوار المستخدم المسندة (roles) مع صلاحيات
    كل دور (roles_permissions) تُجلب بنفس استعلام أعلام عضوية اللجان — فهذا
    المسار يبقى استعلامًا واحدًا بعد المصادقة، كما كان قبل الميزة."""
    data = UserOut.model_validate(user).model_dump()
    data["permissions"] = sorted(user.permission_codes)
    data["permission_scopes"] = user.permission_scopes
    data.update(await user_service.load_profile_extras(db, user_id=user.user_id))
    return UserDetailOut.model_validate(data)


@router.post("/me/active-role", response_model=UserDetailOut)
async def switch_my_active_role(
    payload: ActiveRoleSwitch, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserDetailOut:
    """
    POST /users/me/active-role — تبديل الدور الحالي (مبدّل الأدوار بالشريط
    العلوي؛ تعدد الأدوار — migration 0046).

    - Authentication: أي مستخدم مسجَّل الدخول.
    - Authorization: على نفسه فقط (المعرّف من التوكن، لا من الطلب)، ولدور من
      أدواره المسندة فقط — لا يمنح أي دور جديد.
    - Validation: role_id (UUID).
    - 200: بيانات المستخدم بعد التبديل (نفس شكل /users/me) — الواجهة تحدّث
      القائمة الجانبية والصلاحيات منها مباشرة بلا طلب إضافي.
    - 400: الدور غير مسند لهذا المستخدم.

    معفى من فحص رأس X-Active-Role (core.dependencies) — هو نفسه طريق تغيير
    الدور الحالي.
    """
    try:
        user = await user_service.set_active_role(db, user_id=current_user.user_id, role_id=payload.role_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return await build_my_profile(db, user)


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users.create"))],
)
async def create_user(
    payload: UserCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    """
    إنشاء مستخدم يدويًا (users.create).

    - 201: المستخدم المُنشأ.
    - 400: اسم مستخدم/بريد مكرر، أو دور/مسمى وظيفي غير صالح.
    - 403: بلا صلاحية users.create.

    التأثير الجانبي (طلب لاما 2026-11-02): بعد الإنشاء بنجاح تُرسَل بيانات
    الدخول (اسم المستخدم + كلمة المرور التي أدخلها المسؤول) لبريد المستخدم
    تلقائيًا — نفس رسالة رفع ملف المستخدمين بالضبط. كلمة المرور مؤقتة فعليًا:
    الحساب ينشأ بـmust_change_password=True فيُجبَر على تغييرها عند أول دخول
    (FR-UM-016). الإرسال عبر run_detached بعد commit، ففشل البريد لا يُفشل
    الإنشاء، ولا تُسجَّل كلمة المرور بأي سجل.

    - 403 أيضًا: الإدارة المختارة خارج نطاق صلاحية المنفّذ على users.create
      (راجعي _check_department_assignment).
    """
    assignments = _to_assignments(payload.assignments)
    if assignments is not None:
        _check_assignments_create(current_user, assignments, payload.dep_id)
    else:
        _check_department_assignment(current_user, payload.dep_id, "users.create")
    try:
        user = await user_service.create_user(
            db,
            actor_user_id=current_user.user_id,
            first_name=payload.first_name,
            middle_name=payload.middle_name,
            last_name=payload.last_name,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            role_id=payload.role_id,
            role_ids=payload.role_ids,
            dep_id=payload.dep_id,
            job_title_id=payload.job_title_id,
            status=payload.status,
            assignments=assignments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    run_detached(
        notification_service.notify_imported_users_credentials(
            [(user.email, user.first_name, user.username, payload.password)],
            login_url=settings.FRONTEND_URL.rstrip("/") + "/login" if settings.FRONTEND_URL else None,
        )
    )
    return UserOut.model_validate(user)


@router.get(
    "",
    response_model=list[UserOut],
    dependencies=[Depends(require_permission("users.view"))],
)
async def list_users(
    current_user: CurrentUser,
    dep_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    """
    عرض قائمة المستخدمين — النطاق الفعلي (own/department/all) يحدد ما
    يُعرَض، وليس امتلاك صلاحية users.view وحدها (مراجعة لاما 2026-08-30):
    - own: قائمة تحوي المستخدم نفسه فقط (لا تُرجَع قائمة كاملة تلقائيًا).
    - department: مستخدمو إدارته فقط (تجاهل أي dep_id يرسله العميل غير
      إدارته — لا نثق بفلترة قادمة من الطرف الآخر لتوسيع النطاق).
    - department_tree (migration 0048): مستخدمو إدارته وكل إداراتها التابعة؛
      فلتر dep_id يُحترم فقط لو كان ضمن هذه الإدارات، وإلا يُتجاهل.
    - all: كل المستخدمين، مع احترام فلتر dep_id الاختياري إن أُرسل.
    """
    scope = current_user.scope_for("users.view")
    if scope == "own":
        return [UserOut.model_validate(current_user)]
    if scope == "department":
        # إدارات دوره الحالي (migration 0052 — قد تكون أكثر من إدارة).
        allowed = current_user.department_ids_for_scope(scope)
        if not allowed:
            return []
        users = await user_service.list_users(db, dep_ids=allowed)
        return [UserOut.model_validate(u) for u in users]
    if scope == "department_tree":
        allowed = current_user.department_ids_for_scope(scope)
        if not allowed:
            return []
        if dep_id is not None and dep_id in allowed:
            users = await user_service.list_users(db, dep_id=dep_id)
        else:
            users = await user_service.list_users(db, dep_ids=allowed)
        return [UserOut.model_validate(u) for u in users]
    if scope == "all":
        users = await user_service.list_users(db, dep_id=dep_id)
        return [UserOut.model_validate(u) for u in users]
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="ليست لديك صلاحية للقيام بهذا الإجراء",
    )


@router.get(
    "/import/template",
    dependencies=[Depends(require_permission("users.import"))],
)
async def download_import_template(db: AsyncSession = Depends(get_db)) -> Response:
    """
    GET /users/import/template — يتطلب users.import.

    نموذج Excel فارغ بأعمدة رفع الملف، بقوائم منسدلة محدثة من النظام
    (الأدوار، المسميات الوظيفية) وشيت مرجعي بالإدارات الحالية.
    مُعرَّف قبل /{user_id} عمدًا حتى لا يُفسَّر "import" كمعرّف مستخدم.
    """
    content = await user_import_service.build_template(db)
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote("نموذج_بيانات_المستخدمين.xlsx")},
    )


async def _read_import_rows(file: UploadFile) -> list:
    """قراءة الملف المرفوع والتحقق من صيغته وحجمه وبنيته — مشتركة بين المعاينة والرفع."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="الملف يجب أن يكون بصيغة Excel ‏(.xlsx)")
    content = await file.read(user_import_service.MAX_FILE_BYTES + 1)
    if len(content) > user_import_service.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="حجم الملف أكبر من 2 ميجابايت")
    try:
        return user_import_service.parse_workbook(content)
    except user_import_service.ImportFileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _row_errors_http(exc: "user_import_service.ImportValidationError") -> HTTPException:
    return HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail={
            "message": f"لم يُضف أي مستخدم — الملف يحتوي {len(exc.errors)} خطأ، صحّحيها وأعيدي الرفع",
            "errors": [ImportRowErrorOut(**vars(e)).model_dump() for e in exc.errors],
        },
    )


@router.post(
    "/import/preview",
    response_model=UserImportPreview,
    dependencies=[Depends(require_permission("users.import"))],
)
async def preview_import_users(
    current_user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> UserImportPreview:
    """
    POST /users/import/preview (multipart: file) — يتطلب users.import.

    نفس تحقق POST /users/import بالكامل، لكن بلا أي كتابة: يرجع ملخص ما
    سيُنشأ (المستخدمون وتعييناتهم، الإدارات الجديدة وأمهاتها، المسميات
    الجديدة) لتأكيده قبل الرفع الفعلي (طلب لاما 2026-11-22).

    الاستجابات: 200 ملخص، و400/413 بنفس أشكال POST /users/import.
    """
    rows = await _read_import_rows(file)
    try:
        plan = await user_import_service.preview_import(db, actor=current_user, rows=rows)
    except user_import_service.ImportFileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except user_import_service.ImportValidationError as exc:
        raise _row_errors_http(exc) from exc
    return UserImportPreview(
        users_count=len(plan.users),
        assignments_count=plan.assignments_count,
        users=[
            ImportPreviewUserOut(
                row=u.row,
                full_name=u.full_name,
                email=u.email,
                primary_department=u.primary_department,
                assignments=[ImportPreviewAssignmentOut(department=d, role=r) for d, r in u.assignments],
            )
            for u in plan.users
        ],
        departments_to_create=[
            ImportPreviewDepartmentOut(name=n, parent_name=p) for n, p in plan.departments_to_create
        ],
        job_titles_to_create=plan.job_titles_to_create,
    )


@router.post(
    "/import",
    response_model=UserImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users.import"))],
)
async def import_users(
    current_user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> UserImportResult:
    """
    POST /users/import (multipart: file) — يتطلب users.import.

    ينشئ المستخدمين من ملف Excel (الكل أو لا شيء)، ويولّد لكل واحد اسم
    مستخدم وكلمة مرور مؤقتة، ثم يرسل بيانات الدخول لبريد كل مستخدم برسالة
    منفصلة (run_detached بعد الـcommit — الاستجابة لا تنتظر المزوّد).
    نطاق الصلاحية (all/غيره) يُطبَّق داخل user_import_service.import_users.

    الاستجابات:
    - 201: UserImportResult (بدون كلمات المرور).
    - 400: خطأ بالملف ككل — detail نص.
    - 400: أخطاء بالصفوف — detail = {"message": ..., "errors": [ImportRowErrorOut]}.
    - 409: تعارض متزامن (أُنشئ نفس البريد/الاسم أثناء الرفع) — أعيدي المحاولة.
    - 413: الملف أكبر من الحد.
    """
    rows = await _read_import_rows(file)
    try:
        result = await user_import_service.import_users(db, actor=current_user, rows=rows)
    except user_import_service.ImportFileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except user_import_service.ImportValidationError as exc:
        raise _row_errors_http(exc) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="تعارض مع بيانات أُضيفت للتو (بريد أو اسم مستخدم) — لم يُضف أحد، أعيدي رفع الملف",
        ) from exc

    run_detached(
        notification_service.notify_imported_users_credentials(
            [(u.email, u.first_name, u.username, u.temporary_password) for u in result.users],
            login_url=settings.FRONTEND_URL.rstrip("/") + "/login" if settings.FRONTEND_URL else None,
        )
    )

    return UserImportResult(
        created_count=len(result.users),
        users=[
            ImportedUserOut(
                row=u.row,
                user_id=u.user_id,
                full_name=u.full_name,
                email=u.email,
                username=u.username,
                department=u.department,
                role=u.role,
                is_department_manager=u.is_department_manager,
            )
            for u in result.users
        ],
        departments_created=[
            ImportedDepartmentOut(name=n, code=c, parent_name=result.departments_parents.get(n))
            for n, c in result.departments_created
        ],
        job_titles_created=result.job_titles_created,
        emails_queued=len(result.users),
        assignments_count=result.assignments_count,
    )


@router.get(
    "/{user_id}",
    response_model=UserDetailOut,
    dependencies=[Depends(require_permission("users.view"))],
)
async def get_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserDetailOut:
    # مع كل أدواره المسندة (UserOut.roles) — تعدد الأدوار، migration 0046.
    user = await user_service.get_user_with_roles(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    _check_user_scope_access(current_user, user, "users.view")
    data = UserOut.model_validate(user).model_dump()
    data["permissions"] = sorted(user.permission_codes)
    data["permission_scopes"] = user.permission_scopes
    data["has_committee_membership_access"] = await committee_service.user_has_committee_role_view_access(
        db, user_id=user.user_id
    )
    data["has_any_committee_membership"] = await committee_service.user_has_any_committee_membership(
        db, user_id=user.user_id
    )
    data["has_committee_documents_view_access"] = (
        await committee_service.user_has_committee_role_documents_view_access(
            db, user_id=user.user_id
        )
    )
    return UserDetailOut.model_validate(data)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_permission("users.update"))],
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    target = await user_service.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    _check_user_scope_access(current_user, target, "users.update")
    # نقل المستخدم لإدارة أخرى: الإدارة الجديدة لازم تكون ضمن نطاق المنفّذ
    # أيضًا (وليس فقط إدارته الحالية). update_user يتجاهل dep_id = None.
    if payload.dep_id is not None and payload.dep_id != target.dep_id:
        _check_department_assignment(current_user, payload.dep_id, "users.update")
    assignments = _to_assignments(payload.assignments)
    if assignments is not None:
        existing = await user_assignment_service.load_assignments(db, target.user_id)
        assignments = _merge_scoped_assignments(current_user, existing, assignments)
    try:
        user = await user_service.update_user(
            db,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            first_name=payload.first_name,
            middle_name=payload.middle_name,
            last_name=payload.last_name,
            email=payload.email,
            role_id=payload.role_id,
            role_ids=payload.role_ids,
            dep_id=payload.dep_id,
            job_title_id=payload.job_title_id,
            assignments=assignments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users.delete"))],
)
async def delete_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    target = await user_service.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    _check_user_scope_access(current_user, target, "users.delete")
    try:
        user = await user_service.soft_delete_user(
            db, actor_user_id=current_user.user_id, user_id=user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")


@router.post(
    "/{user_id}/suspend",
    response_model=UserOut,
    dependencies=[Depends(require_permission("users.suspend"))],
)
async def suspend_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    """إيقاف حساب مؤقتًا — FR-UM-004 (يمنع تسجيل الدخول فقط)."""
    target = await user_service.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    _check_user_scope_access(current_user, target, "users.suspend")
    try:
        user = await user_service.set_user_status(
            db, actor_user_id=current_user.user_id, user_id=user_id, status=UserStatus.suspended
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)


@router.post(
    "/{user_id}/reactivate",
    response_model=UserOut,
    dependencies=[Depends(require_permission("users.reactivate"))],
)
async def reactivate_user(
    user_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserOut:
    target = await user_service.get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    _check_user_scope_access(current_user, target, "users.reactivate")
    user = await user_service.set_user_status(
        db, actor_user_id=current_user.user_id, user_id=user_id, status=UserStatus.active
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="المستخدم غير موجود")
    return UserOut.model_validate(user)
