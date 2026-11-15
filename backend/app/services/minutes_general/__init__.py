"""
الهدف:
"القالب العام" للمحاضر (طلب صاحب المشروع 2026-11-15) — قالب رابع بجانب
القوالب الثابتة في meeting_minutes_service، بشكل محضر وادي مكة المعتمد.

الوحدات:
- formatting: التاريخ الهجري/الميلادي، الوقت، الترتيب بالكلمات.
- editor_content: التحقق من محتوى المحرر الغني.
- sections: بناء الأقسام ومزامنتها ودمج تعديلات المستخدم (دوال نقية).
- snapshot: جمع بيانات الاجتماع من القاعدة.
- pdf: ملف PDF مطابق لشكل المحضر الأصلي.

التصميم الكامل: docs/minutes-official-template.md.
"""

from app.services.minutes_general.sections import TEMPLATE_DESCRIPTION, TEMPLATE_ID, TEMPLATE_NAME

__all__ = ["TEMPLATE_DESCRIPTION", "TEMPLATE_ID", "TEMPLATE_NAME"]
