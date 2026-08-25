import re
import os
import logging
from pathlib import Path
from typing import Optional

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
