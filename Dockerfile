FROM python:3.12-slim

# Kerakli tizim paketlari va ffmpeg ni o'rnatish
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bog'liqliklarni o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Loyiha kodlarini nusxalash
COPY . .

# Yuklab olish papkasini yaratish
RUN mkdir -p downloads

# Botni ishga tushirish
CMD ["python", "main.py"]
