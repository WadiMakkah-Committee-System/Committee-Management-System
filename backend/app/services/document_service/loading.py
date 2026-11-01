"""
تحميل الوثائق وما يرتبط بها — المكان **الوحيد** بوحدة الوثائق الذي يحدد
ماذا يُحمَّل (إعادة هيكلة 2026-10-24).

لماذا: خيارات التحميل السابقة (selectinload لكل علاقة) كانت تحمّل الطبقة
الأولى فقط صراحةً، ثم تكمل العلاقات lazy="selectin" الافتراضية بالموديلات
الشجرة كاملة تلقائيًا تحت كل منها: رافع الوثيقة والمستخدمون المحددون →
أدوارهم → صلاحياتهم؛ اللجان المحددة → رئيسها وأعضاؤها وmember_roles →
أدوارهم وصلاحياتهم؛ الإدارات المحددة → مديرها → دوره... إضافة لعمودَي
content_text (النص المستخرج كاملًا من الملف) وembedding (768 رقمًا) لكل
وثيقة في القائمة رغم أن DocumentOut لا يعرض أيًا منهما.

هنا: كل علاقة يُحمَّل منها ما يعرضه DocumentOut فقط (أعمدتها)، وأي علاقة
أعمق عليها raiseload(sql_only=True).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, joinedload, raiseload, selectinload

from app.models.committee import Committee
from app.models.department import Department
from app.models.document import Document, DocumentCategory
from app.models.user import User

_RAISE = {"sql_only": True}


def _leaf(path) -> tuple:
    """العلاقة بأعمدتها فقط — بلا أي علاقة متفرعة منها."""
    return (path, path.raiseload("*", **_RAISE))


def only_columns() -> tuple:
    """لأي كائن (لجنة/إدارة/مستخدم/تصنيف) يُستخدم بأعمدته فقط."""
    return (raiseload("*", **_RAISE),)


def document_options(*, with_content: bool = False) -> tuple:
    """
    شكل DocumentOut + ما يحتاجه فحص الرؤية (visible_* / uploaded_by /
    is_public). with_content=True لمن يقرأ content_text فعلًا (شات وثيقة
    واحدة عبر get_document). embedding لا يُحمَّل أبدًا هنا — البحث الدلالي
    يرتّب به داخل SQL فقط.
    """
    options: list = [
        # many-to-one: JOIN بنفس الاستعلام بدل استعلام selectin مستقل
        # (تحسين أداء 2026-10-25 — نفس البيانات).
        *_leaf(joinedload(Document.category)),
        *_leaf(joinedload(Document.uploader)),
        *_leaf(selectinload(Document.visible_departments)),
        *_leaf(selectinload(Document.visible_committees)),
        *_leaf(selectinload(Document.visible_users)),
        defer(Document.embedding),
        raiseload("*", **_RAISE),
    ]
    if not with_content:
        options.append(defer(Document.content_text))
    return tuple(options)


def documents_query(*, with_content: bool = False, reload: bool = False):
    """reload=True فقط لإعادة التحميل بعد commit بنفس الدالة (populate_existing)
    — ليس افتراضيًا لأن الكائنات المرتبطة مشتركة بين الخدمات بنفس الجلسة."""
    return (
        select(Document)
        .options(*document_options(with_content=with_content))
        .execution_options(populate_existing=reload)
    )


async def load_document(
    db: AsyncSession, document_id: uuid.UUID, *, with_content: bool = False, reload: bool = False
) -> Document | None:
    """الوثيقة غير المحذوفة (أو None) — بدون أي فحص رؤية."""
    result = await db.execute(
        documents_query(with_content=with_content, reload=reload).where(
            Document.document_id == document_id, Document.deleted_at.is_(None)
        )
    )
    return result.unique().scalar_one_or_none()


async def load_category(
    db: AsyncSession, category_id: uuid.UUID, *, reload: bool = False
) -> DocumentCategory | None:
    result = await db.execute(
        select(DocumentCategory)
        .where(DocumentCategory.category_id == category_id)
        .options(*only_columns())
        .execution_options(populate_existing=reload)
    )
    return result.scalar_one_or_none()


async def load_department(db: AsyncSession, dep_id: uuid.UUID) -> Department | None:
    result = await db.execute(
        select(Department).where(Department.dep_id == dep_id).options(*only_columns())
    )
    return result.scalar_one_or_none()


def committees_query():
    return select(Committee).options(*only_columns())


def departments_query():
    return select(Department).options(*only_columns())


def users_query():
    return select(User).options(*only_columns())
