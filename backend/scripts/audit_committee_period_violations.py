"""
سكربت فحص فقط (Read-Only) — لا يُعدّل ولا يحذف أي بيانات إطلاقًا.

الهدف: قبل تفعيل "قاعدة فترة اللجنة" (2026-09-13)، فحص البيانات الحالية
بقاعدة البيانات الفعلية بحثًا عن أي اجتماع/مهمة/قرار (غير محذوف) تاريخه
يقع خارج فترة عمل اللجنة المرتبط بها (committees.start_date/end_date) —
حتى قبل وجود القاعدة الجديدة. يطبع تقريرًا فقط (العدد، النوع، اللجنة).

مستقل تمامًا عن app.* (لا يستورد أي نموذج SQLAlchemy) عمدًا — يعمل بأي
بيئة بايثون فيها asyncpg فقط (مطابقة القيد: Python 3.10 على جهاز
صاحبة المشروع لا يكفي لاستيراد app.main كاملة بسبب datetime.UTC).

يقرأ DATABASE_URL من backend/.env مباشرة وقت التشغيل فقط — لا يُطبَع
ولا يُخزَّن بأي مكان آخر.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import asyncpg


def _load_database_url() -> str:
    # الملف بـbackend/scripts/، و.env بـbackend/ (مستوى فوق) — راجعي
    # backend/scripts/backfill_pending_embeddings.py لنفس التخطيط.
    env_path = Path(__file__).resolve().parent.parent / ".env"
    text = env_path.read_text(encoding="utf-8")
    match = re.search(r"^DATABASE_URL=(.+)$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("DATABASE_URL غير موجود بملف .env")
    url = match.group(1).strip()
    # asyncpg.connect() يحتاج DSN قياسي (postgresql://)، لا "+asyncpg" الذي
    # تحتاجه SQLAlchemy فقط لاختيار الـdriver.
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


MEETINGS_QUERY = """
SELECT c.committee_id, c.name, c.start_date, c.end_date,
       m.meeting_id, m.title, (m.scheduled_at AT TIME ZONE 'UTC')::date AS item_date
FROM meetings m
JOIN committees c ON c.committee_id = m.committee_id
WHERE m.deleted_at IS NULL
  AND c.deleted_at IS NULL
  AND (
        (m.scheduled_at AT TIME ZONE 'UTC')::date < c.start_date
     OR (m.scheduled_at AT TIME ZONE 'UTC')::date > c.end_date
      )
ORDER BY c.name, m.scheduled_at;
"""

TASKS_QUERY = """
SELECT c.committee_id, c.name, c.start_date, c.end_date,
       t.task_id, t.title, t.start_date AS item_start, t.end_date AS item_end
FROM tasks t
JOIN committees c ON c.committee_id = t.committee_id
WHERE t.deleted_at IS NULL
  AND c.deleted_at IS NULL
  AND (t.start_date < c.start_date OR t.end_date > c.end_date)
ORDER BY c.name, t.start_date;
"""

DECISIONS_QUERY = """
SELECT c.committee_id, c.name, c.start_date, c.end_date,
       d.decision_id, d.title, d.start_date AS item_start, d.end_date AS item_end
FROM decisions d
JOIN committees c ON c.committee_id = d.committee_id
WHERE d.deleted_at IS NULL
  AND c.deleted_at IS NULL
  AND (d.start_date < c.start_date OR d.end_date > c.end_date)
ORDER BY c.name, d.start_date;
"""


async def main() -> None:
    dsn = _load_database_url()
    # statement_cache_size=0: مطلوب مع Supabase pooler (pgbouncer، transaction
    # pooling mode بمنفذ 6543) — تجنّب مشاكل الـprepared statements المعروفة.
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        meetings = await conn.fetch(MEETINGS_QUERY)
        tasks = await conn.fetch(TASKS_QUERY)
        decisions = await conn.fetch(DECISIONS_QUERY)
    finally:
        await conn.close()

    print("=" * 70)
    print("تقرير فحص: عناصر تاريخها خارج فترة اللجنة المرتبطة بها (قراءة فقط)")
    print("=" * 70)
    print(f"اجتماعات مخالفة: {len(meetings)}")
    print(f"مهام مخالفة:     {len(tasks)}")
    print(f"قرارات مخالفة:   {len(decisions)}")
    print(f"الإجمالي:        {len(meetings) + len(tasks) + len(decisions)}")
    print()

    def _print_rows(label: str, rows, item_id_key: str, date_desc):
        if not rows:
            return
        print(f"--- {label} ---")
        for r in rows:
            print(
                f"  لجنة: {r['name']} ({r['start_date']} -> {r['end_date']}) | "
                f"{label[:-1]}: {r['title']} [{date_desc(r)}] (id={r[item_id_key]})"
            )
        print()

    _print_rows(
        "اجتماعات", meetings, "meeting_id",
        lambda r: f"تاريخ الاجتماع: {r['item_date']}",
    )
    _print_rows(
        "مهام", tasks, "task_id",
        lambda r: f"من {r['item_start']} إلى {r['item_end']}",
    )
    _print_rows(
        "قرارات", decisions, "decision_id",
        lambda r: f"من {r['item_start']} إلى {r['item_end']}",
    )

    if not (meetings or tasks or decisions):
        print("لا توجد أي مخالفات — كل البيانات الحالية متوافقة أصلًا مع قاعدة فترة اللجنة.")

    print("=" * 70)
    print("ملاحظة: هذا فحص قراءة فقط — لم يُعدَّل أو يُحذف أي شيء بقاعدة البيانات.")


if __name__ == "__main__":
    asyncio.run(main())
