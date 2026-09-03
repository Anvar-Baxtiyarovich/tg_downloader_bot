import asyncio
import http.cookiejar
import json
import logging
import os
import re
import shutil
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List

# MUHIM: config birinchi import qilinadi — u Deno PATH'ini sozlaydi
from bot.config import DOWNLOADS_DIR, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB, BASE_DIR

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

import yt_dlp

try:
    from yt_dlp.extractor.instagram import InstagramIE
    # Instagram rasmli postlarida 'There is no video' xatosi bermasligi uchun
    InstagramIE.raise_no_formats = lambda self, msg, expected=False, video_id=None: None
except Exception:
    pass

from bot.utils.helpers import format_size, compress_video, cleanup_file

logger = logging.getLogger(__name__)


@dataclass
class MediaItem:
    media_type: str  # 'photo' yoki 'video'
    file_path: Path
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: Optional[int] = None


@dataclass
class DownloadResult:
    success: bool
    media_type: str = "video"  # 'video', 'photo', 'album'
    title: Optional[str] = None
    caption: Optional[str] = None
    items: Optional[List[MediaItem]] = None
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
                'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/'
                'best[height<=1080][ext=mp4]/'
                'bestvideo[height<=1080]+bestaudio/'
                'best[height<=1080]/best'
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
        opts_android['remote_components'] = ['ejs:github']
        opts_android['extractor_args'] = {
            'youtube': {
                'player_client': ['android'],
                'player_skip': ['webpage', 'configs'],
            }
        }
        strategies.append(("android (cookiessiz)", opts_android))

        # --- 2-BOSQICH: Cookies + EJS challenge solver (18+ uchun) ---
        if self.cookies_file.exists() and self.cookies_file.stat().st_size > 0:
            opts_web_cookies = self._base_options(output_template)
            opts_web_cookies['remote_components'] = ['ejs:github']
            opts_web_cookies['cookiefile'] = str(self.cookies_file)
            strategies.append(("web (cookies + ejs:github)", opts_web_cookies))

        # --- 3-BOSQICH: Cookiessiz web + EJS (zaxira) ---
        opts_web_noauth = self._base_options(output_template)
        opts_web_noauth['remote_components'] = ['ejs:github']
        strategies.append(("web (cookiessiz + ejs:github)", opts_web_noauth))

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

    def _is_instagram_url(self, url: str) -> bool:
        """Havola Instagram tarmog'iga tegishli ekanligini tekshirish."""
        return bool(re.search(r'https?://(?:www\.)?instagram\.com/', url, re.IGNORECASE))

    def _is_bilibili_url(self, url: str) -> bool:
        """Havola Bilibili tarmog'iga tegishli ekanligini tekshirish."""
        return bool(re.search(r'https?://(?:www\.)?(?:bilibili\.com|b23\.tv)/', url, re.IGNORECASE))

    def _is_tiktok_url(self, url: str) -> bool:
        """Havola TikTok tarmog'iga tegishli ekanligini tekshirish."""
        return bool(re.search(r'https?://(?:www\.|(?:vm|vt)\.)?tiktok\.com/', url, re.IGNORECASE))

    def _is_wechat_channels_url(self, url: str) -> bool:
        """Havola WeChat Channels (视频号) tarmog'iga tegishli ekanligini tekshirish."""
        return bool(re.search(r'channels\.weixin\.qq\.com|weixin\.qq\.com/sph', url, re.IGNORECASE))

    def _get_bilibili_cookies(self) -> List[Any]:
        """Bilibili WAF 412 xatosini aylanib o'tish uchun buvid3 va b_nut cookie-larini avtomatik olish."""
        try:
            cj = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            req = urllib.request.Request(
                'https://www.bilibili.com/',
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/124.0.0.0 Safari/537.36'
                    ),
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            opener.open(req, timeout=8)
            return list(cj)
        except Exception as e:
            logger.warning("Bilibili cookie-larini olishda xatolik: %s", e)
            return []

    def _download_http_file(self, url: str, dest_path: Path, referer: Optional[str] = None) -> bool:
        """HTTP orqali faylni bevosita oqim (stream) tarzida xavfsiz yuklab olish."""
        try:
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
            }
            if referer:
                headers['Referer'] = referer

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, 'wb') as f:
                shutil.copyfileobj(resp, f)

            return dest_path.exists() and dest_path.stat().st_size > 0
        except Exception as e:
            logger.warning("Faylni yuklab olishda xatolik (%s): %s", dest_path.name, e)
            cleanup_file(dest_path)
            return False

    def _download_instagram(self, url: str) -> Optional[DownloadResult]:
        """Instagram postlarini (yakka foto, karusel/albom yoki video) yuklab olish."""
        unique_id = str(uuid.uuid4())[:8]
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                'Accept-Language': 'en-US,en;q=0.9',
            }
        }
        if self.cookies_file.exists() and self.cookies_file.stat().st_size > 0:
            ydl_opts['cookiefile'] = str(self.cookies_file)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ie = ydl.get_info_extractor('Instagram')
                info = ie.extract(url)

            if not info:
                return None

            uploader = info.get('uploader') or info.get('channel') or "Instagram"
            desc = info.get('description') or info.get('title') or ""
            caption = desc.strip() if desc else f"Post by @{uploader}"
            title = info.get('title') or f"Post by {uploader}"

            is_playlist = info.get('_type') == 'playlist' or bool(info.get('entries'))

            # 1. Karusel / Albom (bir nechta rasm yoki video)
            if is_playlist:
                entries = info.get('entries') or []
                if not entries:
                    return None

                items: List[MediaItem] = []
                for idx, entry in enumerate(entries):
                    item_formats = entry.get('formats') or []
                    item_thumbs = entry.get('thumbnails') or []

                    if item_formats:
                        # Video element
                        best_format = max(
                            item_formats,
                            key=lambda f: (f.get('width') or 0) * (f.get('height') or 0)
                        )
                        v_url = best_format.get('url')
                        if not v_url:
                            continue
                        v_path = self.download_dir / f"ig_video_{unique_id}_{idx}.mp4"
                        if self._download_http_file(v_url, v_path, referer="https://www.instagram.com/"):
                            f_size = v_path.stat().st_size
                            duration = entry.get('duration')
                            if f_size > MAX_FILE_SIZE_BYTES:
                                c_path = self.download_dir / f"compressed_{unique_id}_{idx}.mp4"
                                if compress_video(v_path, c_path, target_size_mb=45, duration=duration):
                                    cleanup_file(v_path)
                                    v_path = c_path
                                    f_size = v_path.stat().st_size
                            items.append(MediaItem(
                                media_type="video",
                                file_path=v_path,
                                duration=duration,
                                width=best_format.get('width'),
                                height=best_format.get('height'),
                                file_size=f_size
                            ))
                    elif item_thumbs:
                        # Rasm element (oxirgi thumbnail eng yuqori sifatli hisoblanadi)
                        p_url = item_thumbs[-1].get('url')
                        if not p_url:
                            continue
                        p_path = self.download_dir / f"ig_photo_{unique_id}_{idx}.jpg"
                        if self._download_http_file(p_url, p_path, referer="https://www.instagram.com/"):
                            items.append(MediaItem(
                                media_type="photo",
                                file_path=p_path,
                                width=item_thumbs[-1].get('width'),
                                height=item_thumbs[-1].get('height'),
                                file_size=p_path.stat().st_size
                            ))

                if not items:
                    return None

                if len(items) == 1:
                    first = items[0]
                    return DownloadResult(
                        success=True,
                        media_type=first.media_type,
                        title=title,
                        caption=caption,
                        file_path=first.file_path,
                        duration=first.duration,
                        width=first.width,
                        height=first.height,
                        file_size=first.file_size
                    )

                return DownloadResult(
                    success=True,
                    media_type="album",
                    title=title,
                    caption=caption,
                    items=items
                )

            # 2. Yakka media (Single post)
            formats = info.get('formats') or []
            thumbnails = info.get('thumbnails') or []

            # Agar bu yakka rasm bo'lsa
            if not formats and thumbnails:
                p_url = thumbnails[-1].get('url')
                if p_url:
                    p_path = self.download_dir / f"ig_photo_{unique_id}.jpg"
                    if self._download_http_file(p_url, p_path, referer="https://www.instagram.com/"):
                        return DownloadResult(
                            success=True,
                            media_type="photo",
                            title=title,
                            caption=caption,
                            file_path=p_path,
                            width=thumbnails[-1].get('width'),
                            height=thumbnails[-1].get('height'),
                            file_size=p_path.stat().st_size
                        )

            # Agar bu yakka video bo'lsa
            if formats:
                best_format = max(
                    formats,
                    key=lambda f: (f.get('width') or 0) * (f.get('height') or 0)
                )
                v_url = best_format.get('url')
                if v_url:
                    v_path = self.download_dir / f"ig_video_{unique_id}.mp4"
                    if self._download_http_file(v_url, v_path, referer="https://www.instagram.com/"):
                        f_size = v_path.stat().st_size
                        duration = info.get('duration')
                        if f_size > MAX_FILE_SIZE_BYTES:
                            c_path = self.download_dir / f"compressed_{unique_id}.mp4"
                            if compress_video(v_path, c_path, target_size_mb=45, duration=duration):
                                cleanup_file(v_path)
                                v_path = c_path
                                f_size = v_path.stat().st_size
                        return DownloadResult(
                            success=True,
                            media_type="video",
                            title=title,
                            caption=caption,
                            file_path=v_path,
                            duration=duration,
                            width=best_format.get('width'),
                            height=best_format.get('height'),
                            file_size=f_size
                        )

            return None

        except Exception as e:
            logger.warning("Instagram yuklash maxsus metodi xatolik berdi: %s. Zaxira usulga o'tilmoqda...", e)
            return None

    def _download_bilibili(self, url: str) -> Optional[DownloadResult]:
        """Bilibili videolarini WAF 412 cheklovlarisiz to'g'ridan-to'g'ri mobil/HTML5 API orqali yuklab olish."""
        unique_id = str(uuid.uuid4())[:8]
        try:
            # 1. Havola qisqa bo'lsa (masalan b23.tv), uni to'liq manzilga ochib olamiz
            resolved_url = url
            if 'b23.tv' in url:
                try:
                    req_red = urllib.request.Request(
                        url,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    )
                    with urllib.request.urlopen(req_red, timeout=8) as resp_red:
                        resolved_url = resp_red.geturl()
                except Exception as e:
                    logger.warning("b23.tv yo'naltirishini olishda xatolik: %s", e)

            # 2. bvid ni ajratib olish
            bvid_match = re.search(r'(BV[a-zA-Z0-9]+)', resolved_url, re.IGNORECASE)
            if not bvid_match:
                logger.warning("Bilibili BVID topilmadi: %s", resolved_url)
                return None
            bvid = bvid_match.group(1)

            # 3. m.bilibili.com orqali sarlavha, muallif, poster va davomiylikni olish (412 bermaydi)
            title = f"Bilibili Video ({bvid})"
            caption = None
            thumbnail = None
            duration = None
            try:
                m_req = urllib.request.Request(
                    f"https://m.bilibili.com/video/{bvid}",
                    headers={
                        'User-Agent': (
                            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
                            'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
                        ),
                        'Referer': 'https://m.bilibili.com/',
                    }
                )
                with urllib.request.urlopen(m_req, timeout=10) as m_resp:
                    html = m_resp.read().decode('utf-8', errors='ignore')
                    title_m = re.search(r'property="og:title" content="(.*?)"', html)
                    if title_m:
                        title = title_m.group(1).strip()
                    desc_m = re.search(r'property="og:description" content="(.*?)"', html)
                    if desc_m:
                        caption = desc_m.group(1).strip()
                    img_m = re.search(r'property="og:image" content="(.*?)"', html)
                    if img_m:
                        thumbnail = img_m.group(1).strip()
                    dur_m = re.search(r'property="video:duration" content="(\d+)"', html)
                    if dur_m:
                        duration = int(dur_m.group(1))
            except Exception as e:
                logger.warning("m.bilibili.com metadatalarini olishda xatolik: %s", e)

            # 4. cid ni pagelist API orqali olish
            cid = None
            p_req = urllib.request.Request(
                f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}",
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://www.bilibili.com/',
                }
            )
            with urllib.request.urlopen(p_req, timeout=10) as p_resp:
                p_data = json.loads(p_resp.read().decode())
                if p_data.get('code') == 0 and p_data.get('data'):
                    cid = p_data['data'][0].get('cid')
                    if not duration and p_data['data'][0].get('duration'):
                        duration = p_data['data'][0].get('duration')
                    part_title = p_data['data'][0].get('part')
                    if part_title and title.startswith("Bilibili Video"):
                        title = part_title

            if not cid:
                logger.warning("Bilibili cid topilmadi: %s", bvid)
                return None

            # 5. playurl API orqali MP4 oqim havolasini olish (qn=64 yoki qn=32)
            video_stream_url = None
            for qn in [64, 32]:
                play_url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn={qn}&type=&otype=json&platform=html5"
                play_req = urllib.request.Request(
                    play_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': 'https://www.bilibili.com/',
                    }
                )
                with urllib.request.urlopen(play_req, timeout=10) as play_resp:
                    play_data = json.loads(play_resp.read().decode())
                    if play_data.get('code') == 0 and play_data.get('data', {}).get('durl'):
                        durl = play_data['data']['durl'][0]
                        video_stream_url = durl.get('url')
                        stream_size = durl.get('size', 0)
                        if stream_size <= MAX_FILE_SIZE_BYTES:
                            break
                        if qn == 64:
                            continue
                        break

            if not video_stream_url:
                logger.warning("Bilibili video stream URL topilmadi: %s", bvid)
                return None

            # 6. Videoni yuklab olish
            dest_path = self.download_dir / f"bili_{unique_id}.mp4"
            ok = self._download_http_file(video_stream_url, dest_path, referer="https://www.bilibili.com/")
            if not ok or not dest_path.exists():
                logger.warning("Bilibili video faylini yuklab bo'lmadi: %s", bvid)
                cleanup_file(dest_path)
                return None

            file_size = dest_path.stat().st_size
            # 7. Agar hajm 50 MB dan katta bo'lsa, siqish
            if file_size > MAX_FILE_SIZE_BYTES:
                logger.info("Bilibili video hajmi 50MB dan katta (%s), siqish boshlanmoqda...", format_size(file_size))
                compressed_path = self.download_dir / f"compressed_{unique_id}.mp4"
                compressed_ok = compress_video(dest_path, compressed_path, target_size_mb=45, duration=duration)
                if compressed_ok:
                    cleanup_file(dest_path)
                    dest_path = compressed_path
                    file_size = dest_path.stat().st_size
                else:
                    return DownloadResult(
                        success=False, file_path=dest_path, file_size=file_size,
                        error_message=f"⚠️ Video hajmi juda katta ({format_size(file_size)}). Telegram botlar uchun cheklov 50 MB."
                    )

            logger.info("Bilibili muvaffaqiyatli yuklandi: %s [%s]", title, format_size(file_size))
            return DownloadResult(
                success=True,
                media_type="video",
                title=title,
                caption=caption or title,
                file_path=dest_path,
                thumbnail_url=thumbnail,
                duration=duration,
                file_size=file_size,
            )

        except Exception as e:
            logger.warning("Bilibili yuklashda xatolik: %s", e)
            return None

    def _sync_download(self, url: str, extra_cookies: Optional[List[Any]] = None, referer: Optional[str] = None) -> DownloadResult:
        """Videoni ikki bosqichli strategiya bilan yuklab olish."""
        unique_id = str(uuid.uuid4())[:8]
        outtmpl = str(self.download_dir / f"video_{unique_id}_%(id)s.%(ext)s")

        strategies = self._build_strategies(outtmpl)
        last_error = None

        for name, ydl_opts in strategies:
            try:
                # Agar maxsus Referer sarlavhasi berilgan bo'lsa (masalan, Bilibili yoki TikTok uchun)
                if referer:
                    ydl_opts.setdefault('http_headers', {})['Referer'] = referer

                logger.info("Yuklash urinishi: %s", name)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # Agar dinamik cookie-lar (masalan, Bilibili buvid3/b_nut) berilgan bo'lsa
                    if extra_cookies:
                        for c in extra_cookies:
                            ydl.cookiejar.set_cookie(c)

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
                        media_type="video",
                        title=title,
                        caption=info.get('description') or title,
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
                return DownloadResult(success=False, error_message="🔒 Bu media yopiq (shaxsiy) hisobda joylashgan yoki maxfiy.")
            if "sign in" in err or "login" in err or "age-restricted" in err or " age " in err:
                return DownloadResult(
                    success=False,
                    error_message="🔒 Ushbu kontentni yuklab bo'lmadi. cookies.txt fayli eskirgan bo'lishi mumkin — uni yangilab, qayta urinib ko'ring."
                )

        return DownloadResult(
            success=False,
            error_message="❌ Mediani yuklab bo'lmadi. Havola to'g'riligini yoki post mavjudligini tekshiring."
        )

    def _sync_process(self, url: str) -> DownloadResult:
        """Havolani tahlil qilib, mos platforma strategiyasi orqali yuklash."""
        # 1. WeChat Channels tekshiruvi (Tencent DRM / faqat ilova ichidagi cheklov)
        if self._is_wechat_channels_url(url):
            return DownloadResult(
                success=False,
                error_message=(
                    "⚠️ <b>WeChat Channels (视频号) qo'llab-quvvatlanmaydi.</b>\n\n"
                    "WeChat video kanallari Tencent tomonidan faqat WeChat mobil ilovasi ichida "
                    "shifrlangan (DRM) ko'rinishda ochiladi va ularni to'g'ridan-to'g'ri ochiq havola orqali yuklab bo'lmaydi."
                )
            )

        # 2. Instagram (rasmlar, karusellar va videolar)
        if self._is_instagram_url(url):
            logger.info("Instagram havolasi aniqlandi, maxsus yuklovchi ishga tushirilmoqda: %s", url)
            ig_result = self._download_instagram(url)
            if ig_result and ig_result.success:
                logger.info("Instagram media muvaffaqiyatli yuklandi: type=%s", ig_result.media_type)
                return ig_result
            logger.info("Instagram maxsus yuklovchi natija bermadi, umumiy usulga urinilmoqda...")

        # 3. Bilibili (To'g'ridan-to'g'ri WAF-siz Mobile/HTML5 API, natija bermasa zaxira yt-dlp)
        if self._is_bilibili_url(url):
            logger.info("Bilibili havolasi aniqlandi, maxsus yuklovchi ishga tushirilmoqda: %s", url)
            bili_result = self._download_bilibili(url)
            if bili_result and bili_result.success:
                return bili_result
            logger.info("Bilibili maxsus yuklovchi natija bermadi, zaxira yt-dlp usuliga urinilmoqda...")
            bili_cookies = self._get_bilibili_cookies()
            return self._sync_download(url, extra_cookies=bili_cookies, referer="https://www.bilibili.com/")

        # 4. TikTok (Suv belgisiz video yuklash)
        if self._is_tiktok_url(url):
            logger.info("TikTok havolasi aniqlandi: %s", url)
            return self._sync_download(url, referer="https://www.tiktok.com/")

        # 5. Boshqa barcha platformalar (YouTube, Pinterest va b.)
        return self._sync_download(url)

    async def download_video(self, url: str) -> DownloadResult:
        """Asinxron tarzda media (video, rasm yoki albom) yuklab olish."""
        return await asyncio.to_thread(self._sync_process, url)

    async def download_media(self, url: str) -> DownloadResult:
        """download_video uchun qulay taxallus (alias)."""
        return await self.download_video(url)
