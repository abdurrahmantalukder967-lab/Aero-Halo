# AeroHalo Telegram bot

Multi-user Telegram bot that watches **airborne aircraft within 90 km** of each user's location and sends English alerts with:

- Airline name
- Flight / callsign
- Aircraft type
- Route (origin → destination when known)
- Altitude
- Speed
- Heading and distance

Every Telegram account has its own saved location. One running process serves all users.

Live positions come from [adsb.fi](https://opendata.adsb.fi) (OpenSky Network as fallback). Airline and route lookup uses [ADSBdb](https://www.adsbdb.com) — no paid API key.

## Commands

| Command | What it does |
|---|---|
| `/start` | Welcome + location keyboard |
| Share location | Telegram location pin (recommended) |
| `/set 23.8103 90.4125` | Set latitude / longitude by hand |
| `/status` | Show watch state |
| `/pause` | Stop alerts for you |
| `/resume` | Resume alerts |
| `/help` | Command list |

Radius is fixed at **90 km**.

## Alert example

```
NEW CONTACT — 41 km

Airline     IndiGo
Flight      IGO612Y
Aircraft    AIRBUS A-320neo (VT-IPJ)
Route       DEL New Delhi → AJL Aizawl
Altitude    38,975 ft
Speed       490 kt
Heading     097°
```

A contact is only alerted when it **enters** your halo. Aircraft already inside when you set the location are recorded silently so you are not spammed.

## Setup

1. Open Telegram, talk to [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, pick a name and username
3. Copy the token BotFather gives you
4. On a machine with **Python 3.10+**:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env
```

5. Put your token in `.env`:

```
TELEGRAM_BOT_TOKEN=123456:AA...your-token
```

6. Run:

```bash
python bot.py
```

Leave the process running. Users can `/start` and share a location immediately.

### Keep it online

- A cheap VPS (Ubuntu): `tmux` / `systemd` running `python bot.py`
- [Railway](https://railway.app), [Render](https://render.com) or any always-on Python worker — set `TELEGRAM_BOT_TOKEN` as an environment variable
- Do **not** use a serverless function (Vercel / AWS Lambda). The bot long-polls Telegram and scans every 60 seconds.

Example systemd unit:

```
[Service]
WorkingDirectory=/opt/aero-halo-bot
ExecStart=/opt/aero-halo-bot/.venv/bin/python bot.py
Restart=always
Environment=TELEGRAM_BOT_TOKEN=...
```

## How it works

1. Each chat id is a row in SQLite (`data/aerohalo.db`)
2. Every 60 seconds the bot scans active users
3. For each user it asks adsb.fi for traffic within ~50 NM, then filters to 90 km and airborne only (altitude ≥ 400 ft)
4. New Mode-S hex codes not seen on the previous scan trigger an alert
5. ADSBdb fills in airline name and city pair when the callsign is known

The feed is public ADS-B. Coverage is excellent over Europe, North America, the Gulf and much of South / East Asia. Remote oceans and some inland regions are thinner.

## Files

```
bot.py              Telegram commands + poller
flights.py          90 km scan, ADS-B + OpenSky + ADSBdb
store.py            SQLite multi-user store
requirements.txt    python-telegram-bot, httpx
env.example         token template (copy to .env)
gitignore           copy to .gitignore
LICENSE             MIT
```

## License

MIT
