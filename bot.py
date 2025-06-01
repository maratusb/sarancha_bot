import os
import logging
from dotenv import load_dotenv
from supabase import create_client
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)
import csv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "255357009"))  # Только вы можете экспортировать

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

PHOTO, LOCATION, COMMENT = range(3)
user_data = {}

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Пожалуйста, отправьте фото саранчи.")
    return PHOTO

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    photo_file = await update.message.photo[-1].get_file()
    file_path = f"{user_id}_{photo_file.file_unique_id}.jpg"
    await photo_file.download_to_drive(file_path)
    user_data[user_id] = {"photo_path": file_path}

    button = KeyboardButton(text="📍 ОТПРАВИТЬ МОЁ МЕСТОПОЛОЖЕНИЕ", request_location=True)
    keyboard = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "Теперь отправьте ваше местоположение — нажмите большую кнопку ниже:",
        reply_markup=keyboard
    )
    return LOCATION

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    location = update.message.location
    if not location:
        await update.message.reply_text("Пожалуйста, используйте кнопку для отправки местоположения.")
        return LOCATION
    user_data[user_id]["latitude"] = location.latitude
    user_data[user_id]["longitude"] = location.longitude
    await update.message.reply_text("Добавьте комментарий (например, тип саранчи или описание ситуации):")
    return COMMENT

async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    comment = update.message.text
    data = user_data[user_id]
    data["comment"] = comment

    try:
        with open(data["photo_path"], "rb") as f:
            photo_filename = os.path.basename(data["photo_path"])
            supabase.storage.from_("photos").upload(photo_filename, f, {"x-upsert": "true"})

        public_url = f"{SUPABASE_URL}/storage/v1/object/public/photos/{photo_filename}"

        supabase.table("reports").insert({
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "comment": comment,
            "photo_url": public_url
        }).execute()

        await update.message.reply_text("✅ Спасибо! Данные успешно сохранены.")
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при сохранении данных.")
        print("Ошибка:", e)

    try:
        os.remove(data["photo_path"])
    except:
        pass

    user_data.pop(user_id, None)
    return ConversationHandler.END

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет прав для экспорта данных.")
        return

    try:
        data = supabase.table("reports").select("*").execute().data
        if not data:
            await update.message.reply_text("Нет данных для экспорта.")
            return

        filename = "locust_reports.csv"
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=["id", "created_at", "latitude", "longitude", "comment", "photo_url"])
            writer.writeheader()
            for row in data:
                writer.writerow(row)

        await update.message.reply_document(InputFile(filename))
        os.remove(filename)
    except Exception as e:
        await update.message.reply_text("Ошибка при экспорте данных.")
        print("Export error:", e)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PHOTO: [MessageHandler(filters.PHOTO, handle_photo)],
            LOCATION: [MessageHandler(filters.LOCATION, handle_location)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("export", export_data))
    app.run_polling()
