import os
import re
import time
import logging
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from prompts import SYSTEM_PROMPT
from sheets import log_message

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1",
)

# Per-user conversation memory: {user_id: [messages]}
histories: dict[int, list] = {}


def clean_reply(text: str) -> str:
    # Strip markdown bold/italic that Telegram won't render
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Remove markdown headers
    text = re.sub(r'^#{1,3}\s+', '', text, flags=re.MULTILINE)
    # Replace banned ending questions with correct ones
    replacements = [
        (r'[Qq]aysi AP fan[a-z]* qiziq[a-z]*\?', 'Qaysi birini tanlaysiz?'),
        (r'[Qq]aysi fan[a-z]* qiziq[a-z]*\?', 'Qaysi birini tanlaysiz?'),
        (r'[Qq]aysi kurs[a-z]* qiziq[a-z]*\?', 'Qaysi birini tanlaysiz?'),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text.strip()


def get_reply(user_id: int, user_message: str) -> str:
    history = histories.get(user_id, [])
    history.append({"role": "user", "content": user_message})

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history[-20:],
                temperature=0.85,
                max_tokens=600,
            )
            reply = clean_reply(response.choices[0].message.content.strip())
            history.append({"role": "assistant", "content": reply})
            histories[user_id] = history
            return reply
        except Exception as e:
            logger.warning(f"DeepSeek attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                histories.pop(user_id, None)
                raise


async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    histories.pop(user_id, None)
    try:
        greeting = get_reply(
            user_id,
            "Yangi o'quvchi yoki ota-ona Telegram orqali murojaat qildi. Ularni Nilufar sifatida salom bilan kutib ol va suhbatni boshla.",
        )
        await update.message.reply_text(greeting)
    except Exception as e:
        logger.error(f"Start error: {e}")
        await update.message.reply_text(
            "Assalomu alaykum! SATMakon konsultanti Nilufar. SAT, AP va xorijiy universitetga kirish bo'yicha yordam bera olaman. Ismingizni bilsam bo'ladimi?"
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text

    if not user_text:
        return

    logger.info(f"User {user_id}: {user_text}")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = get_reply(user_id, user_text)
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        await update.message.reply_text("Bir soniya, javob berishda kechikdim. Qayta yozing.")
        return

    logger.info(f"Bot → {user_id}: {reply[:80]}...")
    await update.message.reply_text(reply)

    tg_user = update.effective_user
    try:
        log_message(
            username=tg_user.username,
            full_name=tg_user.full_name,
            user_id=tg_user.id,
            user_msg=user_text,
            bot_reply=reply,
        )
    except Exception as e:
        logger.warning(f"Sheets error: {e}")


async def reset(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    histories.pop(user_id, None)
    try:
        greeting = get_reply(
            user_id,
            "Yangi o'quvchi yoki ota-ona Telegram orqali murojaat qildi. Ularni Nilufar sifatida salom bilan kutib ol.",
        )
        await update.message.reply_text(greeting)
    except Exception as e:
        logger.error(f"Reset error: {e}")


async def admin_stats(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    total_users = len(histories)
    await update.message.reply_text(
        f"📊 Joriy sessiya statistikasi:\n"
        f"Faol foydalanuvchilar: {total_users} ta\n"
        f"Google Sheets'da to'liq tarix mavjud."
    )


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN topilmadi")
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY topilmadi")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("SATMakon Bot ishga tushdi (DeepSeek)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
