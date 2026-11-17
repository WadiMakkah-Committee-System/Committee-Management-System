"""
الهدف:
أكواد صلاحيات التذاكر — تطابق كتالوج migration 0051 حرفيًا (القسم 6 بالمواصفات).
"""

#: مقدّم الطلب: إرسال التذاكر ومتابعتها (على تذاكره فقط).
TICKETS_CREATE = "tickets.create"
#: الدعم: عرض كل التذاكر وسجلها — شرط لباقي خانات الدعم.
TICKETS_VIEW_ALL = "tickets.view_all"
#: الدعم: الرد العام على أي تذكرة.
TICKETS_REPLY = "tickets.reply"
#: الدعم: كتابة الملاحظات الداخلية وقراءتها.
TICKETS_INTERNAL_NOTES = "tickets.internal_notes"
#: الدعم: تغيير الحالة والأولوية والنوع والوحدة.
TICKETS_MANAGE = "tickets.manage"
#: الدعم: الاستلام وإعادة الإسناد.
TICKETS_ASSIGN = "tickets.assign"
