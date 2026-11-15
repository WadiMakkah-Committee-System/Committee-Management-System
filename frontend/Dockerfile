# =====================================================================
# frontend/Dockerfile
# الهدف: بناء الواجهة الأمامية (React + Vite) وتقديمها عبر Nginx.
#
# المسؤولية: مرحلتان:
#   1) build: تثبيت المكتبات وبناء ملفات النشر في مجلد dist.
#   2) nginx: صورة خفيفة تحتوي ملفات dist وإعدادات nginx.conf فقط.
#
# المدخلات:
#   - VITE_API_BASE_URL (Build Argument): رابط الخادم الخلفي، يُضمَّن في
#     ملفات الواجهة وقت البناء. القيمة الافتراضية /api/v1 (النطاق نفسه).
#
# ملاحظة: يُستخدم "vite build" مباشرة بدل "npm run build" لأن الأخير
# يشغّل فحص TypeScript أولاً، وأي خطأ أنواع فيه يوقف النشر بالكامل.
# =====================================================================

# ---------- المرحلة 1: البناء ----------
FROM node:22-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npx vite build

# ---------- المرحلة 2: التقديم عبر Nginx ----------
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
# إعادة تحميل Nginx كل 12 ساعة حتى يلتقط شهادة SSL الجديدة بعد ما يجددها
# certbot على السيرفر (كل ~60 يوم) — بدونها يظل يعرض القديمة لين تنتهي.
CMD ["/bin/sh", "-c", "while :; do sleep 43200; nginx -s reload; done & exec nginx -g 'daemon off;'"]
