import os
import logging
from dotenv import load_dotenv
from supabase import create_client
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import mimetypes

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

PHOTO, LOCATION, COMMENT = range(3)
user_data = {}

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь фото или видео саранчи.")
    return PHOTO

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        ext = ".jpg"
    elif update.message.video:
        file = await update.message.video.get_file()
        ext = ".mp4"
    else:
        await update.message.reply_text("Отправь фото или видео.")
        return PHOTO

    file_path = f"{user_id}_{file.file_unique_id}{ext}"
    await file.download_to_drive(file_path)
    user_data[user_id] = {"file_path": file_path}

    button = KeyboardButton("📍 Отправить геолокацию", request_location=True)
    keyboard = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Теперь отправь местоположение:", reply_markup=keyboard)
    return LOCATION

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    location = update.message.location
    if not location:
        await update.message.reply_text("Используй кнопку геолокации.")
        return LOCATION
    user_data[user_id]["latitude"] = location.latitude
    user_data[user_id]["longitude"] = location.longitude
    await update.message.reply_text("Добавь комментарий (тип саранчи, описание и т.п.):")
    return COMMENT

async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    comment = update.message.text
    data = user_data.get(user_id)
    if not data:
        await update.message.reply_text("Ошибка. Начни сначала командой /start")
        return ConversationHandler.END

    data["comment"] = comment

    try:
        with open(data["file_path"], "rb") as f:
            filename = os.path.basename(data["file_path"])
            supabase.storage.from_("photos").upload(filename, f, {"x-upsert": "true"})

        public_url = f"{SUPABASE_URL}/storage/v1/object/public/photos/{filename}"
        supabase.table("reports").insert({
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "comment": data["comment"],
            "photo_url": public_url,
            "user_id": str(user_id),
        }).execute()

        await update.message.reply_text("✅ Спасибо! Всё загружено.")
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при сохранении в Supabase.")
        print("❌", e)

    try:
        os.remove(data["file_path"])
    except:
        pass

    user_data.pop(user_id, None)
    return ConversationHandler.END

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Только админ может экспортировать данные.")
        return
    try:
        res = supabase.table("reports").select("*").execute()
        rows = res.data
        if not rows:
            await update.message.reply_text("Пока нет данных.")
            return
        csv_data = "id,created_at,latitude,longitude,comment,photo_url\n"
        for r in rows:
            csv_data += f'{r["id"]},{r["created_at"]},{r["latitude"]},{r["longitude"]},"{r["comment"]}",{r["photo_url"]}\n'
        with open("export.csv", "w", encoding="utf-8") as f:
            f.write(csv_data)
        await update.message.reply_document(open("export.csv", "rb"))
        os.remove("export.csv")
    except Exception as e:
        await update.message.reply_text("❌ Ошибка экспорта.")
        print("❌", e)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("✅ Бот запущен и работает.")
    else:
        await update.message.reply_text("⛔ Нет доступа.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PHOTO: [MessageHandler(filters.PHOTO | filters.VIDEO, handle_media)],
            LOCATION: [MessageHandler(filters.LOCATION, handle_location)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("export", export_data))
    app.add_handler(CommandHandler("status", status))
    app.run_polling()
