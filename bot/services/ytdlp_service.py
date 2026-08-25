import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception as e:
    pass

import yt_dlp

from bot.config import DOWNLOADS_DIR, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB, BASE_DIR
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
        self.cookies_file = BASE_DIR / "cookies.txt"

    def _get_ydl_options(
        self,
        output_template: str,
        client: str = "android",
        player_skip: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """yt-dlp uchun har qanday holatda yuklay oladigan universal sozlamalar."""
        if player_skip is None:
            player_skip = ['webpage', 'configs']

        opts = {
            'format': 'best[ext=mp4][filesize<?50M]/bestvideo[ext=mp4][filesize<?50M]+bestaudio[ext=m4a]/best[filesize<?50M]/18/22/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'max_filesize': MAX_FILE_SIZE_BYTES,
            'socket_timeout': 30,
            'geo_bypass': True,
            'extractor_args': {
                'youtube': {
                    'player_client': [client],
                    'player_skip': player_skip,
                }
            },
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }

        # Agar cookies.txt fayli bo'lsa (yopiq/18+ videolar uchun)
        if self.cookies_file.exists() and self.cookies_file.stat().st_size > 0:
            opts['cookiefile'] = str(self.cookies_file)

        return opts

    def _sync_download(self, url: str) -> DownloadResult:
        """Videoni diskka har qanday holatda yuklab olish."""
        unique_id = str(uuid.uuid4())[:8]
        outtmpl = str(self.download_dir / f"video_{unique_id}_%(id)s.%(ext)s")

        # Turli xil strategiyalar (har qanday blokirovkani aylanib o'tish uchun)
        strategies = [
            {"client": "android", "player_skip": ["webpage", "configs"]},
            {"client": "android", "player_skip": []},
            {"client": "mweb", "player_skip": []},
            {"client": "web", "player_skip": []}
        ]

        last_error = None

        for strategy in strategies:
            client = strategy["client"]
            player_skip = strategy["player_skip"]
            ydl_opts = self._get_ydl_options(outtmpl, client=client, player_skip=player_skip)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        continue

                    # Agar playlist/entries bo'lsa, birinchi elementni olamiz
                    if 'entries' in info and info['entries']:
                        info = info['entries'][0]

                    # Aniq yuklangan fayl yo'lini topish
                    file_path = None
                    req_downloads = info.get('requested_downloads')
                    if req_downloads and len(req_downloads) > 0:
                        potential_path = req_downloads[0].get('filepath')
                        if potential_path and Path(potential_path).exists():
                            file_path = Path(potential_path)

                    if not file_path:
                        filename = ydl.prepare_filename(info)
                        if Path(filename).exists():
                            file_path = Path(filename)

                    if not file_path or not file_path.exists():
                        matching_files = list(self.download_dir.glob(f"video_{unique_id}_*"))
                        if matching_files:
                            file_path = matching_files[0]
                        else:
                            continue

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

                    logger.info("Video muvaffaqiyatli yuklandi: %s (client: %s)", title, client)

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
                last_error = e
                error_str = str(e).lower()
                if "file is larger than max-filesize" in error_str or "max_filesize" in error_str:
                    return DownloadResult(
                        success=False,
                        error_message=f"⚠️ Video hajmi {MAX_FILE_SIZE_MB} MB dan katta. Telegram cheklovi tufayli yuklab bo'lmaydi."
                    )
                logger.warning("Strategy (client: %s) muvaffaqiyatsiz bo'ldi, keyingi strategiyaga o'tilmoqda: %s", client, e)
                continue
            except Exception as e:
                last_error = e
                logger.warning("Strategy (client: %s) kutilmagan xato: %s", client, e)
                continue

        if last_error:
            error_str = str(last_error).lower()
            if "private" in error_str:
                return DownloadResult(success=False, error_message="🔒 Bu video yopiq (shaxsiy) hisobda joylashgan yoki maxfiy.")
            elif "sign in" in error_str or "login" in error_str:
                return DownloadResult(
                    success=False,
                    error_message=(
                        "🔒 Ushbu video yosh cheklovi (18+) yoki maxfiyligi sababli akkauntga kirishni talab qilmoqda."
                    )
                )

        return DownloadResult(
            success=False,
            error_message="❌ Videoni yuklab bo'lmadi. Havola to'g'riligini yoki video mavjudligini tekshiring."
        )

    async def download_video(self, url: str) -> DownloadResult:
        """Asinxron tarzda videoni yuklab olish."""
        return await asyncio.to_thread(self._sync_download, url)
