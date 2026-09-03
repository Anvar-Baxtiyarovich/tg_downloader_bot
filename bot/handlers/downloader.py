import asyncio
import html
import logging
from aiogram import Router, types, F
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo

from bot.config import ALLOWED_USERS
from bot.services.ytdlp_service import DownloaderService, DownloadResult
from bot.utils.helpers import extract_url, format_size, format_duration, cleanup_file

logger = logging.getLogger(__name__)
router = Router(name="downloader_router")
downloader_service = DownloaderService()


def _build_caption(result: DownloadResult) -> str:
    """Xabar uchun toza va HTML xavfsiz caption tayyorlash."""
    raw_text = result.caption or result.title or "Media"
    if len(raw_text) > 700:
        raw_text = raw_text[:697] + "..."
    escaped_text = html.escape(raw_text)

    caption_parts = []
    if result.media_type == "photo":
        caption_parts.append(f"📸 <b>{escaped_text}</b>\n")
        if result.file_size:
            caption_parts.append(f"📦 Hajmi: <b>{format_size(result.file_size)}</b>")
    elif result.media_type == "album":
        count = len(result.items) if result.items else 0
        caption_parts.append(f"🖼 <b>{escaped_text}</b> ({count} ta media)\n")
        total_size = sum(item.file_size or 0 for item in (result.items or []))
        if total_size > 0:
            caption_parts.append(f"📦 Umumiy hajm: <b>{format_size(total_size)}</b>")
    else:  # video
        caption_parts.append(f"🎬 <b>{escaped_text}</b>\n")
        if result.duration:
            caption_parts.append(f"⏱ Davomiyligi: <b>{format_duration(result.duration)}</b>")
        if result.file_size:
            caption_parts.append(f"📦 Hajmi: <b>{format_size(result.file_size)}</b>")

    return "\n".join(caption_parts)


@router.message(F.text)
async def handle_link(message: types.Message):
    """Foydalanuvchi yuborgan xabardagi media havolasini qayta ishlash."""
    user_id = message.from_user.id if message.from_user else 0

    # Whitelist tekshiruvi (agar ALLOWED_USERS belgilangan bo'lsa)
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await message.reply(
            "🔒 <b>Kechirasiz, ushbu bot faqat shaxsiy foydalanish uchun mo'ljallangan.</b>\n\n"
            f"Sizning Telegram ID: <code>{user_id}</code>\n"
            "Bot egasidan ruxsat olishingiz mumkin.",
            parse_mode="HTML"
        )
        return

    # Matndan URL ajratib olish
    url = extract_url(message.text)
    if not url:
        await message.reply(
            "ℹ️ Iltimos, media havolasini (linkini) yuboring.\n"
            "Masalan: Instagram (Reels, Post, Karusel) yoki YouTube (Shorts, Video).",
            parse_mode="HTML"
        )
        return

    # Jarayon boshlanganligi haqida xabar
    status_msg = await message.reply("🔍 <b>Havola tekshirilmoqda va yuklanmoqda...</b> ⏳", parse_mode="HTML")
    download_result = None

    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

        # Mediani yuklab olish
        download_result = await downloader_service.download_video(url)

        if not download_result.success:
            await status_msg.edit_text(
                download_result.error_message or "❌ Mediani yuklab bo'lmadi.",
                parse_mode="HTML"
            )
            return

        caption = _build_caption(download_result)

        # 1. ALBOM (Karusel) YUBORISH
        if download_result.media_type == "album":
            items = download_result.items or []
            if not items:
                await status_msg.edit_text("❌ Albom fayllari topilmadi.", parse_mode="HTML")
                return

            await status_msg.edit_text("📤 <b>Albom Telegramga yuborilmoqda...</b>", parse_mode="HTML")
            await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")

            media_group = []
            for i, item in enumerate(items):
                item_input = FSInputFile(str(item.file_path))
                item_caption = caption if i == 0 else None

                if item.media_type == "video":
                    media_group.append(InputMediaVideo(
                        media=item_input,
                        caption=item_caption,
                        parse_mode="HTML",
                        duration=item.duration,
                        width=item.width,
                        height=item.height
                    ))
                else:
                    media_group.append(InputMediaPhoto(
                        media=item_input,
                        caption=item_caption,
                        parse_mode="HTML"
                    ))

            # Telegram media group limiti: maksimal 10 ta element
            chunks = [media_group[j:j + 10] for j in range(0, len(media_group), 10)]
            for idx, chunk in enumerate(chunks):
                if idx > 0:
                    await asyncio.sleep(1)
                await message.reply_media_group(media=chunk)

        # 2. YAKKA RASM YUBORISH
        elif download_result.media_type == "photo":
            if not download_result.file_path or not download_result.file_path.exists():
                await status_msg.edit_text("❌ Rasm fayli saqlanmadi.", parse_mode="HTML")
                return

            await status_msg.edit_text("📤 <b>Rasm Telegramga yuborilmoqda...</b>", parse_mode="HTML")
            await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")

            photo_input = FSInputFile(str(download_result.file_path))
            try:
                await message.reply_photo(
                    photo=photo_input,
                    caption=caption,
                    parse_mode="HTML"
                )
            except Exception as photo_err:
                logger.warning("reply_photo muvaffaqiyatsiz, hujjat sifatida yuborilmoqda: %s", photo_err)
                await message.reply_document(
                    document=photo_input,
                    caption=caption,
                    parse_mode="HTML"
                )

        # 3. YAKKA VIDEO YUBORISH
        else:
            if not download_result.file_path or not download_result.file_path.exists():
                await status_msg.edit_text("❌ Video fayli saqlanmadi.", parse_mode="HTML")
                return

            await status_msg.edit_text("📤 <b>Video Telegramga yuborilmoqda...</b>", parse_mode="HTML")
            await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_video")

            video_input = FSInputFile(str(download_result.file_path))
            try:
                await message.reply_video(
                    video=video_input,
                    caption=caption,
                    duration=download_result.duration,
                    width=download_result.width,
                    height=download_result.height,
                    supports_streaming=True,
                    parse_mode="HTML"
                )
            except Exception as video_err:
                logger.warning("reply_video muvaffaqiyatsiz, hujjat sifatida yuborilmoqda: %s", video_err)
                await message.reply_document(
                    document=video_input,
                    caption=caption,
                    parse_mode="HTML"
                )

        # Holat xabarini o'chirish (tozalik uchun)
        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.exception("Xabarni qayta ishlashda kutilmagan xatolik: %s", e)
        try:
            await status_msg.edit_text(
                f"❌ Xatolik yuz berdi: {str(e)[:150]}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        # Vaqtinchalik fayllarni xavfsiz tozalash
        if download_result:
            if download_result.file_path:
                cleanup_file(download_result.file_path)
            if download_result.items:
                for it in download_result.items:
                    if it.file_path:
                        cleanup_file(it.file_path)
