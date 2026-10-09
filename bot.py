"""Telegram Bot integration handling dynamic user locations."""

import logging
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from flights import format_alert, scan_area_for_location

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ইউজারের সেট করা লোকেশন সাময়িকভাবে সেভ রাখার জন্য ডিকশনারি
USER_LOCATIONS = {}
USER_SEEN_AIRCRAFT = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome to AeroHalo!\n\n"
        "Please share your Live Location or Location to start tracking aircrafts within a 90 km radius of your area."
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lat = update.message.location.latitude
    lon = update.message.location.longitude

    USER_LOCATIONS[user_id] = (lat, lon)

    await update.message.reply_text(
        f"📍 Location set successfully!\n"
        f"Lat: {lat:.4f}, Lon: {lon:.4f}\n\n"
        f"Scanning 90 km halo around you now..."
    )

    contacts = await scan_area_for_location(lat, lon)

    if not contacts:
        await update.message.reply_text(
            "Scan finished. No airborne aircraft inside 90 km right now. I will notify you when one enters!"
        )
    else:
        for contact in contacts:
            msg = format_alert(contact, entered=True)
            await update.message.reply_text(msg, parse_mode="Markdown")


async def now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if user_id not in USER_LOCATIONS:
        await update.message.reply_text(
            "⚠️ Please share your location first so I know where to scan!"
        )
        return

    lat, lon = USER_LOCATIONS[user_id]
    await update.message.reply_text(f"Scanning 90 km around your location ({lat:.2f}, {lon:.2f})...")

    contacts = await scan_area_for_location(lat, lon)

    if not contacts:
        await update.message.reply_text(
            "Scan finished. No airborne aircraft inside 90 km right now."
        )
    else:
        for contact in contacts:
            msg = format_alert(contact, entered=False)
            await update.message.reply_text(msg, parse_mode="Markdown")


async def background_poll(context: ContextTypes.DEFAULT_TYPE) -> None:
    """প্রতিটি ইউজারের সেভ করা লোকেশনের ওপর ভিত্তি করে ব্যাকগ্রাউন্ড পোলিং।"""
    for user_id, (lat, lon) in USER_LOCATIONS.items():
        try:
            contacts = await scan_area_for_location(lat, lon)
            seen = USER_SEEN_AIRCRAFT.setdefault(user_id, set())

            current_hexes = {c.hex for c in contacts}

            for contact in contacts:
                if contact.hex not in seen:
                    msg = format_alert(contact, entered=True)
                    await context.bot.send_message(
                        chat_id=user_id, text=msg, parse_mode="Markdown"
                    )
                    seen.add(contact.hex)

            # এলাকা থেকে বের হয়ে যাওয়া এয়ারক্রাফট ফিল্টার আউট
            USER_SEEN_AIRCRAFT[user_id] = seen.intersection(current_hexes)
        except Exception as e:
            logging.error(f"Error polling for user {user_id}: {e}")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("now", now_command))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    # প্রতি ৪৫ সেকেন্ড পর পর অটোমেটিক পোলিং
    job_queue = app.job_queue
    job_queue.run_repeating(background_poll, interval=45, first=10)

    app.run_polling()


if __name__ == "__main__":
    main()
