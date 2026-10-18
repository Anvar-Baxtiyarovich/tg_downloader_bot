from aiogram import Router, types, F
from aiogram.enums import ChatType
from aiogram.filters import CommandStart, Command

router = Router(name="start_router")
# Start, help va myid buyruqlari faqat shaxsiy chatda ishlaydi, guruhlarda jim turadi
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    """/start buyrug'i uchun javob (faqat shaxsiy chatda)."""
    user_name = message.from_user.first_name if message.from_user else "Foydalanuvchi"
    text = (
        f"Assalomu alaykum, <b>{user_name}</b>! 👋\n\n"
        f"🎬 <b>Media Yuklovchi Botga xush kelibsiz!</b>\n\n"
        f"Bu bot orqali hech qanday reklama yoki majburiy obunalarsiz "
        f"video va rasmlarni to'g'ridan-to'g'ri yuklab olishingiz mumkin.\n\n"
        f"📌 <b>Qo'llab-quvvatlanadigan platformalar:</b>\n"
        f"• <b>Instagram</b> (Reels, Rasmlar, Karusel/Albom postlar)\n"
        f"• <b>TikTok</b> (Suv belgisiz original videolar)\n"
        f"• <b>YouTube</b> (Shorts, Videolar)\n"
        f"• <b>Pinterest</b> (Video va rasmlar)\n"
        f"• <b>Twitter / X</b> (Videolar va postlar)\n"
        f"• <b>Facebook</b> (Reels va videolar)\n"
        f"• <b>Bilibili</b> (HD videolar)\n\n"
        f"🚀 <i>Shunchaki media havolasini (linkini) yuboring!</i>"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    """/help buyrug'i uchun javob (faqat shaxsiy chatda)."""
    text = (
        "📖 <b>Botdan foydalanish qo'llanmasi:</b>\n\n"
        "1. Instagram, YouTube, TikTok, Pinterest, Twitter/X yoki Facebook ilovasidan post yoki videoning <b>ulashish (share)</b> tugmasini bosing.\n"
        "2. <b>Nusxa olish (copy link)</b> qilib, havolani botga yoki bot bor guruhga yuboring.\n"
        "3. Bot media (video, rasm yoki butun albom)ni yuklab, sizga yoki guruhga javob (reply) qilib yuboradi.\n\n"
        "ℹ️ <i>Telegram boti orqali maksimal 50 MB gacha bo'lgan videolarni yuborish mumkin. Undan katta videolar avtomatik ravishda siqiladi.</i>\n\n"
        "🆔 Sizning Telegram ID: <code>{user_id}</code>"
    ).format(user_id=message.from_user.id if message.from_user else "Noma'lum")
    await message.reply(text, parse_mode="HTML")


@router.message(Command("myid"))
async def cmd_myid(message: types.Message):
    """Foydalanuvchi o'z Telegram ID sini bilishi uchun (faqat shaxsiy chatda)."""
    user_id = message.from_user.id if message.from_user else "Topilmadi"
    await message.answer(
        f"🆔 Sizning Telegram ID raqamingiz: <code>{user_id}</code>\n\n"
        f"<i>Agar botni faqat do'stlaringiz uchun cheklamoqchi bo'lsangiz, "
        f"ushbu ID ni .env dagi ALLOWED_USERS ro'yxatiga qo'shishingiz mumkin.</i>",
        parse_mode="HTML"
    )
