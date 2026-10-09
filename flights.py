"""Live aircraft lookup within a 90 km halo.

One request returns positions plus airline, type and route when the feed has them.
Route enrichment is best-effort and never blocks the Telegram alert.
"""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from typing import Any

import httpx

HALO_KM = 90.0
NM_TO_KM = 1.852

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://www.flightradar24.com/"
}

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


async def scan_global_bbox(
    min_lat: float = 20.0,
    max_lat: float = 27.0,
    min_lon: float = 88.0,
    max_lon: float = 93.0
) -> list[Contact]:
    contacts = []

    fr24_url = f"https://data-cloud.flightradar24.com/zones/fcgi/feed.json?bounds={max_lat},{min_lat},{min_lon},{max_lon}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=1&gliders=0"

    try:
        async with httpx.AsyncClient(timeout=8.0, headers=HEADERS) as client:
            resp = await client.get(fr24_url)
            if resp.status_code == 200:
                data = resp.json()
                print(f"FR24 Raw Contacts Count: {len(data)}")
                for key, val in data.items():
                    if isinstance(val, list) and len(val) >= 18:
                        contacts.append(
                            Contact(
                                hex=str(key),
                                callsign=str(val[16]).strip() if val[16] else "N/A",
                                lat=float(val[1]),
                                lon=float(val[2]),
                                altitude_ft=int(val[4]) if val[4] is not None else 0,
                                speed_kts=int(val[5]) if val[5] is not None else 0,
                                heading=int(val[3]) if val[3] is not None else 0,
                            )
                        )
    except Exception as e:
        print(f"FR24 fetch error: {e}")

    if not contacts:
        opensky_url = f"https://opensky-network.org/api/states/all?lamin={min_lat}&lamax={max_lat}&lomin={min_lon}&lomax={max_lon}"
        try:
            async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get(opensky_url)
                if resp.status_code == 200:
                    data = resp.json()
                    states = data.get("states") or []
                    for s in states:
                        if len(s) >= 11 and s[5] is not None and s[6] is not None:
                            contacts.append(
                                Contact(
                                    hex=str(s[0]),
                                    callsign=str(s[1]).strip() if s[1] else "N/A",
                                    lat=float(s[6]),
                                    lon=float(s[5]),
                                    altitude_ft=int(s[7] * 3.28084) if s[7] is not None else 0,
                                    speed_kts=int(s[9] * 1.94384) if s[9] is not None else 0,
                                    heading=int(s[10]) if s[10] is not None else 0,
                                )
                            )
        except Exception as e:
            print(f"OpenSky fetch error: {e}")

    return contacts
