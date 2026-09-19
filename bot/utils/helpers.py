import re
import os
import json
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# URL regex
URL_REGEX = re.compile(
    r'(https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|'
    r'https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9]+\.[^\s]{2,})'
)

def extract_url(text: str) -> Optional[str]:
    """Matndan birinchi uchragan URL manzilini ajratib oladi."""
    if not text:
        return None
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


def format_size(size_bytes: int) -> str:
    """Baytlarni odam o'qiy oladigan formatga o'tkazadi (KB, MB, GB)."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"


def format_duration(seconds: Optional[int]) -> str:
    """Soniyalarni mm:ss yoki hh:mm:ss formatga o'tkazadi."""
    if not seconds or seconds < 0:
        return "00:00"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def cleanup_file(file_path: Optional[Path]) -> None:
    """Faylni xavfsiz o'chiradi."""
    if not file_path:
        return
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info("Vaqtinchalik fayl tozalandi: %s", file_path)
    except Exception as e:
        logger.warning("Faylni o'chirishda xatolik yuz berdi: %s, xato: %s", file_path, e)


def get_video_streams_info(file_path: Path) -> Optional[Dict[str, Any]]:
    """Video fayldagi video va audio oqimlar ma'lumotini ffprobe orqali aniqlaydi."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin or not file_path or not file_path.exists():
        return None
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "stream=index,codec_type,codec_name",
        "-of", "json",
        str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        audio_codecs = [str(s.get("codec_name", "")).lower() for s in streams if s.get("codec_type") == "audio"]
        return {"has_video": has_video, "has_audio": bool(audio_codecs), "audio_codecs": audio_codecs}
    except Exception as e:
        logger.warning("ffprobe oqimlarni aniqlashda xatolik (%s): %s", file_path.name, e)
        return None


def ensure_telegram_compatible_audio(file_path: Path) -> Path:
    """
    Video audio oqimi Telegram pleyeriga mos kelishini ta'minlaydi.
    Agar audio Opus yoki boshqa qo'llab-quvvatlanmaydigan formatda bo'lsa,
    videoni qayta kodlamasdan (-c:v copy), faqat audioni AAC ga o'tkazadi.
    """
    if not file_path or not file_path.exists():
        return file_path

    info = get_video_streams_info(file_path)
    if not info:
        return file_path

    audio_codecs = info.get("audio_codecs", [])
    if not audio_codecs:
        logger.info("Faylda audio oqimi mavjud emas: %s", file_path.name)
        return file_path

    # Telegram uchun xavfsiz va to'liq qo'llab-quvvatlanadigan kodeklar (aac, mp3)
    if all(c in ["aac", "mp3"] for c in audio_codecs):
        return file_path

    logger.info("Mos kelmaydigan audio kodek (%s) aniqlandi, AAC ga o'tkazilmoqda: %s", audio_codecs, file_path.name)
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return file_path

    fixed_path = file_path.with_name(f"fixed_{file_path.name}")
    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(file_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(fixed_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120)
        if fixed_path.exists() and fixed_path.stat().st_size > 0:
            cleanup_file(file_path)
            fixed_path.rename(file_path)
            logger.info("Audio muvaffaqiyatli AAC ga o'tkazildi: %s", file_path.name)
            return file_path
    except Exception as e:
        logger.warning("Audio kodekini AAC ga o'tkazishda xatolik: %s", e)
        cleanup_file(fixed_path)

    return file_path


def compress_video(input_path: Path, output_path: Path, target_size_mb: int = 44, duration: Optional[int] = None) -> bool:
    """Agar video hajmi 50MB dan katta bo'lsa, ffmpeg yordamida Telegram limitiga moslab siqadi."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logger.warning("ffmpeg topilmadi, videoni siqib bo'lmaydi.")
        return False

    if not duration or duration <= 0:
        duration = 300  # Default 5 daqiqa deb hisoblaymiz

    # Target bitrate hisoblash (xavfsiz maqsad: 44 MB)
    total_bits = target_size_mb * 1024 * 1024 * 8
    audio_bitrate_kbps = 64 if duration > 600 else 96
    target_video_bps = (total_bits / duration) - (audio_bitrate_kbps * 1000)
    video_bitrate_kbps = max(int(target_video_bps / 1000), 50)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-b:v", f"{video_bitrate_kbps}k",
        "-maxrate", f"{int(video_bitrate_kbps * 1.2)}k",
        "-bufsize", f"{int(video_bitrate_kbps * 1.5)}k",
        "-vf", "scale=-2:'min(720,ih)'",
        "-preset", "veryfast",
        "-c:a", "aac",
        "-b:a", f"{audio_bitrate_kbps}k",
        "-movflags", "+faststart",
        str(output_path)
    ]

    try:
        logger.info("Video siqilmoqda: %s (target: %skbps)", input_path, video_bitrate_kbps)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=300)
        return output_path.exists() and output_path.stat().st_size <= (50 * 1024 * 1024)
    except Exception as e:
        logger.warning("Videoni siqishda xatolik: %s", e)
        return False
