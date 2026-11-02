"""
الهدف:
نموذج SQLAlchemy ORM لتسجيل الاجتماع صوتيًا + تحويله لمسودة بالذكاء
الاصطناعي (صلاحيات meetings.record_audio / meetings.draft.summarize /
meetings.draft.view / meetings.summary.view — مزروعة أصلًا بكتالوج
الصلاحيات منذ 0006، هذا أول استخدام فعلي لها). يطابق بنية
db/migrations/0025_meeting_recordings_and_drafts.sql — راجعي رأسه لكل
الاجتهادات الموثّقة (منفصل عن فئة "minutes" الرسمية، بدون Workflow
اعتماد/توقيع بهذي المرحلة).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MeetingRecording(Base):
    __tablename__ = "meeting_recordings"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id"), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    recorder: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class MeetingDraftStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class MeetingDraftSource(str, enum.Enum):
    """مصدر المسودة (db/migrations/0041_meetings_teams_integration.sql):
    audio_upload = تسجيل صوتي مرفوع من المتصفح (اجتماع حضوري، recording_id
    إلزامي)؛ teams_transcript = تفريغ Teams الرسمي (اجتماع عن بعد،
    recording_id فارغ) — العلاقة مفروضة بقاعدة البيانات عبر CHECK
    chk_meeting_drafts_source_recording."""

    audio_upload = "audio_upload"
    teams_transcript = "teams_transcript"


class MeetingDraft(Base):
    __tablename__ = "meeting_drafts"

    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.meeting_id"), nullable=False, unique=True
    )
    # اختياري منذ 0041 — إلزامي فقط لو source=audio_upload (راجعي MeetingDraftSource).
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_recordings.recording_id"), nullable=True
    )
    source: Mapped[MeetingDraftSource] = mapped_column(
        SAEnum(MeetingDraftSource, name="meeting_draft_source", native_enum=True),
        nullable=False,
        server_default=MeetingDraftSource.audio_upload.value,
    )

    status: Mapped[MeetingDraftStatus] = mapped_column(
        SAEnum(MeetingDraftStatus, name="meeting_draft_status", native_enum=True),
        nullable=False,
        server_default=MeetingDraftStatus.pending.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # راجعي MEETING_DRAFT_PROMPT بـapp/core/gemini_client.py للـSchema
    # الدقيق المطابق لهذه الأعمدة (JSONB بدل أعمدة منفصلة — البنية غنية
    # ومتداخلة، ولا حاجة موثّقة للاستعلام داخل حقولها بهذي المرحلة).
    full_transcript: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    decisions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    action_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    key_points: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    open_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    compliance_notes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    generated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    recording: Mapped["MeetingRecording | None"] = relationship(lazy="selectin")
    generator: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
