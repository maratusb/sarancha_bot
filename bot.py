import os
import logging
from datetime import datetime
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

PHOTO, LOCATION, COMMENT = range(3)
logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Пришли фото саранчи.")
    return PHOTO

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = await update.message.photo[-1].get_file()
    file_path = f"{update.message.from_user.id}_{photo.file_unique_id}.jpg"
    await photo.download_to_drive(file_path)
    context.user_data['photo_file'] = file_path
    await update.message.reply_text("Теперь отправь геолокацию.", reply_markup=ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить локацию", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True))
    return LOCATION

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lat'] = update.message.location.latitude
    context.user_data['lon'] = update.message.location.longitude
    await update.message.reply_text("Теперь напиши комментарий.")
    return COMMENT

async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    user_id = update.message.from_user.id
    photo_file = context.user_data['photo_file']
    filename = os.path.basename(photo_file)

    with open(photo_file, "rb") as f:
        supabase.storage.from_("photos").upload(filename, f, {"content-type": "image/jpeg"})
    photo_url = f"{SUPABASE_URL}/storage/v1/object/public/photos/{filename}"

    supabase.table("reports").insert({
        "datetime": datetime.utcnow().isoformat(),
        "user_id": str(user_id),
        "latitude": context.user_data['lat'],
        "longitude": context.user_data['lon'],
        "comment": comment,
        "photo_url": photo_url
    }).execute()

    os.remove(photo_file)
    await update.message.reply_text("Готово! Спасибо за сообщение.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PHOTO: [MessageHandler(filters.PHOTO, handle_photo)],
            LOCATION: [MessageHandler(filters.LOCATION, handle_location)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == '__main__':
    main()
