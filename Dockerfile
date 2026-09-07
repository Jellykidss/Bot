FROM python:3.10-slim

WORKDIR /app

# ติดตั้งระบบไลบรารีพื้นฐานสำหรับรองรับเสียงของ Discord (PyNaCl)
RUN apt-get update && apt-get install -y \
    libffi-dev \
    libnacl-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# ติดตั้ง Python Packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ดทั้งหมดเข้ามาใน Container
COPY . .

# รันบอท
CMD ["python", "bot.py"]
