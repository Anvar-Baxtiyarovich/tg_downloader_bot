import logging
from aiogram import Router, types, F
from aiogram.types import FSInputFile

from bot.config import ALLOWED_USERS
from bot.services.ytdlp_service import DownloaderService
from bot.utils.helpers import extract_url, format_size, format_duration, cleanup_file

logger = logging.getLogger(__name__)
router = Router(name="downloader_router")
downloader_service = DownloaderService()


@router.message(F.text)
async def handle_link(message: types.Message):
    """Foydalanuvchi yuborgan xabardagi video havolasini qayta ishlash."""
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
        # Agar oddiy matn bo'lsa
        await message.reply(
            "ℹ️ Iltimos, video havolasini (linkini) yuboring.\n"
            "Masalan: Instagram Reels, YouTube Shorts yoki video havolasi.",
            parse_mode="HTML"
        )
        return

    # Jarayon boshlanganligi haqida xabar
    status_msg = await message.reply("🔍 <b>Havola tekshirilmoqda va yuklanmoqda...</b> ⏳", parse_mode="HTML")
    download_result = None

    try:
        # Telegram "video yuklamoqda" holatini ko'rsatish
        await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_video")

        # Videoni yuklab olish
        download_result = await downloader_service.download_video(url)

        if not download_result.success:
            await status_msg.edit_text(
                download_result.error_message or "❌ Videoni yuklab bo'lmadi.",
                parse_mode="HTML"
            )
            return

        if not download_result.file_path or not download_result.file_path.exists():
            await status_msg.edit_text(
                "❌ Video fayli saqlanmadi. Qayta urinib ko'ring.",
                parse_mode="HTML"
            )
            return

        # Holatni yangilash
        await status_msg.edit_text("📤 <b>Video Telegramga yuborilmoqda...</b>", parse_mode="HTML")
        await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_video")

        # Video fayli
        video_input = FSInputFile(str(download_result.file_path))

        # Caption tayyorlash
        title_text = download_result.title or "Video"
        if len(title_text) > 800:
            title_text = title_text[:797] + "..."

        caption_parts = [f"🎬 <b>{title_text}</b>\n"]
        if download_result.duration:
            caption_parts.append(f"⏱ Davomiyligi: <b>{format_duration(download_result.duration)}</b>")
        if download_result.file_size:
            caption_parts.append(f"📦 Hajmi: <b>{format_size(download_result.file_size)}</b>")

        caption = "\n".join(caption_parts)

        # Videoni Telegramga jo'natish
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
            # Video formatida jo'natib bo'lmasa, fayl (document) sifatida jo'natish
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
        # Vaqtinchalik faylni xavfsiz o'chirish
        if download_result and download_result.file_path:
            cleanup_file(download_result.file_path)
