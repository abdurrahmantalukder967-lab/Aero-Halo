"""
Live aircraft lookup using Flightradar24 public feed inside a specified halo radius.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
import httpx

HALO_KM = 90.0

@dataclass
class Contact:
    hex: str
    callsign: str
    registration: str | None
    airline: str
    aircraft: str
    type_code: str | None
    route: str
    altitude_ft: float | None
    speed_kt: float | None
    heading: float | None
    lat: float
    lon: float
    distance_km: float

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _bbox(lat: float, lon: float, km: float) -> dict[str, float]:
    lat_d = km / 111.32
    lon_d = km / (111.32 * max(0.2, abs(math.cos(math.radians(lat)))))
    return {
        "lamin": max(-90.0, lat - lat_d),
        "lamax": min(90.0, lat + lat_d),
        "lomin": max(-180.0, lon - lon_d),
        "lomax": min(180.0, lon + lon_d),
    }

async def scan_halo(lat: float, lon: float, radius_km: float = HALO_KM) -> list[Contact]:
    bbox = _bbox(lat, lon, radius_km)
    bounds = f"{bbox['lamax']:.2f},{bbox['lamin']:.2f},{bbox['lomin']:.2f},{bbox['lomax']:.2f}"
    url = f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds={bounds}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&type=json"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    contacts = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

    for flight_id, details in data.items():
        if not isinstance(details, list) or len(details) < 18:
            continue

        f_lat = float(details[1])
        f_lon = float(details[2])
        dist = haversine_km(lat, lon, f_lat, f_lon)

        if dist <= radius_km:
            hex_id = str(details[0])
            callsign = str(details[16]) if details[16] else "N/A"
            type_code = str(details[8]) if details[8] else "N/A"
            reg = str(details[9]) if details[9] else "N/A"
            alt = float(details[4]) if details[4] is not None else 0.0
            spd = float(details[5]) if details[5] is not None else 0.0
            heading = float(details[3]) if details[3] is not None else 0.0
            
            origin = str(details[11]) if details[11] else ""
            dest = str(details[12]) if details[12] else ""
            route = f"{origin} ➔ {dest}" if origin or dest else "Unknown"

            c = Contact(
                hex=hex_id,
                callsign=callsign if callsign != "" else "UNKNOWN",
                registration=reg,
                airline="Commercial",
                aircraft=type_code,
                type_code=type_code,
                route=route,
                altitude_ft=alt,
                speed_kt=spd,
                heading=heading,
                lat=f_lat,
                lon=f_lon,
                distance_km=round(dist, 1)
            )
            contacts.append(c)

    return contacts

def format_alert(c: Contact) -> str:
    return (
        f"🛩️🟢 **Aircraft Found!**\n"
        f"• **Callsign:** `{c.callsign}`\n"
        f"• **Type:** `{c.type_code}` ({c.registration})\n"
        f"• **Altitude:** `{c.altitude_ft} ft`\n"
        f"• **Speed:** `{c.speed_kt} kt`\n"
        f"• **Distance:** `{c.distance_km} km` away\n"
        f"• **Route:** {c.route}"
    )
