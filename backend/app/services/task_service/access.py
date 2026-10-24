"""
تحقق الصلاحية بوحدة المهام (إعادة هيكلة 2026-10-24) — النمط الهجين المشترك
في app/services/committee_access.py، وهنا فقط قواعد المهام الخاصة: تقييد
العضو العادي بمهامه المسندة له (العرض/تحديث الحالة)، وعضوية المسؤول.
"""

import uuid

from app.models.committee import Committee
from app.models.task import Task
from app.models.user import User
from app.services.committee_access import CommitteeAccess, system_scope_allows
from app.services.task_service.errors import TaskForbiddenError, TaskValidationError


async def _require_access(
    access: CommitteeAccess, committee: Committee, code: str, message: str
) -> None:
    if not await access.has(committee, code):
        raise TaskForbiddenError(message)


def _is_chair(actor: User, committee: Committee) -> bool:
    return committee.chair_user_id == actor.user_id


async def _require_object_scoped_access(
    access: CommitteeAccess,
    committee: Committee,
    task: Task,
    code: str,
    message: str,
    own_only_message: str,
) -> None:
    """
    فحص صلاحية بمرحلتين: (1) هل يملك الكود أصلًا (نظام أو لجنة)، (2) إن كان
    امتلاكه عبر عضوية اللجنة (لا نطاق نظام) وهو ليس رئيس اللجنة — يُقيَّد
    بمهامه المسندة له هو تحديدًا فقط. رئيس اللجنة أو صاحب نطاق نظام
    (all/department) غير مقيَّدين بهذا الشرط الإضافي.
    """
    actor = access.actor
    if system_scope_allows(actor, committee, code):
        return
    if not await access.has(committee, code):
        raise TaskForbiddenError(message)
    if not _is_chair(actor, committee) and task.assignee_user_id != actor.user_id:
        raise TaskForbiddenError(own_only_message)


def _committee_member_ids(committee: Committee) -> set[uuid.UUID]:
    """كل من يصلح إسناد مهمة له بهذه اللجنة — رئيسها وأعضاؤها."""
    ids = {m.user_id for m in committee.members}
    if committee.chair_user_id is not None:
        ids.add(committee.chair_user_id)
    return ids


def _validate_assignee_membership(committee: Committee, assignee_user_id: uuid.UUID) -> None:
    if assignee_user_id not in _committee_member_ids(committee):
        raise TaskValidationError("لا يمكن إسناد المهمة لمستخدم ليس عضوًا في اللجنة المرتبطة")
