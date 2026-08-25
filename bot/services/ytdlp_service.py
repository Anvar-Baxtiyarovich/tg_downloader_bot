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

    def _base_options(self, output_template: str) -> Dict[str, Any]:
        """Umumiy sozlamalar (barcha strategiyalar uchun)."""
        return {
            'format': (
                'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/'
                'best[height<=720][ext=mp4]/'
                'bestvideo[height<=720]+bestaudio/'
                'best[height<=720]/best'
            ),
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

    def _build_strategies(self, output_template: str) -> list:
        """
        Ikki bosqichli strategiya:
          1-bosqich: Android client, cookiessiz, webpage'ni o'tkazib yuborish.
                     Oddiy ommaviy videolarning 95%+ ini shu usulda muammosiz yuklab oladi.
          2-bosqich: Web client, cookies + ejs:github masofaviy challenge solver.
                     18+ yosh cheklovi qo'yilgan va himoyalangan videolar uchun.
        """
        strategies = []

        # --- 1-BOSQICH: Cookiessiz tezkor Android yuklovchi ---
        opts_android = self._base_options(output_template)
        opts_android['extractor_args'] = {
            'youtube': {
                'player_client': ['android'],
                'player_skip': ['webpage', 'configs'],
            }
        }
        strategies.append(("android (cookiessiz)", opts_android))

        # --- 2-BOSQICH: Cookies + EJS challenge solver ---
        opts_web_cookies = self._base_options(output_template)
        opts_web_cookies['remote_components'] = ['ejs:github']
        if self.cookies_file.exists() and self.cookies_file.stat().st_size > 0:
            opts_web_cookies['cookiefile'] = str(self.cookies_file)
        strategies.append(("web (cookies + ejs:github)", opts_web_cookies))

        return strategies

    def _find_downloaded_file(self, ydl, info, unique_id: str) -> Optional[Path]:
        """Yuklangan fayl yo'lini ishonchli aniqlash."""
        # 1. requested_downloads dan olish
        req_downloads = info.get('requested_downloads')
        if req_downloads:
            filepath = req_downloads[0].get('filepath')
            if filepath and Path(filepath).exists():
                return Path(filepath)

        # 2. prepare_filename dan
        filename = ydl.prepare_filename(info)
        p = Path(filename)
        if p.exists():
            return p
        mp4 = p.with_suffix('.mp4')
        if mp4.exists():
            return mp4

        # 3. glob bilan qidirish
        matches = sorted(self.download_dir.glob(f"video_{unique_id}_*"), key=lambda f: f.stat().st_mtime, reverse=True)
        return matches[0] if matches else None

    def _sync_download(self, url: str) -> DownloadResult:
        """Videoni ikki bosqichli strategiya bilan yuklab olish."""
        unique_id = str(uuid.uuid4())[:8]
        outtmpl = str(self.download_dir / f"video_{unique_id}_%(id)s.%(ext)s")

        strategies = self._build_strategies(outtmpl)
        last_error = None

        for name, ydl_opts in strategies:
            try:
                logger.info("Yuklash urinishi: %s", name)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        continue

                    if 'entries' in info and info['entries']:
                        info = info['entries'][0]

                    file_path = self._find_downloaded_file(ydl, info, unique_id)
                    if not file_path:
                        continue

                    file_size = file_path.stat().st_size
                    duration = info.get('duration')
                    title = info.get('title') or "Video"

                    # Hajmi 50 MB dan katta bo'lsa, avtomatik siqish
                    if file_size > MAX_FILE_SIZE_BYTES:
                        logger.info("Video hajmi 50MB dan katta (%s), siqish boshlanmoqda...", format_size(file_size))
                        compressed_path = self.download_dir / f"compressed_{unique_id}.mp4"
                        ok = compress_video(file_path, compressed_path, target_size_mb=45, duration=duration)
                        if ok:
                            cleanup_file(file_path)
                            file_path = compressed_path
                            file_size = file_path.stat().st_size
                        else:
                            return DownloadResult(
                                success=False, file_path=file_path, file_size=file_size,
                                error_message=f"⚠️ Video hajmi juda katta ({format_size(file_size)}). Telegram cheklovi (50 MB) tufayli yuborib bo'lmadi."
                            )

                    logger.info("Muvaffaqiyatli yuklandi (%s): %s [%s]", name, title, format_size(file_size))
                    return DownloadResult(
                        success=True,
                        title=title,
                        file_path=file_path,
                        thumbnail_url=info.get('thumbnail'),
                        duration=duration,
                        width=info.get('width'),
                        height=info.get('height'),
                        file_size=file_size,
                    )

            except yt_dlp.utils.DownloadError as e:
                last_error = e
                logger.warning("Strategiya [%s] muvaffaqiyatsiz: %s", name, str(e)[:120])
                continue
            except Exception as e:
                last_error = e
                logger.warning("Strategiya [%s] kutilmagan xato: %s", name, str(e)[:120])
                continue

        # Barcha strategiyalar muvaffaqiyatsiz bo'ldi
        if last_error:
            err = str(last_error).lower()
            if "private" in err:
                return DownloadResult(success=False, error_message="🔒 Bu video yopiq (shaxsiy) hisobda joylashgan yoki maxfiy.")
            if "sign in" in err or "login" in err or "age" in err:
                return DownloadResult(
                    success=False,
                    error_message="🔒 Ushbu videoni yuklab bo'lmadi. cookies.txt fayli eskirgan bo'lishi mumkin — uni yangilab, qayta urinib ko'ring."
                )

        return DownloadResult(
            success=False,
            error_message="❌ Videoni yuklab bo'lmadi. Havola to'g'riligini yoki video mavjudligini tekshiring."
        )

    async def download_video(self, url: str) -> DownloadResult:
        """Asinxron tarzda videoni yuklab olish."""
        return await asyncio.to_thread(self._sync_download, url)
