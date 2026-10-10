"""Live aircraft lookup supporting dynamic user locations globally."""

from __future__ import annotations

import math
from dataclasses import dataclass
import httpx

HALO_KM = 50.0

AIRLINES: dict[str, str] = {
    "AWA": "Air Astra",
    "BBC": "Biman Bangladesh Airlines",
    "US-Bangla": "US-Bangla Airlines",
    "UBG": "US-Bangla Airlines",
    "VOX": "Air Astra",
    "IGD": "IndiGo",
    "AIC": "Air India",
    "SEJ": "SpiceJet",
    "VTI": "Vistara",
    "AXB": "Air India Express",
    "SIA": "Singapore Airlines",
    "GFA": "Gulf Air",
    "QTR": "Qatar Airways",
    "UAE": "Emirates",
    "ETD": "Etihad Airways",
    "FDB": "Flydubai",
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
}


@dataclass
class Contact:
    hex: str
    callsign: str
    lat: float
    lon: float
    altitude_ft: int
    speed_kts: int
    heading: int
    distance_km: float = 0.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """দুইটি ভৌগোলিক স্থানাঙ্কের মধ্যবর্তী দূরত্ব (কিলোমিটারে) বের করার ফাংশন।"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


async def scan_area_for_location(user_lat: float, user_lon: float) -> list[Contact]:
    """ইউজারের পয়েন্টের চারপাশের ডাইনামিক বাউন্ডিং বক্স বানিয়ে প্লেন খুঁজে বের করে।"""
    # ইউজারের অক্ষাংশ ও দ্রাঘিমাংশ থেকে প্রায় ১.৫ ডিগ্রি চারপাশের বক্স (প্রায় ১৫০+ কিমি কভার করবে)
    min_lat = user_lat - 1.5
    max_lat = user_lat + 1.5
    min_lon = user_lon - 1.5
    max_lon = user_lon + 1.5

    contacts: list[Contact] = []

    fr24_url = f"https://data-live.flightradar24.com/zones/fcgi/feed.json?bounds={max_lat:.2f},{min_lat:.2f},{min_lon:.2f},{max_lon:.2f}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=1&gliders=0"

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(fr24_url)
            if resp.status_code == 200:
                data = resp.json()
                for key, val in data.items():
                    if isinstance(val, list) and len(val) >= 18:
                        c_lat = float(val[1])
                        c_lon = float(val[2])
                        dist = haversine_km(user_lat, user_lon, c_lat, c_lon)

                        # শুধু ৯০ কিমির ভেতরের বিমানগুলোকে ফিল্টার করা হচ্ছে
                        if dist <= HALO_KM:
                            callsign = str(val[16]).strip() if val[16] else "N/A"
                            contacts.append(
                                Contact(
                                    hex=str(key),
                                    callsign=callsign,
                                    lat=c_lat,
                                    lon=c_lon,
                                    altitude_ft=int(val[4]) if val[4] is not None else 0,
                                    speed_kts=int(val[5]) if val[5] is not None else 0,
                                    heading=int(val[3]) if val[3] is not None else 0,
                                    distance_km=round(dist, 1),
                                )
                            )
                print(f"FR24 Dynamic Contacts inside {HALO_KM}km: {len(contacts)}")
    except Exception as e:
        print(f"FR24 Area Scan Error: {e}")

    # Fallback OpenSky
    if not contacts:
        opensky_url = f"https://opensky-network.org/api/states/all?lamin={min_lat}&lamax={max_lat}&lomin={min_lon}&lomax={max_lon}"
        try:
            async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get(opensky_url)
                if resp.status_code == 200:
                    data = resp.json()
                    states = data.get("states") or []
                    for s in states:
                        if len(s) >= 11 and s[5] is not None and s[6] is not None:
                            c_lat = float(s[6])
                            c_lon = float(s[5])
                            dist = haversine_km(user_lat, user_lon, c_lat, c_lon)

                            if dist <= HALO_KM:
                                contacts.append(
                                    Contact(
                                        hex=str(s[0]),
                                        callsign=str(s[1]).strip() if s[1] else "N/A",
                                        lat=c_lat,
                                        lon=c_lon,
                                        altitude_ft=int(s[7] * 3.28084) if s[7] is not None else 0,
                                        speed_kts=int(s[9] * 1.94384) if s[9] is not None else 0,
                                        heading=int(s[10]) if s[10] is not None else 0,
                                        distance_km=round(dist, 1),
                                    )
                                )
                    print(f"OpenSky Dynamic Contacts inside {HALO_KM}km: {len(contacts)}")
        except Exception as e:
            print(f"OpenSky Area Scan Error: {e}")

    return contacts


def format_alert(contact: Contact, entered: bool = True) -> str:
    status = "entered" if entered else "is inside"
    code = contact.callsign[:3] if len(contact.callsign) >= 3 else ""
    airline_name = AIRLINES.get(code, "")
    airline_str = f"\n• **Airline**: {airline_name}" if airline_name else ""

    return (
        f"✈️ **Aircraft Alert!**\n"
        f"An aircraft {status} your 90 km halo.\n\n"
        f"• **Callsign**: {contact.callsign}\n"
        f"• **Distance**: {contact.distance_km:.1f} km\n"
        f"• **Altitude**: {contact.altitude_ft} ft\n"
        f"• **Speed**: {contact.speed_kts} kts\n"
        f"• **Heading**: {contact.heading}°"
        f"{airline_str}"
)
