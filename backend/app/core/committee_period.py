from __future__ import annotations

from datetime import date

from app.models.committee import Committee


class CommitteePeriodError(ValueError):
    """تاريخ خارج فترة عمل اللجنة، أو محاولة إنشاء عنصر جديد بعد انتهائها — تُترجَم تلقائيًا إلى 400."""


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def assert_within_committee_period(committee: Committee, *, field_label: str, value: date) -> None:
    # اللجنة الدائمة بلا فترة (الهجرة 0037) — أي تاريخ مقبول.
    if committee.start_date is None or committee.end_date is None:
        return
    if value < committee.start_date or value > committee.end_date:
        raise CommitteePeriodError(
            f"{field_label} ({_fmt(value)}) يجب أن يقع ضمن فترة عمل اللجنة "
            f"({_fmt(committee.start_date)} - {_fmt(committee.end_date)})"
        )


def assert_committee_not_expired(committee: Committee, *, action_label: str) -> None:
    # lifecycle_state_today لا يرجع "ended" للجنة الدائمة أبدًا، فـend_date مضمون هنا.
    if committee.lifecycle_state_today == "ended" and committee.end_date is not None:
        raise CommitteePeriodError(
            f"لا يمكن {action_label} لأن فترة اللجنة انتهت بتاريخ {_fmt(committee.end_date)}"
        )
