"""
الهدف:
منطق العمل لوحدة "إدارة القرارات" — القرارات المستقلة فقط (FR-001 مسار
الإصدار المباشر، §5 SRS + §7 BRS). بدون القرارات المستخرجة من اجتماع
بالذكاء الاصطناعي (تُبنى لاحقًا)، وبدون أي ربط بالوثائق (تُبنى من طرف آخر
بالفريق حاليًا). راجعي رأس db/migrations/0021_decisions_schema.sql لكل
الاجتهادات الموثّقة المتفَق عليها مع صاحبة المشروع (2026-09-02).

التفويض: نفس النمط الهجين المطبَّق بوحدة الاجتماعات بالضبط (System Role
scope أو Committee Role permission، عبر committee_service.
get_committee_role_permission_codes) — الأكواد المستخدَمة هنا من كتالوج
0006 الأصلي: decisions.view / decisions.create / decisions.update /
decisions.delete / decisions.vote.open / decisions.vote.cast /
decisions.vote.view_result / decisions.approve.

إغلاق التصويت بالموعد (voting_deadline) يُقيَّم كسليًا (Lazy) عند أي
تفاعل مع القرار (عرض/تصويت/محاولة اعتماد) — لا يوجد Scheduler/Cron
بالمشروع بعد لإغلاقه تلقائيًا بلحظة انتهاء الموعد بالضبط؛ التأخر هنا لا
يتجاوز وقت أول طلب API يلمس القرار بعد الموعد.

تحديث 2026-09-02 (بعد تجربة فعلية من صاحبة المشروع): المنفذون (assignees)
لم يعودوا يُختارون يدويًا عند الإنشاء/التعديل — كل أعضاء اللجنة (بمن فيهم
رئيسها) يُضافون تلقائيًا، بنفس مبدأ مشاركي الاجتماع تمامًا (راجعي
meeting_service._all_committee_members).

تحديث 2026-09-07 (قرار صريح: "الي يحدد بيانات التصويت رئيس اللجنة بس
والأعضاء يقررون"): خيارات التصويت لم تعد ثابتة (موافق/غير موافق) —
open_voting يستقبلها الآن من رئيسة اللجنة نفسها (كل خيار له label حر
و is_approving صريح)، وcast_vote يصوّت لـoption_id محدَّد بدل قيمة enum
ثابتة. راجعي رأس db/migrations/0025_decision_vote_options.sql لتفصيل

تصحيح 2026-09-07 (بلاغ خطأ من صاحبة المشروع: "عضو اللجنة ليه يمديه يشوف
نتيجة التصويت؟! غلط ما أعطيته الصلاحية"): decisions.view لم يكن يُفرَّق
سابقًا عن decisions.vote.view_result — أي عضو يقدر يشوف القرار كان يشوف
تفصيل تصويت الجميع تلقائيًا، رغم أن الكود موجود بالكتالوج منفصلًا منذ
0006 ولم يُفحص فعليًا بأي مكان. صُحِّح الآن عبر _redact_votes_if_unauthorized
(راجعي docstring الدالة) — يُطبَّق في كل نقطة إرجاع Decision بالملف.
كيف تبقى الأغلبية التلقائية تعمل: لو فيه خيار واحد على الأقل is_approving
=true، الأغلبية = مجموع أصوات كل الخيارات المعلَّمة مقابل الإجمالي (تعميم
مباشر للقاعدة الثنائية القديمة). لو ولا خيار معلَّم (استطلاع رأي بحت)،
لا رفض تلقائي إطلاقًا — القرار يبقى بحالة 'voting' بعد الإغلاق بانتظار
اعتماد يدوي من رئيسة اللجنة بناءً على تقديرها الشخصي للنتائج المعروضة.

تحديث 2026-09-07 (طلب صاحبة المشروع: إشعار عند رفض القرار تلقائيًا):
get_decision وcast_vote يُرجعان الآن (Decision, just_rejected: bool) بدل
Decision وحدها — just_rejected=True فقط إذا هذا الاستدعاء تحديدًا هو
الذي تسبَّب بالإغلاق الكسلي المؤدي للرفض (وليس قرارًا رُفض من قبل أصلًا)،
لتُطلِق طبقة الـAPI notification_service.notify_decision_rejected مرة
واحدة بالضبط عند وقوعه فعليًا — لا تكرار عبر استدعاءات لاحقة تصادف نفس
القرار وهو أصلًا مرفوض. راجعي docstring كل دالة للتفصيل.

بنية الحزمة (إعادة هيكلة 2026-10-24 — كانت ملفًا واحدًا ~620 سطرًا):
- errors.py     أخطاء الوحدة (تترجمها طبقة الـAPI لأكواد HTTP).
- loading.py    المكان الوحيد الذي يحدد ماذا يُحمَّل مع القرار (عدد استعلامات ثابت).
- access.py     قواعد صلاحيات القرارات الخاصة (فوق app/services/committee_access.py المشترك).
- voting.py     الإغلاق الكسلي، فتح التصويت، التصويت، الاعتماد.
- crud.py       الإنشاء/العرض/القائمة/التعديل/الحذف.
الاستيراد القديم (from app.services import decision_service; decision_service.X)
يعمل كما هو — كل الأسماء العامة مُعاد تصديرها هنا.
"""

from app.services.decision_service.crud import (
    create_decision,
    delete_decision,
    get_decision,
    list_decisions,
    update_decision,
)
from app.services.decision_service.errors import (
    DecisionForbiddenError,
    DecisionInvalidStateError,
    DecisionNotFoundError,
    DecisionValidationError,
)
from app.services.decision_service.voting import approve_decision, cast_vote, open_voting

__all__ = [
    "DecisionForbiddenError",
    "DecisionInvalidStateError",
    "DecisionNotFoundError",
    "DecisionValidationError",
    "approve_decision",
    "cast_vote",
    "create_decision",
    "delete_decision",
    "get_decision",
    "list_decisions",
    "open_voting",
    "update_decision",
]
