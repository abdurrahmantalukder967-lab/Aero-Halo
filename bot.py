import json
import math
import os
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# 1. Render Health Check Port Binding
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AeroHalo Engine Active")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"HTTP Health Check Server active on port {port}", flush=True)
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

# Configuration
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8656681867:AAHo0g8ceIv3OBPbExT_k3rZUVlVvviknqw")
DEFAULT_CHAT_ID = os.environ.get("CHAT_ID", "8135300883")
CHECK_INTERVAL = 45
RADIUS_KM = 50.0
MIN_ALTITUDE_FT = 550


# User Locations and States
USER_LOCATIONS = {DEFAULT_CHAT_ID: [25.0706365, 91.4102260]}
USER_ALERTED_PLANES = {}
USER_PAUSED = set()

AIRLINE_NAMES = {
    "AWA": "Air Astra",
    "BBC": "Biman Bangladesh Airlines",
    "US-Bangla": "US-Bangla Airlines",
    "UBG": "US-Bangla Airlines",
    "VOX": "Air Astra",
    "IGO": "IndiGo",
    "AIC": "Air India",
    "SEJ": "SpiceJet",
    "VTI": "Vistara",
    "AXB": "Air India Express",
    "SIA": "Singapore Airlines",
    "GFA": "Gulf Air",
    "QTR": "Qatar Airways",
    "UAE": "Emirates",
    "ETD": "Etihad Airways",
    "FDB": "flydubai",
    "JAZ": "Jazeera Airways",
    "KAC": "Kuwait Airways",
    "MSR": "EgyptAir",
    "SV": "Saudia",
    "SVA": "Saudia",
    "THY": "Turkish Airlines",
    "MAS": "Malaysia Airlines",
    "BVT": "Batik Air",
    "SLK": "SilkAir",
    "CPA": "Cathay Pacific",
    "DRK": "DrukAir",
    "AKJ": "Akasa Air",
    "OMS": "SalamAir",
    "NVQ": "NovoAir",
    "LLR": "Alliance Air",
    "CSN": "China Southern Airlines",
    "CES": "China Eastern Airlines",
    "CCA": "Air China",
    "RNA": "Nepal Airlines",
    "AJX": "Bangladesh Air Force",
    "GTR": "mas (Galistair Infinite Aviation)",
    "IRM": "Mahan Air",
    "BDA": "Blue Dart",
    "HYT": "YTO Cargo Airlines",
    "CSS": "SF Airlines",
    "KAL": "Korean Air",
    "ETH": "Ethiopian Airlines",
    "ANA": "ANA All Nippon Airways",
    "ABY": "Air Arabia",
    "VJC": "VietJet Air",
    "BOX": "Aero Logic",
    "CSC": "Sichuan Airlines",
    "JAL": "Japan Airlines",
    "AXM": "AirAsia",
    "TUA": "Turkmenistan Airlines",
    "PAL": "Philippines Airlines",
    "CAL": "China Airlines",
    "S3B": "Bangladesh Army Aviation",
    "RXI": "Riyadh Air",
    "HIM": "Himalaya Airlines",
    "BTN": "Bhutan Airlines",
    "JDL": "JD Express",
    "EVA": "Eva Air",
    "CLX": "Cargolux",
    "SWR": "Swiss",
    "CTJ": "Tianjin Air Cargo",
    "DHK": "DHL Cargo",
    "AFL": "Aeroflot",
    "HKC": "Hong Kong Air Cargo",
    "GTI": "Atlas Air",
    "UPS": "UPS Cargo",
    "BYD": "beOnd",
    "FJL": "FlyJinnah",
    "PIA": "Pakistan International Airlines",
    "ABQ": "AirBlue",
    "BAW": "British Airways",
    "SHT": "British Airways",
    "THA": "Thai Airways",
    "SGA": "SkyGuard",
    "CGS": "MNG Airlines",
    "KMI": "K-Mile Air",
    "VDA": "Volga-Dnepr Airlines",
    "KMF": "Kam Air",
    "IAW": "Iraqi Airways",
    "KNE": "flynas",
    "VJT": "VistaJet",
    "LHA": "Air Central",
    "ALK": "SriLankan Airlines",
    "OAH": "Afcom Cargo",
    "KZR": "Air Astana",
    "DLH": "Lufthansa",
    "NCR": "National Airlines",
    "RJA": "Royal Jordanian",
    "EJU": "easyJet",
    "UAL": "United Airlines",
    "AFR": "Air France",
    "CFG": "Condor Airlines",
    "QQE": "Qatar Executive",
    "MFX": "My Freighter",
    "FAD": "flyadeal",
    "EXS": "Jet2",
    "RYR": "Ryan Air",
    "QFA": "Qantas",
    "CBJ": "Capital Airlines",
    "EXV": "FitsAir",
    "HVN": "Vietnam Airlines",
    "AZG": "Silk Way West Airlines",
    "AZQ": "Silk Way Airlines",
    "TGW": "Scoot",
    "FIN": "Finnair",
    "SJX": "STARLUX",
    "MJN": "Oman-Royal Air Force",
    "TVR": "Terra Avia",
    "CEB": "Cebu Pacific",
    "LNI": "Lion Air",
    "VSV": "SCAT",
    "BH": "Bangladesh Air Force",
    "IGT": "Georgian Airlines",
    "CTV": "Citilink",
    "GIA": "Garuda Indonesia",
    "PGT": "Pegasus",
    "MJJ": "MJets",
    "GCR": "Tianjin Airlines",
    "AXY": "AirX",
    "THB": "BBN Airlines"
}

AIRCRAFT_NAMES = {
    "AT76": "ATR 72-600",
    "AT75": "ATR 72-500",
    "AT72": "ATR 72",
    "DH8D": "De Havilland Dash 8-400",
    "A20N": "Airbus A320neo",
    "A320": "Airbus A320",
    "A21N": "Airbus A321neo",
    "A321": "Airbus A321",
    "A319": "Airbus A319",
    "A19N": "Airbus A319-153N",
    "A332": "Airbus A330-200",
    "A333": "Airbus A330-300",
    "A339": "Airbus A330-900neo",
    "A359": "Airbus A350-900",
    "A351": "Airbus A350-1000",
    "A35K": "Airbus A350-1041",
    "A388": "Airbus A380-800",
    "B738": "Boeing 737-800",
    "B38M": "Boeing 737 MAX 8",
    "B39M": "Boeing 737 MAX 9",
    "B77W": "Boeing 777-300ER",
    "B772": "Boeing 777-200ER",
    "B77L": "Boeing 777-200LR",
    "B788": "Boeing 787-8 Dreamliner",
    "B789": "Boeing 787-9 Dreamliner",
    "B78X": "Boeing 787-10 Dreamliner",
    "B744": "Boeing 747-400",
    "B748": "Boeing 747-8",
    "E190": "Embraer E190",
    "E195": "Embraer E195",
    "B407": "Bell 407",
    "B763": "Boeing 767-36",
    "A346": "Airbus A340-600",
    "B752": "Boeing 757-200",
    "A343": "Airbus 340-300",
    "E75S": "Embraer E175LR",
    "E35L": "Embraer Legacy 650",
    "E550": "Embraer Legacy 500",
    "E135": "Embraer Legacy 600",
    "E190": "Embraer Lineage 1000",
    "C172": "Cessna 172R Skyhawk",
    "C295": "Airbus C-295W",
    "C30J": "Lockheed C-130J Hercules",
    "C130": "Lockheed C-130-Hercules",
    "H25B": "Hawker-XP",
    "F900": "Dassault Falcon 900EX",
    "GA7C": "Gulfstream G700",
    "FA6X": "Dassault Falcon 6X EASy IV",
    "FA7X": "Dassault Falcon 7X",
    "FA8X": "Dassault Falcon 8X EASy III",
    "FA20": "Dassault Falcon 20",
    "IL76": "Ilyushin Il76",
    "AN32": "Antonov AN-32",
    "B429": "Bell 429 GlobalRanger",
    "D228": "Dornier 228",
    "T206": "Cessna Turbo Stationair HD",
    "G115": "Grob G115TP",
    "MI8": "Mil Mi-17",
    "A124": "Antonov An-124-100 Ruslan",
    "GL5": "Bombardier Global 5000",
    "GLF4": "Gulfstream IV-SP",
    "GLF6": "Gulfstream G650ER",
    "GALX": "Gulfstream G200 Galaxy",
    "GLEX": "Bombardier Global 6000",
    "GL7T": "Bombardier Global 7500",
    "GL5T": "Bombardier Global 5500",
    "R66": "Robinson R66 Turbine",
    "A119": "Leonardo AW119 Koala",
    "F2TH": "Dassault Falcon 2000LX EASy",
    "BE20": "Beechcraft 200 King Air",
    "C25A": "Cessna Citation CJ2",
    "C25B": "Cessna Citation CJ3",
    "C55B": "Cessna Citation Bravo",
    "C560": "Cessna Citation V",
    "A400": "Airbus A400M Atlas",
    "CL60": "Bombardier Challenger 605",
    "CL30": "Bombardier Challenger 300",
    "MI17": "Mil Mi-171",
    "GLF5": "Gulfstream G550",
    "AT46": "ATR 42-600",
    "BE9L": "Beechcraft King Air C90",
    "PC12": "Pilatus PC-12",
    "PC24": "Pilatus PC-24",
    "PC21": "Pilatus PC-21",
    "C208": "Cessna Grand Caravan",
    "C17": "Boeing C17A Globemaster III",
    "B505": "Bell 505 Jet Ranger X",
    "C56X": "Cessna Citation XLS+",
    "CL35": "Bombardier Global 3500",
    "LJ35": "Learjet 35A",
    "LJ45": "Learjet 45",
    "AJ27": "Comac ARJ-21-700",
    "P28A": "Piper Archer DX",
    "C182": "Cessna 182M Skylane",
    "AS50": "Airbus Helicopter H125",
    "BTB2": "Bayraktar TB-2",
    "EC35": "Airbus Helicopters H135",
    "C152": "Cessna 152",
    "PRM1": "Beech 390 Premier IA",
    "L410": "Let L-410 Turbolet",
    "B212": "Bell 212",
    "SR22": "Cirrus SR22",
    "C750": "Cessna Citation X",
    "CRJ7": "Mitsubishi CRJ-701ER",
    "CRJ9": "Mitsubishi CRJ-900LR",
    "CRJ2": "Mitsubishi CRJ-200LR"
}

def get_keyboard():
    return json.dumps({
        "keyboard": [
            [{"text": "📍 Share location", "request_location": True}],
            [{"text": "/now"}, {"text": "/status"}],
            [{"text": "/pause"}, {"text": "/resume"}]
        ],
        "resize_keyboard": True,
        "persistent": True
    })

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(a))

def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": json.loads(get_keyboard())
    }).encode('utf-8')
    req = urllib.request.Request(url, d=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception as e:
        print(f"Telegram Push Error [{chat_id}]:", e, flush=True)

def get_bd_planes():
    url = "https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds=27.00,20.00,88.00,93.00&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            planes = []
            for key, val in data.items():
                if isinstance(val, list) and len(val) > 13:
                    planes.append({
                        "icao": key, "lat": val[1], "lon": val[2],
                        "callsign": val[16] if len(val) > 16 and val[16] else "Unknown",
                        "alt": val[4] or 0, "speed": round((val[5] or 0) * 1.852),
                        "reg": val[9] if len(val) > 9 and val[9] else "N/A",
                        "aircraft": AIRCRAFT_NAMES.get((val[8] or "").upper(), val[8] or "Unknown"),
                        "route": f"{val[11]} ➔ {val[12]}" if len(val) > 12 and val[11] and val[12] else "Data Pending",
                        "airline": AIRLINE_NAMES.get((val[18] or "").upper(), val[18] or "Unknown")
                    })
            return planes
    except Exception as e:
        print("FR24 Fetch Error:", e, flush=True)
        return []

def run_manual_scan(chat_id):
    if chat_id not in USER_LOCATIONS:
        send_telegram(chat_id, "⚠️ No location set! Click <b>'📍 Share location'</b> first.")
        return
        
    u_lat, u_lon = USER_LOCATIONS[chat_id][0], USER_LOCATIONS[chat_id][1]
    send_telegram(chat_id, f"🔎 Scanning 50 km halo around ({u_lat:.2f}, {u_lon:.2f})...")
    bd_planes = get_bd_planes()
    
    found_planes = []
    for p in bd_planes:
        dist = haversine(u_lat, u_lon, p["lat"], p["lon"])
        if dist <= RADIUS_KM:
            p["dist"] = round(dist, 1)
            found_planes.append(p)
            
    if not found_planes:
        send_telegram(chat_id, "Scan finished. No airborne aircraft inside 50 km right now.")
    else:
        msg = f"✈️ <b>Current Flights in 50 km Halo ({len(found_planes)}):</b>\n\n"
        for p in found_planes:
            msg += f"• <b>{p['airline']}</b> ({p['callsign']})\n   {p['aircraft']} | {p['dist']} km away\n   Alt: {p['alt']} ft | Route: {p['route']}\n\n"
        send_telegram(chat_id, msg)

def handle_telegram_updates():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=0"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                for result in data.get("result", []):
                    offset = result["update_id"] + 1
                    msg = result.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id"))
                    
                    if not chat_id:
                        continue
                        
                    if "location" in msg:
                        lat = msg["location"]["latitude"]
                        lon = msg["location"]["longitude"]
                        USER_LOCATIONS[chat_id] = [lat, lon]
                        USER_ALERTED_PLANES[chat_id] = set()
                        send_telegram(chat_id, f"📍 <b>Location set successfully!</b>\nLat: {lat:.4f}, Lon: {lon:.4f}\n\nScanning 90 km halo around you now...")
                        run_manual_scan(chat_id)
                    
                    text = msg.get("text", "")
                    if text == "/start":
                        send_telegram(chat_id, "Welcome to AeroHalo! Click '📍 Share location' below to activate live tracking.")
                    elif text == "/now":
                        run_manual_scan(chat_id)
                    elif text == "/pause":
                        USER_PAUSED.add(chat_id)
                        send_telegram(chat_id, "⏸️ Proximity tracking paused.")
                    elif text == "/resume":
                        USER_PAUSED.discard(chat_id)
                        send_telegram(chat_id, "▶️ Proximity tracking resumed.")
                    elif text == "/status":
                        status = "⏸️ Paused" if chat_id in USER_PAUSED else "🟢 Active"
                        loc_str = f"{USER_LOCATIONS[chat_id][0]:.4f}, {USER_LOCATIONS[chat_id][1]:.4f}" if chat_id in USER_LOCATIONS else "Not Set"
                        send_telegram(chat_id, f"<b>Bot Status:</b> {status}\n<b>Location:</b> {loc_str}\n<b>Radius:</b> 50 km")
        except Exception:
            pass
        time.sleep(3)

threading.Thread(target=handle_telegram_updates, daemon=True).start()

print("AeroHalo Engine Started...", flush=True)

# Main Tracking Engine Loop
while True:
    try:
        bd_planes = get_bd_planes()
        print(f"BD Scan Log: {len(bd_planes)} airborne aircraft tracked in BD bounds", flush=True)

        for chat_id, coords in list(USER_LOCATIONS.items()):
            if chat_id in USER_PAUSED:
                continue

            u_lat, u_lon = coords[0], coords[1]
            alerted = USER_ALERTED_PLANES.setdefault(chat_id, set())
            currently_in_range = set()

            for p in bd_planes:
                dist = haversine(u_lat, u_lon, p["lat"], p["lon"])
                if dist <= RADIUS_KM and p["alt"] >= 550:
                    currently_in_range.add(p["icao"])
                    if p["icao"] not in alerted:
                        msg = (
                            f"✈️🟢 <b>New Flight Detected!</b>\n\n"
                            f"Airline: <b>{p['airline']}</b>\n"
                            f"Aircraft: <b>{p['aircraft']}</b>\n"
                            f"Reg: <b>{p['reg']}</b>\n"
                            f"Route: <b>{p['route']}</b>\n"
                            f"Callsign: <b>{p['callsign']}</b>\n"
                            f"Distance: <b>{round(dist, 1)}</b> km\n"
                            f"Altitude: <b>{p['alt']}</b> ft\n"
                            f"Speed: <b>{p['speed']}</b> km/h\n"
                            f"Time: {datetime.now().strftime('%H:%M:%S')}"
                        )
                        send_telegram(chat_id, msg)
                        alerted.add(p["icao"])
                        print(f"Alert pushed for {p['callsign']} to {chat_id}")

            USER_ALERTED_PLANES[chat_id] = alerted.intersection(currently_in_range)

    except Exception as e:
        print("Engine Loop Error:", e, flush=True)

    time.sleep(CHECK_INTERVAL)
