"""محاضر الاجتماعات (Minutes)."""

import logging
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import perf_probe
from app.core.background import run_detached
from app.core.dependencies import CurrentUser
from app.core.socketio_server import sio
from app.db.session import get_db, writes_on_read
from app.schemas.committee import CommitteeMemberUserOut
from app.schemas.meeting_minutes import (
    MeetingMinutesDetailOut,
    MeetingMinutesOut,
    MinutesDetailCommitteeOut,
    MinutesDetailMeetingOut,
    MinutesSection,
    MinutesSummaryOut,
    MinutesTemplateOut,
    ReviewDecisionIn,
    SelectTemplateIn,
    SignMinutesIn,
    UpdateSectionIn,
    UpdateSectionsIn,
)
from app.services import meeting_minutes_service, notification_service

from app.api.v1.documents import _content_disposition
from app.api.v1.meetings._errors import _SERVICE_ERRORS, _handle_errors
from app.api.v1.meetings.ai import _extracted_item_out

router = APIRouter(prefix="/meetings", tags=["meetings"])
logger = logging.getLogger(__name__)


async def _broadcast_minutes(meeting_id: uuid.UUID, event: str, payload: dict) -> None:
    """
    الهدف: بثّ تحديث محضر "القالب العام" من الخادم لغرفة الاجتماع (Socket.IO)
    — النسخة المحفوظة فعليًا، لا ما يرسله العميل.
    المدخلات: الاجتماع، اسم الحدث (minutes.updated / minutes.section_updated)، البيانات.
    التأثيرات الجانبية: بثّ فقط. فشل البث لا يُفشل الطلب (الحفظ تم) — يُسجَّل تحذير.
    """
    try:
        await sio.emit(event, payload, room=f"meeting:{meeting_id}")
    except Exception:  # noqa: BLE001 — البث تحسين لحظي، الحفظ هو الأساس
        logger.warning("minutes broadcast failed (%s) for meeting %s", event, meeting_id, exc_info=True)


def _conflict_response(exc: meeting_minutes_service.MinutesSectionConflictError) -> HTTPException:
    """409 مع نسخة القسم الحالية حتى تعرضها الواجهة وتعيد تطبيق التعديل."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": str(exc),
            "current_section": MinutesSection.model_validate(exc.current_section).model_dump(),
        },
    )


# ============================== المحاضر (Minutes) ==============================
# SRS §7 — راجعي رأس app/services/meeting_minutes_service.py للتصميم
# الكامل (آلة الحالة، القوالب الثابتة، التفويض). التحرير التعاوني اللحظي
# (FR-MIN-005) يُبث عبر حدث "minutes.updated" على نفس قناة WebSocket
# لغرفة الاجتماع أدناه — وليس عبر Polling على هذي الراوتات.


def _minutes_out(minutes) -> MeetingMinutesOut:
    return MeetingMinutesOut(
        minutes_id=minutes.minutes_id,
        meeting_id=minutes.meeting_id,
        template_id=minutes.template_id,
        template_name=meeting_minutes_service.template_name_for(minutes.template_id),
        stage=minutes.stage.value,
        owner=CommitteeMemberUserOut.model_validate(minutes.owner) if minutes.owner else None,
        sections=[MinutesSection.model_validate(s) for s in minutes.sections],
        reviewers=[
            {
                "reviewer_id": r.reviewer_id,
                "user": CommitteeMemberUserOut.model_validate(r.user),
                "status": r.status.value,
                "comment": r.comment,
                "reviewed_at": r.reviewed_at,
            }
            for r in minutes.reviewers
        ],
        signatures=[
            {
                "signature_id": s.signature_id,
                "user": CommitteeMemberUserOut.model_validate(s.user),
                "signed": s.signed_at is not None,
                "signed_at": s.signed_at,
            }
            for s in minutes.signatures
        ],
        sent_to_review_at=minutes.sent_to_review_at,
        approved_at=minutes.approved_at,
        sent_for_signature_at=minutes.sent_for_signature_at,
        completed_at=minutes.completed_at,
        created_at=minutes.created_at,
        updated_at=minutes.updated_at,
    )


async def _minutes_detail_meeting_out_with_guests(db: AsyncSession, meeting) -> MinutesDetailMeetingOut:
    """+ الضيوف المقبولون (migration 0047) — "ضيف خارجي" بقسم الحضور بالمحضر."""
    from app.schemas.committee import CommitteeMemberUserOut
    from app.services import meeting_guest_service

    out = _minutes_detail_meeting_out(meeting)
    out.guests = [
        CommitteeMemberUserOut(
            user_id=g.user_id, first_name=g.first_name, middle_name="", last_name="", email="", is_guest=True
        )
        for g in await meeting_guest_service.list_admitted_guests(db, meeting.meeting_id)
    ]
    return out


def _minutes_detail_meeting_out(meeting) -> MinutesDetailMeetingOut:
    # from_attributes=True (راجعي MinutesDetailMeetingOut) — نفس نمط
    # MeetingOut.model_validate(meeting) المستخدَم ببقية راوتات هذا الملف،
    # بدل بناء يدوي حقل-حقل عرضة للأخطاء.
    return MinutesDetailMeetingOut.model_validate(meeting)


def _minutes_detail_committee_out(committee) -> MinutesDetailCommitteeOut:
    return MinutesDetailCommitteeOut.model_validate(committee)


@router.get("/{meeting_id}/minutes/detail", response_model=MeetingMinutesDetailOut)
# يكتب أثناء القراءة (راجعي writes_on_read بـapp/db/session.py)
@writes_on_read
async def get_meeting_minutes_detail(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingMinutesDetailOut:
    """توحيد أداء (التوصية الثانية بتقرير أداء لاما 2026-09-14 — راجعي
    docstring get_minutes_detail بـservices/meeting_minutes_service.py
    للتصميم الكامل): نقطة واحدة تستبدل 5 طلبات منفصلة كانت
    MeetingMinutesPage.tsx تطلقها (اجتماع/لجنة/محضر/قوالب/بنود مستخرجة)،
    أهمها إلغاء Network Waterfall حقيقي كان موجودًا (طلب اللجنة كان ينتظر
    نتيجة طلب الاجتماع أولًا لمعرفة committee_id قبل أن يبدأ أصلًا)."""
    try:
        detail = await meeting_minutes_service.get_minutes_detail(
            db, meeting_id=meeting_id, actor=current_user
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    minutes_out = _minutes_out(detail["minutes"])
    if detail.get("synced"):
        # القالب العام: بيانات الاجتماع غيّرت أجزاء تلقائية — نبثّها للحاضرين.
        await _broadcast_minutes(
            meeting_id,
            "minutes.updated",
            {"user_id": None, "full_name": None, "sections": [s.model_dump() for s in minutes_out.sections]},
        )
    return MeetingMinutesDetailOut(
        meeting=await _minutes_detail_meeting_out_with_guests(db, detail["meeting"]),
        committee=_minutes_detail_committee_out(detail["committee"]),
        minutes=minutes_out,
        templates=[MinutesTemplateOut(**t) for t in detail["templates"]],
        extracted_items=[_extracted_item_out(item) for item in detail["extracted_items"]],
        can_edit=detail["can_edit"],
    )


@router.get("/{meeting_id}/minutes/pdf")
async def download_meeting_minutes_pdf(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> Response:
    """
    تحميل المحضر PDF (تصنيف "مرفقات اللجنة" بالوثائق — طلب لاما 2026-11-01).
    يتطلب minutes.view. يُولَّد لحظيًا من آخر نسخة مخزَّنة (راجعي
    meeting_minutes_service.get_minutes_pdf). 404 لو لم يُنشأ محضر بعد.
    """
    try:
        filename, content = await meeting_minutes_service.get_minutes_pdf(
            db, meeting_id=meeting_id, actor=current_user
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    # الاسم عربي — _content_disposition (RFC 5987) من documents.py.
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/minutes/summary", response_model=list[MinutesSummaryOut])
async def get_minutes_summaries(
    current_user: CurrentUser,
    meeting_ids: str = Query(default="", description="قائمة meeting_id مفصولة بفاصلة"),
    db: AsyncSession = Depends(get_db),
) -> list[MinutesSummaryOut]:
    """إصلاح 2026-09-14 (بلاغ لاما — 500 متكرر على مسارات متعددة غير
    مرتبطة ببعض بنفس اللحظة، راجعي docstring MinutesSummaryOut للتفاصيل
    الكاملة): نقطة دفعية واحدة تستبدل N طلب منفصل (get_meeting_minutes
    لكل اجتماع عبر useQueries بـMinutesListPage.tsx) — كل نداء لهذي
    النقطة اتصال قاعدة بيانات واحد بدل N اتصال متزامن، مهما كان عدد
    الاجتماعات المطلوبة.

    ?meeting_ids=id1,id2,... (نص واحد مفصول بفاصلة — تحققتُ فعليًا إن
    axios 1.19 بهذا المشروع يسلسل `params: { x: string[] }` بصيغة
    x[]=a&x[]=b الافتراضية غير المدعومة تلقائيًا من FastAPI Query(list),
    فتجنّبت هذا الفخ كليًا بمعامل نصي واحد بدل قائمة)."""
    ids = [s.strip() for s in meeting_ids.split(",") if s.strip()]
    if not ids:
        return []
    try:
        parsed_ids = [uuid.UUID(s) for s in ids]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="meeting_ids غير صالحة") from exc
    summaries = await meeting_minutes_service.list_minutes_summaries(
        db, actor=current_user, meeting_ids=parsed_ids
    )
    return [MinutesSummaryOut(**s) for s in summaries]


@router.get("/{meeting_id}/minutes/templates", response_model=list[MinutesTemplateOut])
async def list_minutes_templates(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[MinutesTemplateOut]:
    """FR-MIN-003: عرض قوالب المحاضر المعتمدة — لرئيس اللجنة/الأدمن فقط
    (minutes.templates.view، تصحيح 2026-09-15 — راجعي رأس
    meeting_minutes_service.list_templates_for_meeting للتفاصيل). الفرونت
    لا يستدعي هذا المسار إلا لمن يملك canManage؛ الأعضاء العاديون يشوفون
    اسم القالب المختار فقط عبر MeetingMinutesOut.template_name بالمسار
    العادي GET /{meeting_id}/minutes."""
    try:
        templates = await meeting_minutes_service.list_templates_for_meeting(
            db, meeting_id=meeting_id, actor=current_user
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return [MinutesTemplateOut(**t) for t in templates]


@router.get("/{meeting_id}/minutes", response_model=MeetingMinutesOut)
# يكتب أثناء القراءة (راجعي writes_on_read بـapp/db/session.py)
@writes_on_read
async def get_meeting_minutes(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingMinutesOut:
    # تحقيق أداء لاما 2026-09-13 (المرحلة النهائية — طلبت تفصيلًا: Auth /
    # SQL execution / Serialization / Total): auth.* uses مقاسة أصلًا
    # بـcore/dependencies.py قبل الوصول لهذا الراوت أصلًا، وكل استعلام SQL
    # مقاس أصلًا بـdb/session.py event hooks (dur_ms لكل "sql: ..." بالتتبع
    # هو زمن الرحلة الشبكية+التنفيذ سويةً وليس تنفيذ Postgres وحده — نفس
    # الاستنتاج الموثّق سابقًا: هذا الرقم تهيمن عليه رحلة الشبكة العابرة
    # للمنطقة (Render↔Supabase) لا تنفيذ الاستعلام الفعلي بالسيرفر). ما
    # كان ناقصًا فقط: قياس صريح لمرحلة التسلسل (serialization/Pydantic)
    # بعد انتهاء كل استعلامات القاعدة — تضاف هنا فقط، بلا أي تغيير على
    # منطق الخدمة أو شكل الاستجابة.
    with perf_probe.timed("api.get_minutes.db_phase"):
        try:
            minutes = await meeting_minutes_service.get_or_create_minutes(
                db, meeting_id=meeting_id, actor=current_user
            )
        except _SERVICE_ERRORS as exc:
            raise _handle_errors(exc) from exc
    with perf_probe.timed("api.get_minutes.serialization"):
        return _minutes_out(minutes)


@router.post("/{meeting_id}/minutes/template", response_model=MeetingMinutesOut)
async def select_minutes_template(
    meeting_id: uuid.UUID,
    payload: SelectTemplateIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    try:
        minutes = await meeting_minutes_service.select_template(
            db, meeting_id=meeting_id, actor=current_user, template_id=payload.template_id
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _minutes_out(minutes)


@router.put("/{meeting_id}/minutes/sections", response_model=MeetingMinutesOut)
async def update_minutes_sections(
    meeting_id: uuid.UUID,
    payload: UpdateSectionsIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    """حفظ (Autosave) — الفرونت يرسل القائمة الكاملة بعد كل تعديل محلي؛
    البث اللحظي لبقية الحاضرين مسؤولية اتصال WebSocket المنفصل (حدث
    minutes.updated)، وليس استجابة هذا الراوت."""
    try:
        minutes = await meeting_minutes_service.update_sections(
            db,
            meeting_id=meeting_id,
            actor=current_user,
            sections=[s.model_dump() for s in payload.sections],
        )
    except meeting_minutes_service.MinutesSectionConflictError as exc:
        raise _conflict_response(exc) from exc
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    out = _minutes_out(minutes)
    if meeting_minutes_service.is_general(minutes):
        # القالب العام: البث من الخادم بالنسخة المدموجة (الأقفال/المحذوف محسوبة).
        await _broadcast_minutes(
            meeting_id,
            "minutes.updated",
            {
                "user_id": str(current_user.user_id),
                "full_name": current_user.full_name,
                "sections": [s.model_dump() for s in out.sections],
            },
        )
    return out


@router.patch("/{meeting_id}/minutes/sections/{section_id}", response_model=MeetingMinutesOut)
async def update_minutes_section(
    meeting_id: uuid.UUID,
    section_id: str,
    payload: UpdateSectionIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    """
    PATCH /meetings/{meeting_id}/minutes/sections/{section_id} — حفظ قسم واحد
    من محضر "القالب العام" (الحفظ الأساسي أثناء التحرير الجماعي).

    - Authentication: مستخدم مسجّل.
    - Authorization: minutes.update على لجنة الاجتماع (بالخادم).
    - Validation: section.id يطابق المسار؛ البيانات حسب نوع القسم؛ rev الحالي.
    - 200: المحضر كامل بعد الحفظ، ويُبثّ القسم المحفوظ لغرفة الاجتماع
      (minutes.section_updated).
    - 400: بيانات غير صالحة / قسم غير موجود / محضر ليس من القالب العام.
    - 403: بلا صلاحية. 404: لا يوجد محضر.
    - 409: المحضر ليس بمرحلة التحضير، أو rev قديم (مع current_section).
    """
    if payload.section.id != section_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="معرّف القسم لا يطابق المسار")
    try:
        minutes, saved = await meeting_minutes_service.update_section(
            db, meeting_id=meeting_id, actor=current_user, section=payload.section.model_dump()
        )
    except meeting_minutes_service.MinutesSectionConflictError as exc:
        raise _conflict_response(exc) from exc
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    await _broadcast_minutes(
        meeting_id,
        "minutes.section_updated",
        {
            "user_id": str(current_user.user_id),
            "full_name": current_user.full_name,
            "section": MinutesSection.model_validate(saved).model_dump(),
        },
    )
    return _minutes_out(minutes)


@router.post("/{meeting_id}/minutes/review/approve", response_model=MeetingMinutesOut)
async def approve_minutes_review(
    meeting_id: uuid.UUID,
    payload: ReviewDecisionIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    try:
        minutes = await meeting_minutes_service.submit_review(
            db, meeting_id=meeting_id, actor=current_user, approve=True, comment=payload.comment
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _minutes_out(minutes)


@router.post("/{meeting_id}/minutes/review/return", response_model=MeetingMinutesOut)
async def return_minutes_review(
    meeting_id: uuid.UUID,
    payload: ReviewDecisionIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    try:
        minutes = await meeting_minutes_service.submit_review(
            db, meeting_id=meeting_id, actor=current_user, approve=False, comment=payload.comment
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _minutes_out(minutes)


@router.post("/{meeting_id}/minutes/approve", response_model=MeetingMinutesOut)
async def approve_meeting_minutes(
    meeting_id: uuid.UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> MeetingMinutesOut:
    try:
        minutes = await meeting_minutes_service.approve_minutes(db, meeting_id=meeting_id, actor=current_user)
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _minutes_out(minutes)


@router.post("/{meeting_id}/minutes/return", response_model=MeetingMinutesOut)
async def return_minutes_for_edit(
    meeting_id: uuid.UUID,
    payload: ReviewDecisionIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    try:
        minutes = await meeting_minutes_service.return_for_edit(
            db, meeting_id=meeting_id, actor=current_user, comment=payload.comment
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    return _minutes_out(minutes)


@router.post("/{meeting_id}/minutes/signature/send", response_model=MeetingMinutesOut)
async def send_minutes_for_signature(
    meeting_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    try:
        minutes = await meeting_minutes_service.send_for_signature(
            db, meeting_id=meeting_id, actor=current_user
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    meeting = await meeting_minutes_service.load_meeting(db, meeting_id)
    run_detached(
        notification_service.notify_minutes_sent_for_signature(
            minutes, meeting, actor_user_id=current_user.user_id
        )
    )
    return _minutes_out(minutes)


@router.post("/{meeting_id}/minutes/sign", response_model=MeetingMinutesOut)
async def sign_meeting_minutes(
    meeting_id: uuid.UUID,
    payload: SignMinutesIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MeetingMinutesOut:
    try:
        minutes = await meeting_minutes_service.sign_minutes(
            db,
            meeting_id=meeting_id,
            actor=current_user,
            signature_image=payload.signature_image,
            use_saved=payload.use_saved,
            save_for_later=payload.save_for_later,
        )
    except _SERVICE_ERRORS as exc:
        raise _handle_errors(exc) from exc
    if minutes.stage.value == "completed":
        meeting = await meeting_minutes_service.load_meeting(db, meeting_id)
        run_detached(notification_service.notify_minutes_completed(minutes, meeting))
    return _minutes_out(minutes)
