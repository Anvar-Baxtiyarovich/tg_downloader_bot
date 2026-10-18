import asyncio
import html
import logging
from typing import Optional
from aiogram import Router, types, F
from aiogram.enums import ChatType
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo, ChatMemberUpdated

from bot.config import ALLOWED_USERS
from bot.services.ytdlp_service import DownloaderService, DownloadResult
from bot.utils.helpers import (
    extract_url,
    format_size,
    format_duration,
    cleanup_file,
    is_supported_media_url,
)

logger = logging.getLogger(__name__)
router = Router(name="downloader_router")
downloader_service = DownloaderService()


def _build_caption(result: DownloadResult, sender: Optional[types.User] = None, is_group: bool = False) -> str:
    """Xabar uchun toza va HTML xavfsiz caption tayyorlash."""
    raw_text = result.caption or result.title or "Media"
    if len(raw_text) > 600:
        raw_text = raw_text[:597] + "..."
    escaped_text = html.escape(raw_text)

    caption_parts = []
    sender_line = ""
    if is_group and sender:
        sender_name = f"@{sender.username}" if sender.username else html.escape(sender.full_name)
        sender_line = f"👤 Yuboruvchi: {sender_name}\n"

    if result.media_type == "photo":
        caption_parts.append(f"📸 <b>{escaped_text}</b>\n")
        if sender_line:
            caption_parts.append(sender_line)
        if result.file_size:
            caption_parts.append(f"📦 Hajmi: <b>{format_size(result.file_size)}</b>")
    elif result.media_type == "album":
        count = len(result.items) if result.items else 0
        caption_parts.append(f"🖼 <b>{escaped_text}</b> ({count} ta media)\n")
        if sender_line:
            caption_parts.append(sender_line)
        total_size = sum(item.file_size or 0 for item in (result.items or []))
        if total_size > 0:
            caption_parts.append(f"📦 Umumiy hajm: <b>{format_size(total_size)}</b>")
    else:  # video
        caption_parts.append(f"🎬 <b>{escaped_text}</b>\n")
        if sender_line:
            caption_parts.append(sender_line)
        meta_parts = []
        if result.duration:
            meta_parts.append(f"⏱ <b>{format_duration(result.duration)}</b>")
        if result.file_size:
            meta_parts.append(f"📦 <b>{format_size(result.file_size)}</b>")
        if meta_parts:
            caption_parts.append(" | ".join(meta_parts))

    return "\n".join(caption_parts)


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_bot_added_to_group(event: ChatMemberUpdated):
    """Bot guruhga qo'shilganda qutlov va qo'llanma xabarini yuborish."""
    if event.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    welcome_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men guruhga yuborilgan media havolalarni <b>avtomatik tarzda yuklab beruvchi botman</b>. 🎬\n\n"
        "📌 <b>Qo'llab-quvvatlanadigan platformalar:</b>\n"
        "• <b>Instagram</b> (Reels, Post, Karusel albomlar)\n"
        "• <b>TikTok</b> (Suv belgisiz videolar)\n"
        "• <b>YouTube</b> (Shorts va videolar)\n"
        "• <b>Pinterest</b> (Video va rasmlar)\n"
        "• <b>Twitter / X</b> (Videolar va rasmlar)\n"
        "• <b>Facebook</b> (Reels va videolar)\n\n"
        "🚀 <i>Guruhga shunchaki havola yuboring — bot videoni xabarga javob (reply) qilib yuboradi!</i>\n\n"
        "⚠️ <b>Guruh adminlari diqqatiga:</b>\n"
        "Bot barcha a'zolar yuborgan xabarlarni ko'ra olishi uchun:\n"
        "1️⃣ Botni guruhda <b>Admin</b> qiling, YOKI\n"
        "2️⃣ @BotFather'da bot sozlamalariga kirib: <code>Bot Settings -> Group Privacy -> Turn off</code> qiling."
    )
    try:
        await event.bot.send_message(
            chat_id=event.chat.id,
            text=welcome_text,
            parse_mode="HTML"
        )
        logger.info(f"Bot yangi guruhga qo'shildi: {event.chat.title} ({event.chat.id})")
    except Exception as e:
        logger.warning(f"Guruhga qutlov yuborishda xatolik: {e}")


@router.message(F.text | F.caption)
async def handle_link(message: types.Message):
    """Foydalanuvchi yuborgan xabardagi media havolasini qayta ishlash."""
    is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    user_id = message.from_user.id if message.from_user else 0
    text = message.text or message.caption or ""

    # Matndan URL ajratib olish
    url = extract_url(text)

    # Faqat qo'llab-quvvatlanadigan media/video havolalariga javob beramiz.
    # Agar xabarda havola bo'lmasa yoki u qo'llab-quvvatlanadigan media havola bo'lmasa,
    # guruhda ham, shaxsiy chatda ham umuman hech qanday javob qaytarmaymiz (to'liq e'tiborsiz qoldiramiz).
    if not url or not is_supported_media_url(url):
        return

    # Shaxsiy chatda whitelist tekshiruvi (agar ALLOWED_USERS belgilangan bo'lsa)
    if not is_group and ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await message.reply(
            "🔒 <b>Kechirasiz, ushbu bot faqat shaxsiy foydalanish uchun mo'ljallangan.</b>\n\n"
            f"Sizning Telegram ID: <code>{user_id}</code>\n"
            "Bot egasidan ruxsat olishingiz mumkin.",
            parse_mode="HTML"
        )
        return

    # Jarayon boshlanganligi haqida xabar (status)
    status_msg = await message.reply("⏳ <b>Yuklanmoqda...</b>", parse_mode="HTML")
    download_result = None

    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

        # Mediani yuklab olish
        download_result = await downloader_service.download_video(url)

        if not download_result.success:
            err_text = download_result.error_message or "❌ Mediani yuklab bo'lmadi."
            if is_group:
                # Guruhda xatolik xabari 15 soniyadan keyin o'chiriladi (guruh toza turishi uchun)
                try:
                    await status_msg.edit_text(err_text, parse_mode="HTML")
                    await asyncio.sleep(15)
                    await status_msg.delete()
                except Exception:
                    pass
            else:
                await status_msg.edit_text(err_text, parse_mode="HTML")
            return

        caption = _build_caption(download_result, sender=message.from_user, is_group=is_group)

        # 1. ALBOM (Karusel) YUBORISH
        if download_result.media_type == "album":
            items = download_result.items or []
            if not items:
                await status_msg.edit_text("❌ Albom fayllari topilmadi.", parse_mode="HTML")
                return

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

            await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")

            photo_input = FSInputFile(str(download_result.file_path))
            try:
                await message.reply_photo(
                    photo=photo_input,
                    caption=caption,
                    parse_mode="HTML"
                )
            except Exception as photo_err:
                logger.warning(f"reply_photo muvaffaqiyatsiz, hujjat sifatida yuborilmoqda: {photo_err}")
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
                logger.warning(f"reply_video muvaffaqiyatsiz, hujjat sifatida yuborilmoqda: {video_err}")
                await message.reply_document(
                    document=video_input,
                    caption=caption,
                    parse_mode="HTML"
                )

        # Holat xabarini o'chirish (asl havola xabari qoladi, yuklanmoqda xabari o'chiriladi)
        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"Xabarni qayta ishlashda kutilmagan xatolik: {e}")
        try:
            err_text = f"❌ Xatolik yuz berdi: {str(e)[:150]}"
            if is_group:
                await status_msg.edit_text(err_text, parse_mode="HTML")
                await asyncio.sleep(15)
                await status_msg.delete()
            else:
                await status_msg.edit_text(err_text, parse_mode="HTML")
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
