"""
الهدف:
رفع ملف المستخدمين (users.import — طلب لاما 2026-11-01): إنشاء عدة مستخدمين
دفعة واحدة من ملف Excel بنفس أعمدة "نموذج_بيانات_المستخدمين.xlsx"، مع توليد
اسم مستخدم وكلمة مرور مؤقتة لكل واحد (تُرسَل لبريده من طبقة الـAPI).

المسؤولية:
- parse_workbook(): قراءة الملف والتحقق من بنيته (الأعمدة، الحد الأقصى للصفوف).
- import_users(): التحقق من كل الصفوف أولًا، ثم الإنشاء بمعاملة واحدة.
- build_template(): توليد نموذج فارغ بقوائم منسدلة من بيانات النظام الحالية.

قواعد العمل (قرارات لاما 2026-11-01، ومحدّثة 2026-11-22 — migration 0052):
- صف لكل تعيين (إدارة + دور)، والصفوف بنفس البريد = مستخدم واحد. التفاصيل
  الكاملة بـ_validate.
- الكل أو لا شيء: أي خطأ بأي صف ← لا يُنشأ أحد، وتُرجَع كل الأخطاء برقم الصف.
- الحقول الإلزامية: الاسم الأول/الأوسط/العائلة + البريد.
- الدور: أسماء النموذج تُقابَل بأدوار النظام (ROLE_ALIASES)، وأي اسم/وصف دور
  نظامي آخر يُقبل كما هو. دور المسؤول الأعلى وأدوار اللجان لا تُسند أبدًا.
- المسمى الوظيفي غير الموجود يُضاف تلقائيًا — لمن يملك نطاق 'all' أو
  job_titles.create فقط.
- الإدارة غير الموجودة تُنشأ تلقائيًا (نطاق all فقط) برمز DEP-001...، تحت
  الإدارة الأم المكتوبة لو وُجدت، ومديرها صاحب صف «مدير إدارة (أدمن)» بها.
- preview_import(): نفس التحقق بلا كتابة — ملخص للتأكيد قبل الإنشاء.
- النموذج القديم (7 أعمدة، صف لكل مستخدم) ما زال مقبولًا.
- الحد الأقصى MAX_ROWS صفًا وMAX_USERS مستخدمًا (حد Brevo المجاني 300 بريد/يوم).

الصلاحيات (مفروضة هنا لا بالواجهة):
- نطاق 'all' على users.import: أي إدارة، وإنشاء إدارات جديدة.
- أي نطاق آخر: إدارات نطاق المُستورِد فقط (الفارغ = إدارته الأساسية)، بلا إنشاء إدارات،
  ولا إسناد دور يملك صلاحيات ليست لدى المُستورِد نفسه (منع تصعيد الصلاحيات).
"""

from __future__ import annotations

import asyncio
import io
import re
import secrets
import uuid
import zipfile
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.role import Role
from app.models.user_department_role import UserDepartmentRole
from app.models.user_role import UserRole
from app.models.user import User, UserStatus
from app.services import audit_service

SHEET_NAME = "المستخدمين"
LISTS_SHEET_NAME = "القوائم"
# تعدد الإدارات (migration 0052 — قرار لاما 2026-11-22): صف لكل تعيين
# (إدارة + دور)، والبريد يتكرر بعدد إدارات الشخص — كل الصفوف بنفس البريد =
# مستخدم واحد.
TEMPLATE_HEADERS = [
    "الاسم الأول",
    "الاسم الأوسط",
    "اسم العائلة",
    "البريد الإلكتروني",
    "المسمى الوظيفي",
    "الإدارة الأم",
    "الإدارة",
    "الدور في الإدارة",
    "الإدارة الأساسية",
]
# النموذج القديم (قبل 0052) — يبقى مقبولًا: صف واحد لكل مستخدم، بلا إدارة أم.
LEGACY_TEMPLATE_HEADERS = [
    "الاسم الأول",
    "الاسم الأوسط",
    "اسم العائلة",
    "البريد الإلكتروني",
    "الإدارة",
    "المسمى الوظيفي",
    "الدور في النظام",
]
PRIMARY_YES = "نعم"
# صفوف الملف (تعيينات) والمستخدمون (بريد مختلف) — الحد الثاني لحد Brevo
# المجاني (300 بريد/يوم).
MAX_ROWS = 400
MAX_USERS = 200
MAX_FILE_BYTES = 2 * 1024 * 1024

# أسماء الأدوار كما تظهر بنموذج لاما ← أسماء الأدوار المقابلة بقاعدة البيانات
# (أول اسم موجود فعليًا يُعتمد). "ادمن" هو الاسم الحالي بالإنتاج لدور
# admin النظامي (أُعيدت تسميته من الشاشة) — نقبل الاثنين.
ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "الرئيس التنفيذي": ("executive_president",),
    "المكتب التنفيذي": ("executive_office_manager", "مدير المكتب التنفيذي"),
    "مدير إدارة (أدمن)": ("ادمن", "admin", "مسؤول إدارة"),
    "مستخدم نظام": ("مستخدم نظام",),
}
# من يُسند له دور "مدير إدارة (أدمن)" (أيًّا كان اسمه الحالي بالنظام — يُحدَّد
# عبر _resolve_role نفسها، فيبقى صحيحًا لو أُعيدت تسمية الدور) وله إدارة
# بالملف يصبح مديرها.
MANAGER_ROLE_LABEL = "مدير إدارة (أدمن)"

_NAME_MAX = 100
_DEPARTMENT_NAME_MAX = 150
_JOB_TITLE_MAX = 150
_USERNAME_MIN = 3
_USERNAME_MAX = 50
_TEMP_PASSWORD_LENGTH = 12
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_LOWER = "abcdefghijkmnpqrstuvwxyz"
_DIGITS = "23456789"
_DEPARTMENT_CODE_RE = re.compile(r"^DEP-(\d+)$", re.IGNORECASE)


class ImportFileError(Exception):
    """خطأ بالملف ككل (ليس Excel، أعمدة خاطئة، فارغ، صفوف أكثر من الحد)."""


@dataclass
class RowError:
    row: int
    field: str | None
    message: str


class ImportValidationError(Exception):
    """صف واحد أو أكثر غير صالح — لا يُنشأ أي مستخدم."""

    def __init__(self, errors: list[RowError]):
        super().__init__("الملف يحتوي أخطاء")
        self.errors = errors


@dataclass
class ParsedRow:
    row: int
    first_name: str
    middle_name: str
    last_name: str
    email: str
    job_title: str
    parent_department: str
    department: str
    role: str
    primary: str = ""


@dataclass
class CreatedUser:
    row: int
    user_id: uuid.UUID
    full_name: str
    first_name: str
    email: str
    username: str
    department: str | None
    role: str | None
    is_department_manager: bool
    # كلمة المرور المؤقتة الصريحة — لإرسالها بالبريد فقط، لا تُرجَع بالـAPI.
    temporary_password: str = field(repr=False)


@dataclass
class ImportResult:
    users: list[CreatedUser]
    departments_created: list[tuple[str, str]]  # (الاسم، الرمز)
    job_titles_created: list[str] = field(default_factory=list)
    assignments_count: int = 0
    # الإدارات الجديدة → اسم إدارتها الأم (None = بالمستوى الأعلى).
    departments_parents: dict[str, str | None] = field(default_factory=dict)


@dataclass
class ImportPlanUser:
    row: int
    full_name: str
    email: str
    primary_department: str | None
    assignments: list[tuple[str | None, str | None]]  # (الإدارة، الدور)


@dataclass
class ImportPlan:
    """ملخص ما سيُنشأ (معاينة قبل التأكيد — لا يُكتب شيء)."""

    users: list[ImportPlanUser]
    departments_to_create: list[tuple[str, str | None]]  # (الاسم، الإدارة الأم)
    job_titles_to_create: list[str]
    assignments_count: int


# --------------------------------------------------------------------------
# قراءة الملف
# --------------------------------------------------------------------------


def _cell_text(value: object) -> str:
    """تحويل قيمة خلية لنص مُشذَّب (الأرقام الصحيحة بدون .0)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def parse_workbook(content: bytes) -> list[ParsedRow]:
    """
    الهدف: قراءة ملف Excel المرفوع وتحويل صفوفه لقائمة ParsedRow.

    المدخلات: content — bytes الملف (.xlsx).
    المخرجات: list[ParsedRow] — الصفوف غير الفارغة، برقم صفها الفعلي بالملف.
    الأخطاء: ImportFileError — ملف غير صالح، شيت/أعمدة غير مطابقة للنموذج،
    ملف بلا مستخدمين، أو أكثر من MAX_ROWS صفًا.
    ملاحظة: يقرأ شيت "المستخدمين" إن وُجد وإلا الشيت الأول، ويتجاهل أي
    شيت آخر (مثل "اللجان الدائمة" — خارج نطاق هذه الميزة بقرار لاما).
    """
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ImportFileError("الملف ليس ملف Excel صالحًا — استخدمي صيغة .xlsx من النموذج") from exc

    try:
        sheet = workbook[SHEET_NAME] if SHEET_NAME in workbook.sheetnames else workbook.worksheets[0]
        rows_iter = sheet.iter_rows(values_only=True)
        header = next(rows_iter, None)
        header_all = [_cell_text(v) for v in (header or ())]
        if header_all[: len(TEMPLATE_HEADERS)] == TEMPLATE_HEADERS:
            width, legacy = len(TEMPLATE_HEADERS), False
        elif header_all[: len(LEGACY_TEMPLATE_HEADERS)] == LEGACY_TEMPLATE_HEADERS:
            width, legacy = len(LEGACY_TEMPLATE_HEADERS), True
        else:
            raise ImportFileError(
                "أعمدة الملف لا تطابق النموذج. الأعمدة المطلوبة بالترتيب: " + "، ".join(TEMPLATE_HEADERS)
            )

        parsed: list[ParsedRow] = []
        for index, values in enumerate(rows_iter, start=2):
            cells = [_cell_text(v) for v in (values or ())][:width]
            cells += [""] * (width - len(cells))
            if not any(cells):
                continue
            if len(parsed) >= MAX_ROWS:
                raise ImportFileError(f"الحد الأقصى {MAX_ROWS} صف لكل ملف — قسّمي الملف لأكثر من ملف")
            if legacy:
                first, middle, last, email, department, job_title, role = cells
                parsed.append(ParsedRow(index, first, middle, last, email, job_title, "", department, role, ""))
            else:
                parsed.append(ParsedRow(index, *cells))
    finally:
        workbook.close()

    if not parsed:
        raise ImportFileError("الملف لا يحتوي أي مستخدمين تحت صف العناوين")
    return parsed


# --------------------------------------------------------------------------
# بيانات الدخول
# --------------------------------------------------------------------------


def username_base_from_email(email: str) -> str:
    """
    الهدف: اسم مستخدم أساسي من البريد — نفس قواعد suggestUsernameFromEmail
    بالواجهة (frontend/src/lib/credentialSuggestions.ts) حتى يكون شكل الأسماء
    موحّدًا بين الإضافة اليدوية والرفع: الجزء قبل @ بلا وسم "+"، أحرف إنجليزية
    صغيرة وأرقام و"." و"_" فقط. لو الناتج أقصر من 3 أحرف يُرجع "user".
    """
    local = email.strip().split("@")[0].split("+")[0].lower()
    base = re.sub(r"[^a-z0-9_.]", "_", local)
    base = re.sub(r"([._])[._]+", r"\1", base).strip("._")
    base = base[:_USERNAME_MAX].rstrip("._")
    return base if len(base) >= _USERNAME_MIN else "user"


def unique_username(base: str, taken: set[str]) -> str:
    """
    الهدف: أول اسم غير مأخوذ من base، base2، base3... (بحد 50 حرفًا).
    التأثيرات الجانبية: يضيف الاسم المختار إلى taken (لتفادي التكرار داخل الملف).
    """
    candidate = base
    counter = 2
    while candidate in taken:
        suffix = str(counter)
        candidate = f"{base[: _USERNAME_MAX - len(suffix)]}{suffix}"
        counter += 1
    taken.add(candidate)
    return candidate


def generate_temporary_password() -> str:
    """
    الهدف: كلمة مرور مؤقتة عشوائية آمنة (secrets) تحقق سياسة FR-UM-015:
    12 حرفًا تضم حرفًا كبيرًا وصغيرًا ورقمًا على الأقل، بلا أحرف ملتبسة
    (O/0، l/1/I) — نفس مجموعة أحرف generateTemporaryPassword بالواجهة.
    """
    alphabet = _UPPER + _LOWER + _DIGITS
    chars = [secrets.choice(_UPPER), secrets.choice(_LOWER), secrets.choice(_DIGITS)]
    chars += [secrets.choice(alphabet) for _ in range(_TEMP_PASSWORD_LENGTH - len(chars))]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


# كلمة المرور الأولية الموحّدة لكل المستوردين من Excel — مؤقت لمرحلة ما قبل
# التدشين فقط (طلب الإدارة 2026-11-15). تطابق سياسة FR-UM-015 (8 أحرف + حرف
# كبير + حرف صغير + رقم)، والحساب يُنشأ بـmust_change_password=True فيُجبَر
# صاحبه على تغييرها عند أول دخول. نفس القيمة PRELAUNCH_INITIAL_PASSWORD
# بالواجهة (frontend/src/lib/credentialSuggestions.ts).
# يوم التدشين: احذف هذا الثابت وأرجع import_users لـ generate_temporary_password().
PRELAUNCH_INITIAL_PASSWORD = "Wa123456"


# --------------------------------------------------------------------------
# مطابقة الأدوار
# --------------------------------------------------------------------------


def _key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _assignable_roles(roles: list[Role]) -> list[Role]:
    """الأدوار النظامية القابلة للإسناد عبر الملف (بدون المسؤول الأعلى وأدوار اللجان)."""
    return [r for r in roles if r.kind != "committee" and not r.is_super_admin]


def _resolve_role(label: str, roles: list[Role]) -> Role | None:
    """
    الهدف: إيجاد الدور المقصود بنص عمود "الدور في النظام".
    الترتيب: أسماء النموذج (ROLE_ALIASES) ← اسم الدور ← وصف الدور (لو
    طابق دورًا واحدًا فقط). يُرجع None لو لم يُعثر على تطابق واحد مؤكد.

    إصلاح 2026-11-01 (لاما أعادت تسمية executive_office_manager إلى "المكتب
    التنفيذي" من شاشة الأدوار): لو اسم النموذج لا يجد أسماءه البرمجية
    المتوقعة (الدور أُعيدت تسميته)، نكمل البحث بالاسم ثم الوصف بدل الرفض —
    فيعمل الرفع قبل إعادة التسمية وبعدها.
    """
    by_name = {_key(r.name): r for r in roles}

    def by_description(text: str) -> Role | None:
        matches = [r for r in roles if r.description and _key(r.description) == _key(text)]
        return matches[0] if len(matches) == 1 else None

    for alias, names in ROLE_ALIASES.items():
        if _key(alias) == _key(label):
            for name in names:
                if _key(name) in by_name:
                    return by_name[_key(name)]
            for name in names:
                if (role := by_description(name)) is not None:
                    return role
            break
    if _key(label) in by_name:
        return by_name[_key(label)]
    return by_description(label)


def role_choices(roles: list[Role]) -> list[str]:
    """
    الهدف: قائمة القيم المسموحة بعمود الدور (للنموذج ولرسائل الخطأ): أسماء
    النموذج الأربعة المتوفرة فعليًا بهذا النظام + أسماء بقية الأدوار القابلة
    للإسناد التي لا يغطيها اسم من النموذج.
    """
    assignable = _assignable_roles(roles)
    choices: list[str] = []
    covered: set[uuid.UUID] = set()
    for alias in ROLE_ALIASES:
        role = _resolve_role(alias, assignable)
        if role is not None:
            choices.append(alias)
            covered.add(role.role_id)
    choices += sorted(r.name for r in assignable if r.role_id not in covered)
    return choices


# --------------------------------------------------------------------------
# الاستيراد
# --------------------------------------------------------------------------


async def _next_department_codes(db: AsyncSession, count: int) -> list[str]:
    """رموز تلقائية DEP-001... تبدأ بعد أكبر رمز DEP-n مستخدم حاليًا (ولو لإدارة محذوفة)."""
    result = await db.execute(select(Department.code).where(Department.code.ilike("DEP-%")))
    numbers = [int(m.group(1)) for (code,) in result.all() if code and (m := _DEPARTMENT_CODE_RE.match(code))]
    start = max(numbers, default=0) + 1
    return [f"DEP-{n:03d}" for n in range(start, start + count)]


@dataclass
class _Person:
    """كل صفوف البريد الواحد — مستخدم واحد بعدة تعيينات."""

    rows: list[ParsedRow]
    email: str
    # (الصف، الدور، مفتاح الإدارة) لكل صف صالح.
    assignments: list[tuple[ParsedRow, Role | None, str | None]] = field(default_factory=list)
    job_title_key: str | None = None
    primary_key: str | None = None


async def _validate(db: AsyncSession, *, actor: User, rows: list[ParsedRow]):
    """
    الهدف:
    التحقق من كل صفوف الملف (بدون أي كتابة) وبناء خطة الإنشاء — مشتركة بين
    المعاينة (preview_import) والإنشاء الفعلي (import_users).

    المخرجات: (people, departments, job_titles, new_departments, new_job_titles,
    managers, roles) — أو ImportValidationError بكل الأخطاء.

    قواعد العمل (قرارات لاما 2026-11-22، migration 0052):
    - صف لكل تعيين؛ الصفوف بنفس البريد = مستخدم واحد. الاسم الثلاثي والمسمى
      الوظيفي لازم يتطابقون بكل صفوفه (المسمى الفارغ بصف = غير محدد فيه).
    - البريد المسجّل مسبقًا بالنظام يُرفض (الملف لا يعدّل حسابات قائمة).
    - تكرار نفس (البريد، الإدارة، الدور) خطأ.
    - "الإدارة الأساسية": «نعم» بصف واحد على الأكثر لكل شخص؛ بلا «نعم» تكون
      إدارة أول صف له.
    - الدور الفارغ مسموح فقط لشخص بصف واحد (عضو بالإدارة بلا دور).
    - الإدارة الأم (اختيارية): لازم تكون موجودة وبالمستوى الأعلى — الملف لا
      ينشئ إدارات أم أبدًا. إدارة موجودة: أمها الفعلية لازم تطابق المكتوبة.
      إدارة جديدة (نطاق all فقط): تُنشأ تحت الأم المكتوبة، وبإدارة أم واحدة
      بكل الملف، وتحتاج صف مدير.
    - الإدارة الأم بلا إدارة بالصف: خطأ (الموظف التابع للأم مباشرة تُكتب أمه
      بعمود "الإدارة").
    - مدير الإدارة: صف دوره «مدير إدارة (أدمن)» — واحد لكل إدارة بالملف،
      والإدارة الموجودة اللي لها مدير لا يُغيَّر مديرها من الملف.
    - بغير نطاق all: إدارات نطاق المُستورِد فقط، الفارغ = إدارته الأساسية،
      بلا إنشاء إدارات، وبلا إسناد دور يتجاوز صلاحياته.
    """
    import_scope = actor.scope_for("users.import")
    full_scope = import_scope == "all"
    # الإدارات المسموح الرفع لها بدون نطاق all: إدارات دوره الحالي، أو هي
    # وما تحتها لنطاق department_tree (migration 0048/0052).
    allowed_dep_ids = actor.department_ids_for_scope(
        "department_tree" if import_scope == "department_tree" else "department"
    )
    actor_permissions = actor.permission_codes
    if not full_scope and not allowed_dep_ids:
        raise ImportFileError("حسابك غير مرتبط بإدارة — لا يمكنك رفع مستخدمين إلا لإدارتك")

    emails_in_file = {r.email.casefold() for r in rows if r.email}
    roles = _assignable_roles(list((await db.execute(select(Role))).scalars().all()))
    manager_role = _resolve_role(MANAGER_ROLE_LABEL, roles)
    job_titles = {_key(j.name): j for j in (await db.execute(select(JobTitle))).scalars().all()}
    departments = {
        _key(d.name): d
        for d in (await db.execute(select(Department).where(Department.deleted_at.is_(None)))).scalars().all()
    }
    departments_by_id = {d.dep_id: d for d in departments.values()}
    existing_emails = set(
        (
            await db.execute(
                select(func.lower(User.email)).where(
                    User.deleted_at.is_(None), func.lower(User.email).in_(emails_in_file or {""})
                )
            )
        ).scalars()
    )

    errors: list[RowError] = []
    can_create_job_titles = full_scope or "job_titles.create" in actor_permissions
    new_job_titles: dict[str, str] = {}  # key → الاسم كما كُتب أول مرة
    new_departments: dict[str, str] = {}  # key → الاسم كما كُتب أول مرة
    new_department_parent: dict[str, tuple[str | None, int]] = {}  # key → (key الأم، أول صف)
    managers: dict[str, int] = {}  # key الإدارة → رقم صف مديرها بالملف
    department_first_row: dict[str, int] = {}
    people: dict[str, _Person] = {}

    for row in rows:
        row_errors: list[RowError] = []

        for value, field_name in (
            (row.first_name, "الاسم الأول"),
            (row.middle_name, "الاسم الأوسط"),
            (row.last_name, "اسم العائلة"),
        ):
            if not value:
                row_errors.append(RowError(row.row, field_name, f"{field_name} مطلوب"))
            elif len(value) > _NAME_MAX:
                row_errors.append(RowError(row.row, field_name, f"{field_name} أطول من {_NAME_MAX} حرف"))

        email = ""
        if not row.email:
            row_errors.append(RowError(row.row, "البريد الإلكتروني", "البريد الإلكتروني مطلوب"))
        else:
            try:
                email = validate_email(row.email, check_deliverability=False).normalized
            except EmailNotValidError:
                row_errors.append(RowError(row.row, "البريد الإلكتروني", f"صيغة البريد غير صحيحة: {row.email}"))
            else:
                if email.casefold() in existing_emails:
                    row_errors.append(
                        RowError(row.row, "البريد الإلكتروني", "البريد مسجّل مسبقًا لمستخدم آخر بالنظام")
                    )

        role: Role | None = None
        if row.role:
            role = _resolve_role(row.role, roles)
            if role is None:
                row_errors.append(
                    RowError(
                        row.row,
                        "الدور في الإدارة",
                        f"الدور «{row.role}» غير موجود. القيم المسموحة: " + "، ".join(role_choices(roles)),
                    )
                )
            elif not full_scope and not role.permission_codes <= actor_permissions:
                row_errors.append(
                    RowError(row.row, "الدور في الإدارة", f"لا تملك صلاحية إسناد الدور «{row.role}»")
                )

        job_title_key: str | None = None
        if row.job_title:
            job_title_key = _key(row.job_title)
            if len(row.job_title) > _JOB_TITLE_MAX:
                row_errors.append(
                    RowError(row.row, "المسمى الوظيفي", f"المسمى الوظيفي أطول من {_JOB_TITLE_MAX} حرف")
                )
            elif job_title_key not in job_titles:
                if can_create_job_titles:
                    new_job_titles.setdefault(job_title_key, row.job_title)
                else:
                    row_errors.append(
                        RowError(
                            row.row,
                            "المسمى الوظيفي",
                            f"المسمى «{row.job_title}» غير موجود، ولا تملك صلاحية إضافة مسميات وظيفية",
                        )
                    )

        # ---- الإدارة الأم ----
        parent_key: str | None = None
        parent_ok = True
        if row.parent_department:
            parent = departments.get(_key(row.parent_department))
            if parent is None:
                parent_ok = False
                row_errors.append(
                    RowError(
                        row.row,
                        "الإدارة الأم",
                        f"الإدارة الأم «{row.parent_department}» غير موجودة — الإدارات الأم تُنشأ من المنصة",
                    )
                )
            elif parent.parent_dep_id is not None:
                parent_ok = False
                row_errors.append(
                    RowError(
                        row.row,
                        "الإدارة الأم",
                        f"«{parent.name}» إدارة تابعة وليست أمًّا — الهيكل مستويان فقط",
                    )
                )
            else:
                parent_key = _key(parent.name)
            if not row.department:
                parent_ok = False
                row_errors.append(
                    RowError(
                        row.row,
                        "الإدارة",
                        "الإدارة مطلوبة مع الإدارة الأم — لو الموظف تابع للأم مباشرة اكتبيها بعمود الإدارة",
                    )
                )

        # ---- الإدارة ----
        department_key: str | None = None
        if row.department:
            department_key = _key(row.department)
            existing_department = departments.get(department_key)
            if len(row.department) > _DEPARTMENT_NAME_MAX:
                row_errors.append(RowError(row.row, "الإدارة", f"اسم الإدارة أطول من {_DEPARTMENT_NAME_MAX} حرف"))
            elif existing_department is not None:
                if parent_ok and row.parent_department:
                    actual_parent = departments_by_id.get(existing_department.parent_dep_id)
                    if actual_parent is None or _key(actual_parent.name) != parent_key:
                        actual = f"«{actual_parent.name}»" if actual_parent else "بلا إدارة أم"
                        row_errors.append(
                            RowError(
                                row.row,
                                "الإدارة الأم",
                                f"الإدارة «{existing_department.name}» إدارتها الأم بالنظام {actual}، "
                                f"وليست «{row.parent_department}»",
                            )
                        )
            elif not full_scope:
                row_errors.append(
                    RowError(row.row, "الإدارة", f"الإدارة «{row.department}» غير موجودة، ولا تملك صلاحية إنشاء إدارات")
                )
            elif parent_ok:
                new_departments.setdefault(department_key, row.department)
                previous = new_department_parent.setdefault(department_key, (parent_key, row.row))
                if previous[0] != parent_key:
                    row_errors.append(
                        RowError(
                            row.row,
                            "الإدارة الأم",
                            f"الإدارة الجديدة «{row.department}» مكتوبة تحت إدارة أم مختلفة بالصف {previous[1]}",
                        )
                    )
        elif not full_scope and actor.department is not None:
            department_key = _key(actor.department.name)

        if not full_scope and department_key is not None and not any(e.field == "الإدارة" for e in row_errors):
            target = departments.get(department_key)
            if target is None or target.dep_id not in allowed_dep_ids:
                message = (
                    "يمكنك إضافة مستخدمين لإدارتك أو الإدارات التابعة لها فقط"
                    if import_scope == "department_tree"
                    else "يمكنك إضافة مستخدمين لإدارتك فقط"
                )
                row_errors.append(RowError(row.row, "الإدارة", message))

        if row.primary and row.primary != PRIMARY_YES:
            row_errors.append(
                RowError(row.row, "الإدارة الأساسية", f"القيمة المسموحة «{PRIMARY_YES}» أو اتركيها فارغة")
            )

        if department_key is not None:
            department_first_row.setdefault(department_key, row.row)
            if role is not None and manager_role is not None and role.role_id == manager_role.role_id:
                existing = departments.get(department_key)
                if department_key in managers:
                    row_errors.append(
                        RowError(row.row, "الدور في الإدارة", f"للإدارة مدير آخر بالملف (الصف {managers[department_key]})")
                    )
                elif existing is not None and existing.manager_user_id is not None:
                    row_errors.append(
                        RowError(
                            row.row,
                            "الدور في الإدارة",
                            f"الإدارة «{existing.name}» لها مدير — تغيير المدير يتم من صفحة الإدارات",
                        )
                    )
                else:
                    managers[department_key] = row.row

        errors += row_errors
        if email:
            person = people.setdefault(email.casefold(), _Person(rows=[], email=email))
            person.rows.append(row)
            if not row_errors:
                person.assignments.append((row, role, department_key))
                if job_title_key:
                    person.job_title_key = person.job_title_key or job_title_key

    if len(people) > MAX_USERS:
        raise ImportFileError(f"الحد الأقصى {MAX_USERS} مستخدم لكل ملف — قسّمي الملف لأكثر من ملف")

    # ---- قواعد الشخص الواحد (عبر صفوفه) ----
    for person in people.values():
        first = person.rows[0]
        name = (first.first_name, first.middle_name, first.last_name)
        titles = {_key(r.job_title) for r in person.rows if r.job_title}
        seen: dict[tuple[str | None, str | None], int] = {}
        primaries = [r for r in person.rows if r.primary == PRIMARY_YES]
        for r in person.rows[1:]:
            if (r.first_name, r.middle_name, r.last_name) != name:
                errors.append(
                    RowError(
                        r.row,
                        "الاسم الأول",
                        f"نفس البريد بالصف {first.row} باسم مختلف — الاسم لازم يتطابق بكل صفوف الشخص",
                    )
                )
        if len(titles) > 1:
            errors.append(
                RowError(
                    person.rows[-1].row,
                    "المسمى الوظيفي",
                    "صفوف نفس البريد فيها مسميات وظيفية مختلفة — المسمى واحد لكل شخص",
                )
            )
        if len(primaries) > 1:
            errors.append(
                RowError(
                    primaries[1].row,
                    "الإدارة الأساسية",
                    f"«{PRIMARY_YES}» مكتوبة بأكثر من صف لنفس الشخص (أول مرة بالصف {primaries[0].row}) — إدارة أساسية واحدة فقط",
                )
            )
        for r, role, department_key in person.assignments:
            key = (department_key, str(role.role_id) if role else None)
            if key in seen:
                errors.append(RowError(r.row, "الدور في الإدارة", f"نفس الإدارة والدور مكررين للشخص (الصف {seen[key]})"))
            seen.setdefault(key, r.row)
            if role is None and len(person.rows) > 1:
                errors.append(
                    RowError(r.row, "الدور في الإدارة", "حددي الدور — الشخص المكتوب بأكثر من صف لازم دور بكل صف")
                )
        if primaries:
            person.primary_key = next(
                (dk for r, _, dk in person.assignments if r.row == primaries[0].row), None
            )
        elif person.assignments:
            person.primary_key = next((dk for _, _, dk in person.assignments if dk is not None), None)

    for key, name in new_departments.items():
        if key not in managers:
            errors.append(
                RowError(
                    department_first_row[key],
                    "الإدارة",
                    f"الإدارة «{name}» جديدة وستُنشأ تلقائيًا، وتحتاج مديرًا: "
                    f"أضيفي صفًا لها دوره «{MANAGER_ROLE_LABEL}»",
                )
            )

    if errors:
        errors.sort(key=lambda e: e.row)
        raise ImportValidationError(errors)

    return people, departments, job_titles, new_departments, new_department_parent, new_job_titles, managers


def _department_label(key: str | None, departments: dict[str, Department], new_departments: dict[str, str]):
    if key is None:
        return None
    if key in departments:
        return departments[key].name
    return new_departments.get(key)


async def preview_import(db: AsyncSession, *, actor: User, rows: list[ParsedRow]) -> ImportPlan:
    """
    الهدف: معاينة الرفع قبل التأكيد (طلب لاما 2026-11-22) — نفس التحقق
    الكامل، ويرجع ملخص ما سيُنشأ (المستخدمون وتعييناتهم، الإدارات الجديدة
    وأمهاتها، المسميات الجديدة). بلا أي كتابة بقاعدة البيانات.
    الأخطاء: نفس import_users (ImportFileError / ImportValidationError).
    """
    people, departments, _, new_departments, new_parent, new_job_titles, _ = await _validate(
        db, actor=actor, rows=rows
    )
    users = [
        ImportPlanUser(
            row=p.rows[0].row,
            full_name=f"{p.rows[0].first_name} {p.rows[0].middle_name} {p.rows[0].last_name}",
            email=p.email,
            primary_department=_department_label(p.primary_key, departments, new_departments),
            assignments=[
                (_department_label(dk, departments, new_departments), r.role or None)
                for r, _, dk in p.assignments
            ],
        )
        for p in people.values()
    ]
    return ImportPlan(
        users=users,
        departments_to_create=[
            (name, _department_label(new_parent[key][0], departments, new_departments))
            for key, name in new_departments.items()
        ],
        job_titles_to_create=list(new_job_titles.values()),
        assignments_count=sum(len(p.assignments) for p in people.values()),
    )


async def import_users(db: AsyncSession, *, actor: User, rows: list[ParsedRow]) -> ImportResult:
    """
    الهدف:
    التحقق من كل صفوف الملف (_validate) ثم إنشاء المستخدمين وتعييناتهم
    (والإدارات والمسميات الجديدة) بمعاملة واحدة — الكل أو لا شيء.

    المدخلات:
    - db: جلسة قاعدة البيانات.
    - actor: المستخدم المُستورِد (يملك users.import — مفحوص بطبقة الـAPI).
    - rows: ناتج parse_workbook.

    المخرجات: ImportResult — مستخدم واحد لكل بريد (مع كلمة المرور المؤقتة
    للإرسال بالبريد فقط)، والإدارات والمسميات المنشأة.

    التأثيرات الجانبية: يكتب users/user_roles/user_department_roles/
    departments/job_titles/audit_logs ويعمل commit. كل مستخدم
    must_change_password=True (FR-UM-016).

    الأخطاء: ImportValidationError بكل أخطاء الصفوف (لا يُكتب شيء).
    """
    people, departments, job_titles, new_departments, new_parent, new_job_titles, managers = await _validate(
        db, actor=actor, rows=rows
    )
    taken_usernames = set(
        (await db.execute(select(func.lower(User.username)).where(User.deleted_at.is_(None)))).scalars()
    )

    # ---- المسميات الجديدة ----
    created_job_titles: list[str] = []
    for key, name in new_job_titles.items():
        job_title = JobTitle(name=name)
        db.add(job_title)
        job_titles[key] = job_title
        created_job_titles.append(name)
    if new_job_titles:
        await db.flush()
        for name in created_job_titles:
            await audit_service.log_action(
                db,
                actor_user_id=actor.user_id,
                action_type="create",
                target_type="job_title",
                target_id=job_titles[_key(name)].job_title_id,
                metadata={"name": name, "source": "excel_import"},
            )

    # ---- الإدارات الجديدة (تحت أمّها لو كُتبت) ----
    codes = await _next_department_codes(db, len(new_departments))
    created_departments: list[tuple[str, str]] = []
    for (key, name), code in zip(new_departments.items(), codes):
        parent_key = new_parent[key][0]
        parent = departments.get(parent_key) if parent_key else None
        department = Department(
            name=name, code=code, description=None, parent_dep_id=parent.dep_id if parent else None
        )
        db.add(department)
        departments[key] = department
        created_departments.append((name, code))
    if new_departments:
        await db.flush()

    # مؤقت قبل التدشين: كلمة موحّدة للجميع بدل generate_temporary_password()
    # — راجعي PRELAUNCH_INITIAL_PASSWORD أعلاه.
    person_list = list(people.values())
    passwords = [PRELAUNCH_INITIAL_PASSWORD for _ in person_list]
    # bcrypt بطيء عمدًا — التجزئة بالتوازي على خيوط منفصلة بدل التسلسل.
    hashes = await asyncio.gather(*(asyncio.to_thread(hash_password, p) for p in passwords))

    created: list[CreatedUser] = []
    assignments_count = 0
    for person, password, password_hash in zip(person_list, passwords, hashes):
        first = person.rows[0]
        primary = departments.get(person.primary_key) if person.primary_key else None
        job_title = job_titles.get(person.job_title_key) if person.job_title_key else None
        # الدور الحالي عند أول دخول: دور صف الإدارة الأساسية، وإلا أول دور.
        ordered_roles: list[Role] = []
        primary_role = next(
            (role for _, role, dk in person.assignments if role is not None and dk == person.primary_key), None
        )
        for role in [primary_role, *(role for _, role, _ in person.assignments)]:
            if role is not None and role not in ordered_roles:
                ordered_roles.append(role)

        username = unique_username(username_base_from_email(person.email), taken_usernames)
        user = User(
            first_name=first.first_name,
            middle_name=first.middle_name,
            last_name=first.last_name,
            username=username,
            email=person.email,
            password_hash=password_hash,
            role_id=ordered_roles[0].role_id if ordered_roles else None,
            dep_id=primary.dep_id if primary else None,
            job_title_id=job_title.job_title_id if job_title else None,
            status=UserStatus.active,
            must_change_password=True,
        )
        db.add(user)
        await db.flush()
        # تعدد الأدوار (0046): user_roles أولًا — قيد users_active_role_assigned_fkey
        # (مؤجَّل لحد COMMIT)، وقيد التعيينات يشترط الدور المسند (0052).
        db.add_all([UserRole(user_id=user.user_id, role_id=r.role_id, assigned_by=actor.user_id) for r in ordered_roles])
        await db.flush()
        unique_assignments = {
            (role.role_id, departments[dk].dep_id)
            for _, role, dk in person.assignments
            if role is not None and dk is not None
        }
        db.add_all(
            [
                UserDepartmentRole(user_id=user.user_id, role_id=rid, dep_id=did, assigned_by=actor.user_id)
                for rid, did in unique_assignments
            ]
        )
        assignments_count += len(person.assignments)

        managed = [dk for r, _, dk in person.assignments if dk is not None and managers.get(dk) == r.row]
        for dk in managed:
            departments[dk].manager_user_id = user.user_id

        await audit_service.log_action(
            db,
            actor_user_id=actor.user_id,
            action_type="create",
            target_type="user",
            target_id=user.user_id,
            metadata={
                "username": username,
                "role": ordered_roles[0].name if ordered_roles else None,
                "roles": [r.name for r in ordered_roles],
                "assignments": [
                    {"role_id": str(rid), "dep_id": str(did)} for rid, did in sorted(unique_assignments, key=str)
                ],
                "source": "excel_import",
            },
        )
        created.append(
            CreatedUser(
                row=first.row,
                user_id=user.user_id,
                full_name=f"{first.first_name} {first.middle_name} {first.last_name}",
                first_name=first.first_name,
                email=person.email,
                username=username,
                department=primary.name if primary else None,
                role="، ".join(r.role for r, _, _ in person.assignments if r.role) or None,
                is_department_manager=bool(managed),
                temporary_password=password,
            )
        )

    for name, code in created_departments:
        department = departments[_key(name)]
        await audit_service.log_action(
            db,
            actor_user_id=actor.user_id,
            action_type="create",
            target_type="department",
            target_id=department.dep_id,
            metadata={
                "name": name,
                "code": code,
                "manager_user_id": str(department.manager_user_id),
                "parent_dep_id": str(department.parent_dep_id) if department.parent_dep_id else None,
                "source": "excel_import",
            },
        )

    await db.commit()
    return ImportResult(
        users=created,
        departments_created=created_departments,
        job_titles_created=created_job_titles,
        assignments_count=assignments_count,
        departments_parents={
            name: _department_label(new_parent[_key(name)][0], departments, new_departments)
            for name, _ in created_departments
        },
    )


# --------------------------------------------------------------------------
# النموذج
# --------------------------------------------------------------------------


async def build_template(db: AsyncSession) -> bytes:
    """
    الهدف: نموذج Excel فارغ بالأعمدة المطلوبة (صف لكل تعيين — migration
    0052)، مع قوائم منسدلة محدثة من النظام: المسميات الوظيفية، الإدارات الأم
    (المستوى الأعلى فقط)، الإدارات (اقتراح — يقبل أيضًا اسم إدارة جديدة)،
    الأدوار (role_choices)، و«نعم» للإدارة الأساسية. شيت "القوائم" للمرجع،
    وشيت "تعليمات" بمثال شخص في أكثر من إدارة.
    المخرجات: bytes ملف .xlsx.
    """
    roles = _assignable_roles(list((await db.execute(select(Role))).scalars().all()))
    titles = sorted((await db.execute(select(JobTitle.name))).scalars().all())
    active_departments = (
        await db.execute(select(Department.name, Department.parent_dep_id).where(Department.deleted_at.is_(None)))
    ).all()
    department_names = sorted(name for name, _ in active_departments)
    parent_names = sorted(name for name, parent in active_departments if parent is None)
    choices = role_choices(roles)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    sheet.sheet_view.rightToLeft = True
    sheet.append(TEMPLATE_HEADERS)
    header_fill = PatternFill("solid", fgColor="105EA7")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for column, width in zip("ABCDEFGHI", (14, 14, 14, 30, 24, 24, 24, 22, 16)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"

    lists = workbook.create_sheet(LISTS_SHEET_NAME)
    lists.sheet_view.rightToLeft = True
    columns = [
        ("الأدوار", choices),
        ("المسميات الوظيفية", titles),
        ("الإدارات الحالية", department_names),
        ("الإدارات الأم", parent_names),
        ("الإدارة الأساسية", [PRIMARY_YES]),
    ]
    lists.append([title for title, _ in columns])
    for cell in lists[1]:
        cell.font = Font(bold=True)
    for i in range(max(len(values) for _, values in columns)):
        lists.append([values[i] if i < len(values) else None for _, values in columns])
    for column in "ABCDE":
        lists.column_dimensions[column].width = 28

    last_data_row = MAX_ROWS + 1

    def add_list(list_column: str, count: int, target_column: str, *, strict: bool = True) -> None:
        if not count:
            return
        validation = DataValidation(
            type="list",
            formula1=f"'{LISTS_SHEET_NAME}'!${list_column}$2:${list_column}${count + 1}",
            allow_blank=True,
            # الإدارة: قائمة مقترحة فقط — الاسم الجديد مقبول (يُنشأ تلقائيًا).
            showErrorMessage=strict,
        )
        validation.add(f"{target_column}2:{target_column}{last_data_row}")
        sheet.add_data_validation(validation)

    add_list("A", len(choices), "H")
    add_list("B", len(titles), "E")
    add_list("C", len(department_names), "G", strict=False)
    add_list("D", len(parent_names), "F")
    add_list("E", 1, "I")

    notes = workbook.create_sheet("تعليمات")
    notes.sheet_view.rightToLeft = True
    for line in (
        "كل صف = تعيين واحد (إدارة + دور). الشخص في أكثر من إدارة = أكثر من صف بنفس البريد.",
        "البريد يعرّف الشخص: كل الصفوف بنفس البريد = مستخدم واحد (حساب واحد وبريد ترحيب واحد).",
        "الاسم الثلاثي والمسمى الوظيفي لازم يتطابقون بكل صفوف نفس البريد.",
        f"الإدارة الأساسية: «{PRIMARY_YES}» بصف واحد فقط للشخص (للعرض). بدونها تكون إدارة أول صف له.",
        "الإدارة الأم اختيارية: لازم تكون موجودة بالنظام. لو الإدارة جديدة تُنشأ تحتها تلقائيًا.",
        f"الإدارة الجديدة تحتاج صف مدير دوره «{MANAGER_ROLE_LABEL}». انتبهي للإملاء: اسم مختلف = إدارة جديدة.",
        "البريد المسجّل مسبقًا بالنظام يُرفض — إدارات المستخدم الحالي تُعدَّل من صفحة المستخدم.",
        "لو فيه أي خطأ بأي صف ما يُضاف أحد، وتظهر الأخطاء برقم الصف.",
    ):
        notes.append([line])
    notes.column_dimensions["A"].width = 100

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
