"""أخطاء وحدة الوثائق."""


class DocumentValidationError(ValueError):
    """خطأ تحقق منطقي (اسم مكرر، حجم ملف متجاوز الحد، مرجع غير موجود...)."""
