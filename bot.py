"""AeroHalo Telegram bot — multi-user 90 km aircraft watch.

Each Telegram user sets their own location. The bot polls live ADS-B data
and sends an English alert whenever a new airborne contact enters that
user's 90 km halo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from pathlib import Path

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from flights import HALO_KM, Contact, format_alert, scan_halo
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("aerohalo")

STORE = Store()
COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)")
POLL_SECONDS = 45
MAX_ALERTS = 15
_LOCKS: dict[int, asyncio.Lock] = {}
_FAIL_NOTICE: dict[int, float] = {}
_BOOT_SENT: set[int] = set()


def _keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Share location", request_location=True)],
            [KeyboardButton("/now"), KeyboardButton("/status")],
            [KeyboardButton("/pause"), KeyboardButton("/resume")],
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
    "/now — send every aircraft inside 90 km right now\n"
    "/status — current watch\n"
    "/pause — stop alerts\n"
    "/resume — start alerts again\n\n"
    "Setting a location sends one message per aircraft already inside the halo. "
    "After that, only new aircraft are messaged. /now repeats the full list."
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


def _lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _LOCKS:
        _LOCKS[chat_id] = asyncio.Lock()
    return _LOCKS[chat_id]


async def _send_contacts(bot, chat_id: int, contacts: list[Contact], *, force: bool) -> set[str]:
    watcher = STORE.get(chat_id)
    seen = set(watcher.seen_hexes) if watcher else set()
    targets = contacts if force else [c for c in contacts if c.hex not in seen]
    sent = set(seen)
    if not contacts:
        if force:
            await bot.send_message(
                chat_id,
                "Scan finished. No airborne aircraft inside 90 km right now. I will message you when one enters.",
            )
            log.info("empty scan chat=%s", chat_id)
        return sent
    if not targets:
        log.info("no new aircraft chat=%s tracked=%s", chat_id, len(contacts))
        return sent
    batch = targets[:MAX_ALERTS]
    for contact in batch:
        try:
            await bot.send_message(chat_id, format_alert(contact, entered=not force))
            sent.add(contact.hex)
            log.info("alert sent chat=%s flight=%s", chat_id, contact.callsign)
        except Exception:
            log.exception("send failed chat=%s flight=%s", chat_id, contact.callsign)
    extra = len(targets) - len(batch)
    if extra > 0:
        await bot.send_message(chat_id, f"{extra} more aircraft are inside 90 km. Send /now to list them.")
    return sent


async def _scan_and_alert(bot, chat_id: int, lat: float, lon: float, *, force: bool) -> bool:
    async with _lock(chat_id):
        try:
            contacts = await scan_halo(lat, lon)
        except Exception:
            log.exception("scan failed chat=%s", chat_id)
            now = time.time()
            if now - _FAIL_NOTICE.get(chat_id, 0) > 900:
                _FAIL_NOTICE[chat_id] = now
                try:
                    await bot.send_message(chat_id, "Live feed failed. I will retry in under a minute.")
                except Exception:
                    log.exception("fail notice not sent chat=%s", chat_id)
            return False
        log.info("scan chat=%s aircraft=%s force=%s", chat_id, len(contacts), force)
        sent = await _send_contacts(bot, chat_id, contacts, force=force)
        STORE.save_seen(chat_id, sent)
        return True


async def cmd_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    watcher = STORE.get(update.effective_chat.id)
    if not watcher:
        await update.message.reply_text("Set a location first. Share your location or /set LAT LON.")
        return
    if not watcher.active:
        STORE.set_active(update.effective_chat.id, True)
    await update.message.reply_text("Scanning 90 km around you...")
    await _scan_and_alert(
        context.bot,
        update.effective_chat.id,
        watcher.lat,
        watcher.lon,
        force=True,
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    w = STORE.get(update.effective_chat.id)
    if not w:
        await update.message.reply_text("Set a location first.")
        return
    STORE.set_active(update.effective_chat.id, True)
    await update.message.reply_text("Watch resumed. Scanning now...")
    await _scan_and_alert(context.bot, update.effective_chat.id, w.lat, w.lon, force=True)


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
    await _arm(update, context, lat, lon, f"{lat:.4f}, {lon:.4f}")


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.location:
        return
    loc = update.message.location
    await _arm(update, context, loc.latitude, loc.longitude, "Shared location")


async def _arm(update: Update, context: ContextTypes.DEFAULT_TYPE, lat: float, lon: float, label: str) -> None:
    if not update.effective_chat or not update.message:
        return
    STORE.upsert_location(update.effective_chat.id, lat, lon, label)
    await update.message.reply_text(
        f"Watch set.\n{label}\n{lat:.5f}, {lon:.5f}\nHalo {int(HALO_KM)} km.\n"
        "Scanning now. You will get one message per aircraft.",
        reply_markup=_keyboard(),
    )
    await _scan_and_alert(context.bot, update.effective_chat.id, lat, lon, force=True)


async def poll_watchers_async(app: Application):
    """
    মাত্র ১টি গ্লোবাল API কলে সব ইউজারের এলাকায় বিমান ফিল্টার করে নোটিফিকেশন পাঠাবে।
    """
    while True:
        try:
            watchers = list(STORE.active_watchers())
            if not watchers:
                await asyncio.sleep(30)
                continue

            # ১. মাত্র ১টি API কলে পুরো রিজিয়নের সব লাইভ বিমান আনা
            all_aircraft = await scan_global_bbox(20.0, 27.0, 88.0, 93.0)

            # ২. মেমোরিতে প্রতিটি ইউজারের লোকেশন অনুযায়ী ডিস্ট্যান্স ফিল্টার করা
            for w in watchers:
                fresh_contacts = []
                current_hexes = set()

                for ac in all_aircraft:
                    dist = haversine_km(w.lat, w.lon, ac.lat, ac.lon)
                    if dist <= HALO_KM:  # ৯০ কিমির ভেতরে থাকলে
                        current_hexes.add(ac.hex)
                        if ac.hex not in w.seen_hexes:
                            # কাস্টম ডিস্ট্যান্স সেট করে নোটিফিকেশন লিস্টে রাখা
                            ac_copy = dataclasses.replace(ac, distance_km=round(dist, 1))
                            fresh_contacts.append(ac_copy)

                # ইউজারের seen_hexes আপডেট করা
                STORE.save_seen(w.chat_id, current_hexes)

                # ৩. শুধু নতুন এন্টার করা বিমানের জন্য ইউজারকে মেসেজ পাঠানো
                for contact in fresh_contacts:
                    try:
                        await app.bot.send_message(
                            chat_id=w.chat_id,
                            text=format_alert(contact),
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        log.exception("Failed to send alert to %s: %s", w.chat_id, e)

        except Exception as e:
            log.exception("Error in global background poll: %s", e)

        # প্রতি ৪৫ সেকেন্ড পর পর পরবর্তী স্ক্যান
        await asyncio.sleep(45)


def _ensure_event_loop() -> None:
    """Python 3.14 no longer creates a loop for the main thread. PTB 21 crashes without one."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _health_server() -> None:
    """Render web services kill the process unless something listens on $PORT."""
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return
    try:
        port = int(raw)
    except ValueError:
        return
    if port <= 0:
        return
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, name="health", daemon=True).start()
    log.info("health server listening on %s", port)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    job = app.job_queue
    if job is None:
        raise SystemExit("Job queue extra is missing. Install python-telegram-bot[job-queue].")
    job.run_repeating(poll_watchers_async, interval=POLL_SECONDS, first=15)
    _ensure_event_loop()
    _health_server()
    log.info("AeroHalo bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
