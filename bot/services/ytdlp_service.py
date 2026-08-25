import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

import yt_dlp

from bot.config import DOWNLOADS_DIR, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB, BASE_DIR
from bot.utils.helpers import format_size, compress_video, cleanup_file

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
        self.cookies_file = BASE_DIR / "cookies.txt"

        # Agar .env da YOUTUBE_COOKIES o'zgaruvchisi berilgan bo'lsa
        raw_cookies = os.getenv("YOUTUBE_COOKIES", "").strip()
        if raw_cookies and not self.cookies_file.exists():
            try:
                self.cookies_file.write_text(raw_cookies, encoding="utf-8")
                logger.info(".env dagi YOUTUBE_COOKIES faylga saqlandi.")
            except Exception as e:
                logger.warning("YOUTUBE_COOKIES ni yozishda xatolik: %s", e)

    def _get_ydl_options(self, output_template: str, cookie_browser: Optional[str] = None) -> Dict[str, Any]:
        """Barcha platformalar uchun universal va ishonchli yt-dlp sozlamalari."""
        opts = {
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 30,
            'geo_bypass': True,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }

        # Agar cookies.txt mavjud bo'lsa
        if self.cookies_file.exists() and self.cookies_file.stat().st_size > 0:
            opts['cookiefile'] = str(self.cookies_file)
        elif cookie_browser:
            opts['cookiesfrombrowser'] = (cookie_browser, None, None, None)

        return opts

    def _sync_download(self, url: str) -> DownloadResult:
        """Videoni diskka yuklab olish."""
        unique_id = str(uuid.uuid4())[:8]
        outtmpl = str(self.download_dir / f"video_{unique_id}_%(id)s.%(ext)s")

        # Birinchi urinish: standart options
        attempts = [None]
        # Agar cookies.txt bo'lmasa, Windows brauzerlaridan cookies olishga urinish
        if not (self.cookies_file.exists() and self.cookies_file.stat().st_size > 0):
            attempts.extend(["chrome", "edge", "firefox", "brave"])

        last_error = None

        for browser in attempts:
            ydl_opts = self._get_ydl_options(outtmpl, cookie_browser=browser)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        continue

                    if 'entries' in info and info['entries']:
                        info = info['entries'][0]

                    # Yuklangan fayl nomini aniqlash
                    file_path = None
                    req_downloads = info.get('requested_downloads')
                    if req_downloads and len(req_downloads) > 0:
                        potential_path = req_downloads[0].get('filepath')
                        if potential_path and Path(potential_path).exists():
                            file_path = Path(potential_path)

                    if not file_path:
                        filename = ydl.prepare_filename(info)
                        p_filename = Path(filename)
                        if p_filename.exists():
                            file_path = p_filename
                        else:
                            mp4_candidate = p_filename.with_suffix('.mp4')
                            if mp4_candidate.exists():
                                file_path = mp4_candidate

                    if not file_path or not file_path.exists():
                        matching_files = list(self.download_dir.glob(f"video_{unique_id}_*"))
                        if matching_files:
                            file_path = matching_files[0]
                        else:
                            continue

                    file_size = file_path.stat().st_size
                    duration = info.get('duration')
                    title = info.get('title') or "Video"
                    width = info.get('width')
                    height = info.get('height')
                    thumbnail_url = info.get('thumbnail')

                    # Agar video 50MB dan katta bo'lsa, avtomatik siqamiz
                    if file_size > MAX_FILE_SIZE_BYTES:
                        logger.info("Video hajmi 50MB dan katta (%s), siqish boshlanmoqda...", format_size(file_size))
                        compressed_path = self.download_dir / f"compressed_{unique_id}.mp4"
                        success = compress_video(file_path, compressed_path, target_size_mb=45, duration=duration)
                        if success:
                            cleanup_file(file_path)
                            file_path = compressed_path
                            file_size = file_path.stat().st_size
                            logger.info("Video muvaffaqiyatli siqildi: %s", format_size(file_size))
                        else:
                            return DownloadResult(
                                success=False,
                                file_path=file_path,
                                file_size=file_size,
                                error_message=(
                                    f"⚠️ Video hajmi juda katta ({format_size(file_size)}).\n"
                                    f"Telegram cheklovi (50 MB) tufayli uni yuborib bo'lmadi."
                                )
                            )

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

            except yt_dlp.utils.DownloadError as e:
                last_error = e
                # Agar oddiy urinish xato bersa, keyingi brauzer cookie urinishiga o'tamiz
                continue
            except Exception as e:
                last_error = e
                continue

        if last_error:
            error_str = str(last_error).lower()
            if "private" in error_str:
                return DownloadResult(success=False, error_message="🔒 Bu video yopiq (shaxsiy) hisobda joylashgan yoki maxfiy.")
            elif "sign in" in error_str or "login" in error_str or "age" in error_str:
                return DownloadResult(
                    success=False,
                    error_message=(
                        "🔞 <b>Ushbu video yosh cheklovi (18+) ostida!</b>\n\n"
                        "YouTube 18+ videolarni faqat balog'at yoshiga yetgan Google akkauntlar orqali ko'rishga ruxsat beradi.\n\n"
                        "💡 <i>Bunday videolarni yuklash uchun botga bir martalik <code>cookies.txt</code> faylini joylash zarur.</i>"
                    )
                )

        return DownloadResult(
            success=False,
            error_message="❌ Videoni yuklab bo'lmadi. Havola to'g'riligini yoki video mavjudligini tekshiring."
        )

    async def download_video(self, url: str) -> DownloadResult:
        """Asinxron tarzda videoni yuklab olish."""
        return await asyncio.to_thread(self._sync_download, url)
