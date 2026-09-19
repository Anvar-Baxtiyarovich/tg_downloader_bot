import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# .env faylini yuklash
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Deno va Node JS yo'llarini PATH ga qo'shish (Windows va Linux uchun)
user_home = Path.home()
deno_bin = user_home / ".deno" / "bin"
if deno_bin.exists():
    os.environ["PATH"] = str(deno_bin) + os.pathsep + os.environ.get("PATH", "")

# FFmpeg yo'llarini global tizim PATH ga qo'shish
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Faqat ruxsat berilgan foydalanuvchilar (agar ko'rsatilgan bo'lsa)
_raw_allowed_users = os.getenv("ALLOWED_USERS", "").strip()
if _raw_allowed_users:
    ALLOWED_USERS = set(int(uid.strip()) for uid in _raw_allowed_users.split(",") if uid.strip().isdigit())
else:
    ALLOWED_USERS = set()

# Vaqtinchalik yuklab olish papkasi
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Telegram Bot API fayl hajmi limiti (MB)
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
