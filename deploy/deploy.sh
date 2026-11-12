#!/usr/bin/env bash
# =====================================================================
# deploy/deploy.sh
# الهدف: النشر التلقائي على سيرفر بارع (طلب لاما 2026-11-12) — يُشغَّل من
# GitHub Actions بعد كل دمج في main (.github/workflows/deploy.yml)، ويمكن
# تشغيله يدويًا على السيرفر بنفس النتيجة.
#
# المسؤولية:
#   1. يسحب آخر main (fast-forward فقط — لا يمسح أي تعديل محلي).
#   2. يقارن بآخر نسخة نُشرت بنجاح (.deployed-sha) ويعيد بناء ما تغيّر فقط:
#        backend/  → backend   |   frontend/ → frontend
#        docker-compose.prod.yml → كل الخدمات المبنية
#      قاعدة البيانات وRedis لا تُعاد أبدًا من هنا.
#   3. يتحقق أن النظام يعمل بعد النشر (/health عبر Nginx → الخادم الخلفي).
#   4. يحذف الصور القديمة غير المستخدمة (توفير مساحة القرص).
#
# migrations (قرار مقصود): لا تُطبَّق تلقائيًا أبدًا لأنها تغيّر البيانات.
#   لو وُجد ملف جديد في db/migrations يتوقف السكربت **قبل** إعادة البناء
#   (النسخة الحالية تبقى شغالة كما هي) ويطبع الملفات وأمر تطبيقها. بعد
#   تطبيقها يدويًا شغّلي:  ./deploy/deploy.sh --migrations-applied
#
# الاستخدام:  ./deploy/deploy.sh [--migrations-applied]
# =====================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yml")
STATE_FILE="$APP_DIR/.deployed-sha"
LOCK_FILE="$APP_DIR/.deploy.lock"
MIGRATIONS_APPLIED=false
[[ "${1:-}" == "--migrations-applied" ]] && MIGRATIONS_APPLIED=true

log() { echo "[deploy $(date -u +%H:%M:%S)] $*"; }

cd "$APP_DIR"

# نشر واحد في نفس الوقت (دمجان متتاليان بسرعة لا يتداخلان).
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "نشر آخر يعمل الآن — تم الإلغاء."
  exit 1
fi

# أول تشغيل: النسخة الموجودة حاليًا هي المنشورة.
[[ -f "$STATE_FILE" ]] || git rev-parse HEAD >"$STATE_FILE"
before="$(cat "$STATE_FILE")"
log "آخر نسخة منشورة: ${before:0:7}"

git fetch --quiet origin main
target="$(git rev-parse origin/main)"
log "آخر نسخة على GitHub: ${target:0:7}"

if [[ "$before" == "$target" ]]; then
  log "لا يوجد تحديث جديد."
  exit 0
fi

# فحص الـ migrations **قبل** سحب الكود: لو توقفنا يبقى الكود والحاويات على
# النسخة القديمة، وإعادة التشغيل بعد التطبيق تلقى نفس الفرق.
new_migrations="$(git diff --name-only --diff-filter=A "$before" "$target" -- db/migrations | sort || true)"
if [[ -n "$new_migrations" && "$MIGRATIONS_APPLIED" != true ]]; then
  log "⚠️  يوجد migrations جديدة — توقف النشر (النسخة الحالية ما زالت تعمل بدون أي تغيير):"
  echo "$new_migrations" | sed 's/^/    - /'
  echo
  echo "  ١. راجعيها:  git show origin/main:<المسار>"
  echo "  ٢. طبّقيها بالترتيب على السيرفر:"
  echo "$new_migrations" | while read -r f; do
    echo "     git show origin/main:$f | ${COMPOSE[*]} exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'"
  done
  echo "  ٣. ثم:  ./deploy/deploy.sh --migrations-applied"
  exit 2
fi

git merge --ff-only --quiet "$target"
after="$target"
log "تم سحب الكود: ${after:0:7}"

changed="$(git diff --name-only "$before" "$after")"
services=()
if grep -q '^docker-compose.prod.yml$' <<<"$changed"; then
  services=(backend frontend)
else
  grep -q '^backend/' <<<"$changed" && services+=(backend)
  grep -q '^frontend/' <<<"$changed" && services+=(frontend)
fi

if [[ ${#services[@]} -eq 0 ]]; then
  log "التغييرات لا تخص الخادم الخلفي ولا الواجهة — لا حاجة لإعادة البناء."
else
  log "إعادة بناء: ${services[*]}"
  "${COMPOSE[@]}" up -d --build "${services[@]}"
fi

log "فحص الحالة..."
for i in $(seq 1 30); do
  if curl -fsS --max-time 5 http://localhost/health >/dev/null 2>&1; then
    echo "$after" >"$STATE_FILE"
    docker image prune -f >/dev/null 2>&1 || true
    log "✅ تم النشر بنجاح (${after:0:7})."
    exit 0
  fi
  sleep 3
done

log "❌ النظام لا يستجيب بعد النشر — آخر سجلات الخادم الخلفي:"
"${COMPOSE[@]}" logs --tail=60 backend || true
exit 1
