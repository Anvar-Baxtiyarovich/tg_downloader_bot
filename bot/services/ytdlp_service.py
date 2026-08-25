import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import yt_dlp

from bot.config import DOWNLOADS_DIR, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB
from bot.utils.helpers import format_size

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    success: bool
    title: Optional[str] = None
    file_path: Optional[Path] = None
    thumbnail_url: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: Optional[int] = None
    error_message: Optional[str] = None


class DownloaderService:
    def __init__(self):
        self.download_dir = DOWNLOADS_DIR

    def _get_ydl_options(self, output_template: str) -> Dict[str, Any]:
        """yt-dlp uchun optimal sozlamalar."""
        return {
            'format': 'best[ext=mp4][filesize<?50M]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'max_filesize': MAX_FILE_SIZE_BYTES,
            'socket_timeout': 30,
            'geo_bypass': True,
            # Instagram va YouTube uchun user-agent
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }

    def _sync_extract_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Video haqida metama'lumotlarni yuklab olmasdan olish."""
        opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 15,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            logger.error("Metama'lumot olishda xatolik: %s", e)
            return None

    def _sync_download(self, url: str) -> DownloadResult:
        """Videoni diskka yuklab olish (sinxron rejimda)."""
        unique_id = str(uuid.uuid4())[:8]
        outtmpl = str(self.download_dir / f"video_{unique_id}_%(id)s.%(ext)s")
        ydl_opts = self._get_ydl_options(outtmpl)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return DownloadResult(
                        success=False,
                        error_message="Video haqida ma'lumot topilmadi yoki havola noto'g'ri."
                    )

                # Agar playlist/entries bo'lsa, birinchi elementni olamiz
                if 'entries' in info and info['entries']:
                    info = info['entries'][0]

                # Yuklangan fayl nomini aniqlash
                filename = ydl.prepare_filename(info)
                file_path = Path(filename)

                # Ba'zida kengaytma o'zgarishi mumkin (.mkv -> .mp4)
                if not file_path.exists():
                    # Eng so'nggi yuklangan mos faylni qidiramiz
                    matching_files = list(self.download_dir.glob(f"video_{unique_id}_*"))
                    if matching_files:
                        file_path = matching_files[0]
                    else:
                        return DownloadResult(
                            success=False,
                            error_message="Yuklangan video fayli diskda topilmadi."
                        )

                file_size = file_path.stat().st_size

                # Hajm 50MB dan katta bo'lsa
                if file_size > MAX_FILE_SIZE_BYTES:
                    return DownloadResult(
                        success=False,
                        file_path=file_path,
                        file_size=file_size,
                        error_message=(
                            f"⚠️ Video hajmi {format_size(file_size)} ekan.\n"
                            f"Telegram botlari orqali faqat {MAX_FILE_SIZE_MB} MB gacha bo'lgan "
                            f"videolarni yuborish mumkin."
                        )
                    )

                title = info.get('title') or "Video"
                duration = info.get('duration')
                width = info.get('width')
                height = info.get('height')
                thumbnail_url = info.get('thumbnail')

                return DownloadResult(
                    success=True,
                    title=title,
                    file_path=file_path,
                    thumbnail_url=thumbnail_url,
                    duration=duration,
                    width=width,
                    height=height,
                    file_size=file_size
                )

        except yt_dlp.utils.MaxDownloadsReached:
            return DownloadResult(success=False, error_message="Yuklashlar limiti oshib ketdi.")
        except yt_dlp.utils.DownloadError as e:
            error_str = str(e).lower()
            if "file is larger than max-filesize" in error_str or "max_filesize" in error_str:
                return DownloadResult(
                    success=False,
                    error_message=f"⚠️ Video hajmi {MAX_FILE_SIZE_MB} MB dan katta. Telegram cheklovi tufayli yuklab bo'lmaydi."
                )
            elif "private" in error_str:
                return DownloadResult(
                    success=False,
                    error_message="🔒 Bu video yopiq (shaxsiy) hisobda joylashgan yoki maxfiy."
                )
            elif "sign in" in error_str or "login" in error_str:
                return DownloadResult(
                    success=False,
                    error_message="🔒 Ushbu videoni ko'rish uchun akkauntga kirish talab etiladi."
                )
            else:
                logger.error("yt-dlp DownloadError: %s", e)
                return DownloadResult(
                    success=False,
                    error_message="❌ Videoni yuklab bo'lmadi. Havola to'g'riligini yoki video mavjudligini tekshiring."
                )
        except Exception as e:
            logger.exception("Kutilmagan xatolik: %s", e)
            return DownloadResult(
                success=False,
                error_message=f"❌ Xatolik yuz berdi: {str(e)[:100]}"
            )

    async def download_video(self, url: str) -> DownloadResult:
        """Asinxron tarzda videoni yuklab olish (boshqa foydalanuvchilarni to'xtatib qo'ymaslik uchun)."""
        return await asyncio.to_thread(self._sync_download, url)

    async def get_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Asinxron tarzda video metama'lumotlarini olish."""
        return await asyncio.to_thread(self._sync_extract_info, url)
