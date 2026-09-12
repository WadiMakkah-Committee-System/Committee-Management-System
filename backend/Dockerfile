# نظام إدارة اللجان والاجتماعات — Backend (FastAPI + Socket.IO)
# تحديث 2026-09-12: أول Dockerfile للمشروع — لنشر الباك-إند على Railway
# (أو أي استضافة تدعم Dockerfile قياسي). راجعي app/main.py للتأكد من إن
# نقطة التشغيل الفعلية هي socket_app (تغليف Socket.IO لتطبيق FastAPI)،
# وليس app مباشرة — تفصيل موثّق بتعليق app/main.py نفسه.

FROM python:3.11-slim

WORKDIR /app

# gcc: احتياطًا لبعض الحزم (مثل bcrypt) اللي أحيانًا تحتاج تُبنى من
# المصدر على معماريات/نسخ بايثون معينة لو ما توفر wheel جاهز.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway (وأغلب منصات PaaS) تمرر رقم البورت عبر متغير البيئة PORT —
# القيمة الافتراضية 8000 للتشغيل المحلي عبر docker run بدون PORT.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:socket_app --host 0.0.0.0 --port ${PORT}"]
