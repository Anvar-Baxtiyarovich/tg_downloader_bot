FROM python:3.12-slim

# Kerakli tizim paketlari: ffmpeg va nodejs (YouTube JS challenge solver uchun)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Deno o'rnatish (YouTube JS challenge solver uchun)
RUN curl -fsSL https://deno.land/install.sh | sh && \
    cp /root/.deno/bin/deno /usr/local/bin/deno

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
