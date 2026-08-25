# 🎬 Shaxsiy Telegram Video Downloader Bot

Ushbu bot **YouTube** (Shorts, to'liq videolar), **Instagram** (Reels, postlar) va boshqa ijtimoiy tarmoqlardan videolarni hech qanday **reklama**, **homiylik kanallariga majburiy obuna bo'lishlarsiz** to'g'ridan-to'g'ri Telegram orqali yuklab olish uchun yaratilgan.

---

## 🚀 Ishga Tushirish Qo'llanmasi

### 1. Telegram Bot yaratish va Token olish
1. Telegramda [@BotFather](https://t.me/BotFather) botiga kiring.
2. `/newbot` buyrug'ini yuboring.
3. Botingizga nom va `@username` bering (masalan: `my_personal_downloader_bot`).
4. `@BotFather` sizga **API Token** beradi (masalan: `7123456789:AAH...`).

---

### 2. Loyihani Sozlash

1. Loyiha papkasidagi `.env` faylini oching va bot tokenini yozing:
   ```env
   BOT_TOKEN=7123456789:AAH...sizning_tokeningiz
   ```

2. *(Ixtiyoriy)* Agar botdan **faqat o'zingiz va do'stlaringiz** foydalanishini istasangiz:
   - Botga `/myid` yuborib ID raqamingizni oling.
   - `.env` faylidagi `ALLOWED_USERS` qatoriga ID larni vergul bilan kiriting:
     ```env
     ALLOWED_USERS=123456789,987654321
     ```
   - Agar bu qator bo'sh qoldirilsa, botdan istalgan kishi bemalol foydalana oladi.

---

### 3. Kutubxonalarni O'rnatish va Ishga Tushirish

Terminalda (PowerShell yoki CMD) quyidagi buyruqlarni ketma-ket bajaring:

```bash
# 1. Virtual muhit yaratish
python -m venv venv

# 2. Virtual muhitni faollashtirish (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# (Agar CMD ishlatsangiz: .\venv\Scripts\activate.bat)

# 3. Kerakli kutubxonalarni o'rnatish
pip install -r requirements.txt

# 4. Botni ishga tushirish
python main.py
```

---

## 🎯 Botdan Foydalanish

1. Botga kiring va `/start` tugmasini bosing.
2. Instagram yoki YouTube'dan istalgan video havolasini botga yuboring.
3. Bot videoni yuklab, sizga toza va original holda yuboradi!

---

## 📁 Loyiha Tuzilmasi

- `bot/config.py` — Sozlamalar va .env fayli bilan ishlash
- `bot/handlers/start.py` — `/start`, `/help`, `/myid` komandalari
- `bot/handlers/downloader.py` — Havolalarni qabul qilish va videolarni Telegramga jo'natish
- `bot/services/ytdlp_service.py` — `yt-dlp` orqali videoni yuklab olish xizmati
- `bot/utils/helpers.py` — URL ajratib olish va yordamchi funksiyalar
- `main.py` — Botni yurgizuvchi asosiy fayl
