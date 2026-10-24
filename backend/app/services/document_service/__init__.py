"""
الهدف:
منطق العمل لوحدة "إدارة الوثائق" — تصنيفات الوثائق ونطاق رؤيتها المركّب
(عام / إدارة محددة / لجنة محددة / مستخدم محدد)، ورفع/عرض/تعديل/حذف/تحميل
الوثيقة نفسها (الملف الفعلي مخزَّن بـ Supabase Storage عبر
app.core.storage_client، هذه الوحدة تخزّن البيانات الوصفية فقط).

المسؤولية:
- فحص صلاحيات الرؤية المركّبة (is_public / إدارة المستخدم / لجانه /
  ارتباطه شخصيًا) لكل قراءة أو تحميل — بمعزل عن فحص صلاحية RBAC العامة
  (documents.view/download) التي تُفرض بطبقة الـ API عبر require_permission.
- تسجيل كل عملية (رفع/تعديل/حذف/تحميل) في audit_logs عبر audit_service.

قرارات موثّقة:
- البحث (q) في هذه المرحلة ILIKE بسيط على العنوان/الوصف (ومحتوى الوثيقة
  إن كانت لدى المستخدم صلاحية documents.search_content) — عمود
  content_tsv (Full-Text Search عبر GIN index) جاهز بالقاعدة لكن غير
  مستخدَم بعد؛ الانتقال له تحسين لاحق عند الحاجة لأداء أفضل مع حجم بيانات
  أكبر. البحث الدلالي (embedding/Gemini، صلاحية documents.search_all_agent)
  مؤجَّل بالكامل لمرحلة ال٢كاء الاصطناعي القادمة (راجع docstring
  app/models/document.py).
- documents.export موجودة بكتالوج الصلاحيات لمرحلة تصدير لاحقة (مثال:
  تصدير قائمة الوثائق CSV) — لا يوجد لها Endpoint في هذه المرحلة، بنفس
  منطق document_links (جاهز بالقاعدة، غير مُستخدم بعد).
- فحص "رؤية" وثيقة بعينها (get/download) يُرجع None (→ 404 بطبقة الـ API)
  وليس خطأ صلاحية 403، حتى لا نكشف حتى بوجود الوثيقة لمن لا تظهر له.
- الحذف Soft Delete (deleted_at) اتساقًا مع بقية الكيانات الجوهرية —
  الملف بالتخزين يبقى كما هو (لا نحذفه فعليًا)، فقط البيانات الوصفية
  تُخفى من القوائم والوصول.

بنية الحزمة (إعادة هيكلة 2026-10-24 — كانت ملفًا واحدًا ~754 سطرًا):
- errors.py      DocumentValidationError.
- loading.py     المكان الوحيد الذي يحدد ماذا يُحمَّل مع الوثيقة (بلا شجرة العلاقات
                 الافتراضية، وبلا content_text/embedding بالقوائم).
- visibility.py  فحص الرؤية المركّبة (DocumentViewer يجلب لجان المستخدم مرة واحدة
                 للطلب) + أهداف النشر.
- categories.py  تصنيفات الوثائق.
- documents.py   الوثائق نفسها.
الاستيراد القديم (document_service.X) يعمل كما هو.
"""

from app.services.document_service.categories import (
    create_category,
    delete_category,
    get_category,
    list_categories,
    update_category,
)
from app.services.document_service.documents import (
    DocumentScopeFilter,
    _assert_single_visibility_category,
    create_document,
    delete_document,
    download_document,
    get_document,
    list_documents,
    update_document,
)
from app.services.document_service.errors import DocumentValidationError
from app.services.document_service.loading import document_options
from app.services.document_service.visibility import (
    DocumentViewer,
    can_view_document,
    get_publish_targets,
)

__all__ = [
    "DocumentScopeFilter",
    "DocumentValidationError",
    "DocumentViewer",
    "_assert_single_visibility_category",
    "can_view_document",
    "create_category",
    "create_document",
    "delete_category",
    "delete_document",
    "document_options",
    "download_document",
    "get_category",
    "get_document",
    "get_publish_targets",
    "list_categories",
    "list_documents",
    "update_category",
    "update_document",
]
