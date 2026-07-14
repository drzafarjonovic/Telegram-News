# ============================================================
#  Telegram-News — Enterprise v2.0 konteyneri
#  Autoscaling / monitoring uchun (Railway, Fly.io, K8s, Docker Compose).
# ============================================================
FROM python:3.11-slim

# OCR uchun tesseract (IXTIYORIY — faqat OCR_ENABLED=true bo'lsa kerak).
# Kerak bo'lmasa, xarajatni kamaytirish uchun bu qatorni olib tashlashingiz mumkin.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # OCR kutubxonalari (ixtiyoriy). OCR ishlatmasangiz izohga oling.
    && pip install --no-cache-dir pytesseract Pillow

COPY . .

# Prometheus metrikslari uchun port
EXPOSE 9101

CMD ["python", "main.py"]
