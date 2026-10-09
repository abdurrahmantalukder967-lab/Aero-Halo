import math
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

class SimpleServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_port():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleServer)
    server.serve_forever()

threading.Thread(target=start_port, daemon=True).start()
import requests
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# 1. Render Health Check & Port Binding Thread
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
CHAT_ID = os.environ.get("CHAT_ID", "8135300883")
CHECK_INTERVAL = 45
RADIUS_KM = 90.0

# Default Location (Sunamganj)
MY_LAT = 25.0706365
MY_LON = 91.4102260

alerted_planes = set()

AIRLINE_NAMES = {
    "AWA": "Air Astra", "BBC": "Biman Bangladesh Airlines", "US-Bangla": "US-Bangla Airlines",
    "UBG": "US-Bangla Airlines", "VOX": "Air Astra", "IGO": "IndiGo", "AIC": "Air India",
    "SEJ": "SpiceJet", "VTI": "Vistara", "AXB": "Air India Express", "SIA": "Singapore Airlines",
    "GFA": "Gulf Air", "QTR": "Qatar Airways", "UAE": "Emirates", "ETD": "Etihad Airways",
    "FDB": "flydubai", "JAZ": "Jazeera Airways", "KAC": "Kuwait Airways", "MSR": "EgyptAir",
    "SV": "Saudia", "SVA": "Saudia", "THY": "Turkish Airlines", "MAS": "Malaysia Airlines",
    "AKJ": "Akasa Air", "NVQ": "NovoAir", "CES": "China Eastern Airlines", "CCA": "Air China"
}

AIRCRAFT_NAMES = {
    "AT76": "ATR 72-600", "A20N": "Airbus A320neo", "A320": "Airbus A320",
    "A21N": "Airbus A321neo", "A321": "Airbus A321", "A332": "Airbus A330-200",
    "A333": "Airbus A330-300", "B738": "Boeing 737-800", "B38M": "Boeing 737 MAX 8",
    "B77W": "Boeing 777-300ER", "B788": "Boeing 787-8 Dreamliner", "B789": "Boeing 787-9 Dreamliner"
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(a))

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, data=data, timeout=15)
        print("Telegram Push Response:", res.status_code, flush=True)
    except Exception as e:
        print("Telegram Error:", e, flush=True)

def get_nearby_planes(lat_center, lon_center):
    # Dynamic bounding box calculation
    min_lat, max_lat = lat_center - 1.5, lat_center + 1.5
    min_lon, max_lon = lon_center - 1.5, lon_center + 1.5

    url = f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds={max_lat:.2f},{min_lat:.2f},{min_lon:.2f},{max_lon:.2f}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return []
            
        data = r.json()
        planes = []
        
        for key, val in data.items():
            if isinstance(val, list) and len(val) > 13:
                plat, plon = val[1], val[2]
                dist = haversine(lat_center, lon_center, plat, plon)
                
                if dist <= RADIUS_KM:
                    callsign = val[16] if (len(val) > 16 and val[16]) else "Unknown"
                    alt = val[4] if val[4] is not None else 0
                    speed_kts = val[5] if val[5] is not None else 0
                    speed_kmh = round(speed_kts * 1.852)
                    
                    reg = val[9] if (len(val) > 9 and val[9]) else "N/A"
                    raw_aircraft = val[8] if (len(val) > 8 and val[8]) else "Unknown"
                    aircraft_fullname = AIRCRAFT_NAMES.get(raw_aircraft.upper(), raw_aircraft)
                    
                    origin_code = val[11] if (len(val) > 11 and val[11]) else ""
                    dest_code = val[12] if (len(val) > 12 and val[12]) else ""
                    route = f"{origin_code} ➔ {dest_code}" if (origin_code and dest_code) else "Data Pending"

                    raw_code = val[18] if (len(val) > 18 and val[18]) else (callsign[:3] if callsign != "Unknown" else "Unknown")
                    airline_fullname = AIRLINE_NAMES.get(raw_code.upper(), raw_code)
                    
                    planes.append({
                        "icao": key,
                        "callsign": callsign,
                        "airline": airline_fullname,
                        "aircraft_name": aircraft_fullname,
                        "registration": reg,
                        "route": route,
                        "dist": round(dist, 1),
                        "alt": alt,
                        "speed": speed_kmh
                    })
        return planes
    except Exception as e:
        print("FR24 Fetch Error:", e, flush=True)
        return []

print("Plane Engine Active...", flush=True)

# Processing Loop
while True:
    try:
        planes = get_nearby_planes(MY_LAT, MY_LON)
        print(f"Scan Check: {len(planes)} aircraft found in {RADIUS_KM} km", flush=True)
        
        current_icaos = set()
        for p in planes:
            current_icaos.add(p["icao"])
            if p["icao"] not in alerted_planes:
                msg = (
                    f"✈️🟢 <b>New Flight Detected!</b>\n\n"
                    f"Airline: <b>{p['airline']}</b>\n"
                    f"Aircraft: <b>{p['aircraft_name']}</b>\n"
                    f"Reg: <b>{p['registration']}</b>\n"
                    f"Route: <b>{p['route']}</b>\n"
                    f"Callsign: <b>{p['callsign']}</b>\n"
                    f"Distance: {p['dist']} km\n"
                    f"Altitude: {p['alt']} ft\n"
                    f"Speed: {p['speed']} km/h\n"
                    f"Time: {datetime.now().strftime('%H:%M:%S')}"
                )
                send_telegram(msg)
                alerted_planes.add(p["icao"])
                print("Alert sent for:", p["callsign"], flush=True)
                
        # এলাকা ছেড়ে বেরিয়ে যাওয়া বিমানগুলো ক্লিন করা
        alerted_planes = alerted_planes.intersection(current_icaos)
            
    except Exception as loop_err:
        print("Engine Loop Error:", loop_err, flush=True)
        
    time.sleep(CHECK_INTERVAL)
