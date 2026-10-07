"""AeroHalo Telegram bot — multi-user 90 km aircraft watch.

Each Telegram user sets their own location. The bot polls live ADS-B data
and sends an English alert whenever a new airborne contact enters that
user's 90 km halo.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from threading import Thread
from flask import Flask

app = Flask(__name__)
@app.route('/')
def health_check():
    return "AeroHalo Bot is Live!", 200

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_http_server, daemon=True).start()
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from flights import HALO_KM, format_alert, scan_halo
from store import Store


def _load_env() -> None:
    path = Path(__file__).resolve().parent / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aerohalo")

STORE = Store()
COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)")
POLL_SECONDS = 60


def _keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Share location", request_location=True)],
            [KeyboardButton("/status"), KeyboardButton("/pause")],
        ],
        resize_keyboard=True,
    )


HELP = (
    "AeroHalo watches airborne traffic within 90 km of you.\n\n"
    "Commands\n"
    "/start — welcome and keyboard\n"
    "/help — this message\n"
    "Share location — tap the button (best) or send a map pin\n"
    "/set 23.8103 90.4125 — set coordinates manually\n"
    "/status — current watch\n"
    "/pause — stop alerts\n"
    "/resume — start alerts again\n\n"
    "Every user has their own location. Alerts are English-only and include "
    "airline, aircraft, route, altitude and speed."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "AeroHalo is armed when you set a location.\n"
        f"Halo radius is fixed at {int(HALO_KM)} km.\n\n"
        "Tap Share location, or send /set LAT LON.",
        reply_markup=_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(HELP, reply_markup=_keyboard())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    w = STORE.get(update.effective_chat.id)
    if not w:
        await update.message.reply_text("No location yet. Share your location or /set LAT LON.")
        return
    state = "active" if w.active else "paused"
    label = w.label or f"{w.lat:.4f}, {w.lon:.4f}"
    await update.message.reply_text(
        f"Watch  {state}\n"
        f"Place  {label}\n"
        f"Coord  {w.lat:.5f}, {w.lon:.5f}\n"
        f"Halo   {int(HALO_KM)} km\n"
        f"Known  {len(w.seen_hexes)} contacts this session"
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    STORE.set_active(update.effective_chat.id, False)
    await update.message.reply_text("Alerts paused. /resume to continue.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    w = STORE.get(update.effective_chat.id)
    if not w:
        await update.message.reply_text("Set a location first.")
        return
    STORE.set_active(update.effective_chat.id, True)
    await update.message.reply_text("Watch resumed.")


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    text = " ".join(context.args or [])
    m = COORD_RE.search(text)
    if not m:
        await update.message.reply_text("Usage: /set 23.8103 90.4125")
        return
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        await update.message.reply_text("Coordinates out of range.")
        return
    await _arm(update, lat, lon, f"{lat:.4f}, {lon:.4f}")


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.location:
        return
    loc = update.message.location
    await _arm(update, loc.latitude, loc.longitude, "Shared location")


async def _arm(update: Update, lat: float, lon: float, label: str) -> None:
    if not update.effective_chat or not update.message:
        return
    STORE.upsert_location(update.effective_chat.id, lat, lon, label)
    await update.message.reply_text(
        f"Watch set.\n{label}\n{lat:.5f}, {lon:.5f}\nHalo {int(HALO_KM)} km.\n"
        "You will be alerted when a new aircraft enters the halo.",
        reply_markup=_keyboard(),
    )
    try:
        contacts = await scan_halo(lat, lon)
        STORE.save_seen(update.effective_chat.id, {c.hex for c in contacts})
        if contacts:
            lines = [f"{c.callsign}  {c.airline}  {int(round(c.distance_km))} km" for c in contacts[:8]]
            await update.message.reply_text(
                f"{len(contacts)} airborne now.\n" + "\n".join(lines)
            )
        else:
            await update.message.reply_text("No airborne contacts inside 90 km right now.")
    except Exception:
        log.exception("initial scan failed")
        await update.message.reply_text("Live feed is busy. Alerts will retry on the next scan.")


import asyncio

async def poll_watchers_async(app: Application):
    while True:
        try:
            watchers = list(STORE.active_watchers())
            for w in watchers:
                contacts = await scan_halo(w.lat, w.lon)
                current = {c.hex for c in contacts}
                fresh = [c for c in contacts if c.hex not in w.seen_hexes]
                STORE.save_seen(w.chat_id, current)
                for contact in fresh:
                    try:
                        await app.bot.send_message(
                            w.chat_id, 
                            format_alert(contact), 
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        log.exception("Send failed for %s: %s", w.chat_id, e)
        except Exception as e:
            log.exception("Error in background watcher poll: %s", e)
            
        await asyncio.sleep(30)

async def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env")
        
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    
    log.info("AeroHalo bot starting...")
    
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        # Start Flightradar24 polling task
        asyncio.create_task(poll_watchers_async(app))
        
        await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
