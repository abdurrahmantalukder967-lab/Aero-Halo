"""Live aircraft lookup within a 90 km halo.

One request returns positions plus airline, type and route when the feed has
them. Route enrichment is best-effort and never blocks the Telegram alert.
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
USER_AGENT = "Mozilla/5.0 (compatible; AeroHalo/1.0; +https://aero-halo.example)"

AIRLINES: dict[str, str] = {
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
    "GTR": "MAS Galistair Infinite Aviation",
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
    "AKL": "SriLankan Airlines",
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
    "BH": "Bangladesh Air Force"
}

TYPES: dict[str, str] = {
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
    "C172": "Cessna 172R Skyhawk",
    "C295": "Airbus C-295W",
    "C30J": "Lockheed C-130J Hercules",
    "C130": "Lockheed C-130-Hercules",
    "H25B": "Hawker-XP",
    "F900": "Dassault Falcon 900EX",
    "GA7C": "Gulfstream G700",
    "FA6X": "Dassault Falcon 6X EASy IV",
    "FA7X": "Dassault Falcon 7X",
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
    "GLEX": "Bombardier Global 6000",
    "GL7T": "Bombardier Global 7500",
    "GL5T": "Bombardier Global 5500",
    "R66": "Robinson R66 Turbine",
    "A119": "Leonardo AW119 Koala",
    "F2TH": "Dassault Falcon 2000LX EASy",
    "BE20": "Beechcraft 200 King Air",
    "C25A": "Cessna Citation CJ2",
    "C55B": "Cessna Citation Bravo",
    "C560": "Cessna Citation V",
    "A400": "Airbus A400M Atlas",
    "CL60": "Bombardier Challenger 605",
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
    "SR22": "Cirrus SR22"
}

def get_country_from_reg(reg: str | None) -> str:
    if not reg or reg == "N/A":
        return "Unknown"
    
    reg = reg.upper()
    prefixes = {
    "S2-": "Bangladesh 🇧🇩",
    "S3-": "Bangladesh (Military) 🇧🇩", 
    "VT-": "India 🇮🇳",
    "AP-": "Pakistan 🇵🇰",
    "4R-": "Sri Lanka 🇱🇰",
    "8Q-": "Maldives 🇲🇻",
    "A5-": "Bhutan 🇧🇹",
    "9N-": "Nepal 🇳🇵",
    "A6-": "United Arab Emirates 🇦🇪",
    "A7-": "Qatar 🇶🇦",
    "A9C-": "Bahrain 🇧🇭",
    "HZ-": "Saudi Arabia 🇸🇦",
    "9K-": "Kuwait 🇰🇼",
    "JY-": "Jordan 🇯🇴",
    "A4O-": "Oman 🇴🇲",
    "OD-": "Lebanon 🇱🇧",
    "YI-": "Iraq 🇮🇶",
    "EP-": "Iran 🇮🇷",
    "TC-": "Turkey 🇹🇷",
    "9M-": "Malaysia 🇲🇾",
    "9V-": "Singapore 🇸🇬",
    "HS-": "Thailand 🇹🇭",
    "VN-": "Vietnam 🇻🇳",
    "PK-": "Indonesia 🇮🇩",
    "RP-": "Philippines 🇵🇭",
    "XY-": "Myanmar 🇲🇲",
    "XZ-": "Myanmar 🇲🇲",
    "RD-": "Laos 🇱🇦",
    "XU-": "Cambodia 🇰🇭",
    "V8-": "Brunei 🇧🇳",
    "B-": "China / Taiwan / Hong Kong 🇨🇳",
    "JA-": "Japan 🇯🇵",
    "HL-": "South Korea 🇰🇷",
    "P-": "North Korea 🇰🇵",
    "JU-": "Mongolia 🇲🇳",
    "G-": "United Kingdom 🇬🇧",
    "F-": "France 🇫🇷",
    "D-": "Germany 🇩🇪",
    "EI-": "Ireland 🇮🇪",
    "EJ-": "Ireland 🇮🇪",
    "EC-": "Spain 🇪🇸",
    "I-": "Italy 🇮🇹",
    "PH-": "Netherlands 🇳🇱",
    "OO-": "Belgium 🇧🇪",
    "HB-": "Switzerland 🇨🇭",
    "OE-": "Austria 🇦🇹",
    "CS-": "Portugal 🇵🇹",
    "SX-": "Greece 🇬🇷",
    "SE-": "Sweden 🇸🇪",
    "LN-": "Norway 🇳🇴",
    "OY-": "Denmark 🇩🇰",
    "OH-": "Finland 🇫🇮",
    "SP-": "Poland 🇵🇱",
    "HA-": "Hungary 🇭🇺",
    "OK-": "Czech Republic 🇨🇿",
    "OM-": "Slovakia 🇸🇰",
    "YR-": "Romania 🇷🇴",
    "LZ-": "Bulgaria 🇧🇬",
    "RA-": "Russia 🇷🇺",
    "RF-": "Russia (Military) 🇷🇺",
    "UR-": "Ukraine 🇺🇦",
    "EW-": "Belarus 🇧🇾",
    "N-": "United States 🇺🇸",
    "ER-": "Moldova 🇲🇩",
    "C-": "Canada 🇨🇦",
    "XA-": "Mexico 🇲🇽",
    "XB-": "Mexico 🇲🇽",
    "XC-": "Mexico 🇲🇽",
    "PP-": "Brazil 🇧🇷",
    "PR-": "Brazil 🇧🇷",
    "PT-": "Brazil 🇧🇷",
    "PU-": "Brazil 🇧🇷",
    "PS-": "Brazil 🇧🇷",
    "LV-": "Argentina 🇦🇷",
    "LQ-": "Argentina 🇦🇷",
    "CC-": "Chile 🇨🇱",
    "HK-": "Colombia 🇨🇴",
    "VH-": "Australia 🇦🇺",
    "ZK-": "New Zealand 🇳🇿",
    "ZL-": "New Zealand 🇳🇿",
    "ZM-": "New Zealand 🇳🇿",
    "ZS-": "South Africa 🇿🇦",
    "ZT-": "South Africa 🇿🇦",
    "ZU-": "South Africa 🇿🇦",
    "SU-": "Egypt 🇪🇬",
    "5N-": "Nigeria 🇳🇬",
    "5Y-": "Kenya 🇰🇪",
    "ET-": "Ethiopia 🇪🇹",
    "7T-": "Algeria 🇩🇿",
    "CN-": "Morocco 🇲🇦"
    }
    
    for prefix, country in prefixes.items():
        if reg.startswith(prefix):
            return country
            
    return "International"


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


def _bbox(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    lat_d = km / 111.32
    lon_d = km / (111.32 * max(0.2, abs(math.cos(math.radians(lat)))))
    return (
        max(-90.0, lat - lat_d),
        min(90.0, lat + lat_d),
        max(-180.0, lon - lon_d),
        min(180.0, lon + lon_d),
    )


def lookup_airline(code: str) -> str | None:
    token = code.strip().upper().replace(" ", "")
    if not token:
        return None
    if AIRLINES.get(token):
        return AIRLINES[token]
    three = token[:3]
    if len(three) == 3 and three.isalpha() and AIRLINES.get(three):
        return AIRLINES[three]
    two = token[:2]
    if AIRLINES.get(two):
        return AIRLINES[two]
    return None


def aircraft_name(type_code: str | None, fallback: str | None = None) -> str:
    code = (type_code or "").strip().upper()
    if code in TYPES:
        return TYPES[code]
    if fallback and fallback.strip() and fallback.strip().upper() != code:
        return fallback.strip()
    return code or "Unknown type"


def _route(origin: str | None, dest: str | None) -> str:
    o = (origin or "").strip().upper()
    d = (dest or "").strip().upper()
    if o and d:
        return f"{o} → {d}"
    if o:
        return f"From {o}"
    if d:
        return f"To {d}"
    return "Route unknown"


async def _get_json(client: httpx.AsyncClient, url: str, timeout: float) -> Any:
    res = await client.get(url, timeout=timeout, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    res.raise_for_status()
    return res.json()


def _finish(contacts: list[Contact]) -> list[Contact]:
    contacts.sort(key=lambda c: c.distance_km)
    return contacts[:40]


async def _from_fr24(client: httpx.AsyncClient, lat: float, lon: float) -> list[Contact]:
    lamin, lamax, lomin, lomax = _bbox(lat, lon, HALO_KM + 5)
    bounds = f"{lamax:.4f},{lamin:.4f},{lomin:.4f},{lomax:.4f}"
    url = (
        "https://data-cloud.flightradar24.com/zones/fcgi/feed.js"
        f"?bounds={bounds}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1"
        "&gnd=0&air=1&vehicles=0&estimated=0&maxage=14400&gliders=0&stats=0"
    )
    data = await _get_json(client, url, 12.0)
    if not isinstance(data, dict):
        return []
    contacts: list[Contact] = []
    for key, row in data.items():
        if key in {"full_count", "version", "stats"} or not isinstance(row, list) or len(row) < 14:
            continue
        ac_lat, ac_lon = row[1], row[2]
        if not isinstance(ac_lat, (int, float)) or not isinstance(ac_lon, (int, float)):
            continue
        on_ground = row[14] if len(row) > 14 else 0
        if on_ground in (1, True, "1"):
            continue
        alt = row[4] if isinstance(row[4], (int, float)) else None
        if alt is None or alt < 100:
            continue
        km = haversine_km(lat, lon, float(ac_lat), float(ac_lon))
        if km > HALO_KM + 0.5:
            continue
        type_code = str(row[8]).strip().upper() if len(row) > 8 and row[8] else None
        reg = str(row[9]).strip() if len(row) > 9 and row[9] else None
        origin = str(row[11]).strip() if len(row) > 11 and row[11] else None
        dest = str(row[12]).strip() if len(row) > 12 and row[12] else None
        flight_no = str(row[13]).strip().upper() if len(row) > 13 and row[13] else ""
        callsign = str(row[16]).strip().upper() if len(row) > 16 and row[16] else flight_no
        airline_code = str(row[18]).strip().upper() if len(row) > 18 and row[18] else ""
        hex_id = str(row[0] or key).strip().lower()
        callsign = callsign or flight_no or hex_id.upper()
        airline = lookup_airline(airline_code) or lookup_airline(callsign) or airline_code or "Unknown operator"
        speed = float(row[5]) if isinstance(row[5], (int, float)) else None
        heading = float(row[3]) if isinstance(row[3], (int, float)) else None
        contacts.append(
            Contact(
                hex=hex_id,
                callsign=callsign,
                registration=reg,
                flag=get_country_from_reg(reg),
                airline=airline,
                aircraft=aircraft_name(type_code),
                type_code=type_code,
                route=_route(origin, dest),
                altitude_ft=float(alt),
                speed_kt=speed,
                heading=heading,
                lat=float(ac_lat),
                lon=float(ac_lon),
                distance_km=km,
            )
        )
    return _finish(contacts)


async def _from_fr24_api(client: httpx.AsyncClient, lat: float, lon: float) -> list[Contact]:
    """Official Flightradar24 API. Needs FR24_API_TOKEN. Paid per aircraft returned."""
    token = os.environ.get("FR24_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("FR24_API_TOKEN is not set")
    lamin, lamax, lomin, lomax = _bbox(lat, lon, HALO_KM + 5)
    bounds = f"{lamax:.4f},{lamin:.4f},{lomin:.4f},{lomax:.4f}"
    res = await client.get(
        "https://fr24api.flightradar24.com/api/live/flight-positions/full",
        params={"bounds": bounds, "limit": 40},
        timeout=12.0,
        headers={
            "Accept": "application/json",
            "Accept-Version": "v1",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    res.raise_for_status()
    data = res.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    contacts: list[Contact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ac_lat, ac_lon = row.get("lat"), row.get("lon")
        if not isinstance(ac_lat, (int, float)) or not isinstance(ac_lon, (int, float)):
            continue
        alt = row.get("alt")
        if not isinstance(alt, (int, float)) or alt < 100:
            continue
        km = haversine_km(lat, lon, float(ac_lat), float(ac_lon))
        if km > HALO_KM + 0.5:
            continue
        type_code = str(row.get("type") or "").strip().upper() or None
        callsign = str(row.get("callsign") or row.get("flight") or "").strip().upper()
        hex_id = str(row.get("hex") or row.get("fr24_id") or callsign or "unknown").strip().lower()
        callsign = callsign or hex_id.upper()
        airline_code = str(row.get("painted_as") or row.get("operating_as") or "").strip().upper()
        airline = lookup_airline(airline_code) or lookup_airline(callsign) or airline_code or "Unknown operator"
        origin = str(row.get("orig_iata") or row.get("orig_icao") or "").strip()
        dest = str(row.get("dest_iata") or row.get("dest_icao") or "").strip()
        speed = row.get("gspeed")
        heading = row.get("track")
        reg = str(row.get("reg") or "").strip() or None
        contacts.append(
            Contact(
                hex=hex_id,
                callsign=callsign,
                registration=reg,
                airline=airline,
                aircraft=aircraft_name(type_code),
                type_code=type_code,
                route=_route(origin, dest),
                altitude_ft=float(alt),
                speed_kt=float(speed) if isinstance(speed, (int, float)) else None,
                heading=float(heading) if isinstance(heading, (int, float)) else None,
                lat=float(ac_lat),
                lon=float(ac_lon),
                distance_km=km,
            )
        )
    return _finish(contacts)


def _from_adsb_rows(rows: list[dict[str, Any]], lat: float, lon: float) -> list[Contact]:
    contacts: list[Contact] = []
    for ac in rows:
        ac_lat, ac_lon = ac.get("lat"), ac.get("lon")
        if not isinstance(ac_lat, (int, float)) or not isinstance(ac_lon, (int, float)):
            continue
        alt = ac.get("alt_baro")
        if alt == "ground" or not isinstance(alt, (int, float)) or alt < 100:
            continue
        dst = ac.get("dst")
        km = float(dst) * NM_TO_KM if isinstance(dst, (int, float)) else haversine_km(lat, lon, ac_lat, ac_lon)
        if km > HALO_KM + 0.5:
            continue
        callsign = str(ac.get("flight") or "").strip().upper() or str(ac.get("hex") or "UNKNOWN").upper()
        type_code = str(ac.get("t") or "").strip().upper() or None
        contacts.append(
            Contact(
                hex=str(ac.get("hex") or callsign).lower(),
                callsign=callsign,
                registration=(str(ac["r"]).strip() if ac.get("r") else None),
                airline=lookup_airline(callsign) or "Unknown operator",
                aircraft=aircraft_name(type_code, str(ac.get("desc") or "") or None),
                type_code=type_code,
                route="Route unknown",
                altitude_ft=float(alt),
                speed_kt=float(ac["gs"]) if isinstance(ac.get("gs"), (int, float)) else None,
                heading=float(ac["track"]) if isinstance(ac.get("track"), (int, float)) else None,
                lat=float(ac_lat),
                lon=float(ac_lon),
                distance_km=km,
            )
        )
    return _finish(contacts)


async def _from_adsb_fi(client: httpx.AsyncClient, lat: float, lon: float) -> list[Contact]:
    dist_nm = math.ceil(HALO_KM / NM_TO_KM) + 2
    data = await _get_json(client, f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{dist_nm}", 12.0)
    return _from_adsb_rows(data.get("ac") or [], lat, lon)


async def _from_adsb_lol(client: httpx.AsyncClient, lat: float, lon: float) -> list[Contact]:
    dist_nm = math.ceil(HALO_KM / NM_TO_KM) + 2
    data = await _get_json(client, f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist_nm}", 12.0)
    rows = data.get("ac") if isinstance(data, dict) else None
    return _from_adsb_rows(rows or [], lat, lon)


async def _enrich_routes(client: httpx.AsyncClient, contacts: list[Contact]) -> None:
    """Fill missing routes. Hard-capped so Telegram alerts are never stuck behind it."""

    async def one(contact: Contact) -> None:
        if contact.route != "Route unknown":
            return
        key = contact.callsign.strip().upper().replace(" ", "")
        if len(key) < 3:
            return
        try:
            data = await _get_json(client, f"https://api.adsbdb.com/v0/callsign/{key}", 2.5)
            fr = (data.get("response") or {}).get("flightroute") or {}
            airline = (fr.get("airline") or {}).get("name")
            origin = (fr.get("origin") or {}).get("iata_code")
            dest = (fr.get("destination") or {}).get("iata_code")
            if airline and contact.airline == "Unknown operator":
                contact.airline = airline
            route = _route(origin, dest)
            if route != "Route unknown":
                contact.route = route
        except Exception:
            return

    pending = [c for c in contacts[:12] if c.route == "Route unknown"]
    if not pending:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*(one(c) for c in pending)), timeout=4.0)
    except TimeoutError:
        return


async def scan_halo(lat: float, lon: float) -> list[Contact]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        errors: list[str] = []
        saw_empty = False
        fetches = [_from_fr24, _from_adsb_fi, _from_adsb_lol]
        if os.environ.get("FR24_API_TOKEN", "").strip():
            fetches.insert(0, _from_fr24_api)
        for fetch in fetches:
            try:
                contacts = await fetch(client, lat, lon)
            except Exception as exc:
                errors.append(f"{fetch.__name__}: {exc}")
                continue
            if contacts:
                await _enrich_routes(client, contacts)
                return contacts
            saw_empty = True
        if errors and not saw_empty:
            raise RuntimeError(errors[-1])
        return []


def format_alert(contact: Contact, *, entered: bool = True) -> str:
    alt = f"{int(round(contact.altitude_ft)):,} ft" if contact.altitude_ft is not None else "n/a"
    spd = f"{int(round(contact.speed_kt))} kt" if contact.speed_kt is not None else "n/a"
    hdg = f"{int(round(contact.heading)) % 360:03d}°" if contact.heading is not None else "n/a"
    dist = f"{contact.distance_km:.1f} km" if contact.distance_km < 10 else f"{int(round(contact.distance_km))} km"
    reg = f" ({contact.registration})" if contact.registration else ""
    title = "NEW CONTACT" if entered else "IN RANGE"
    return (
        f"{title} — {dist}\n\n"
        f"Airline     {contact.airline}\n"
        f"Flight      {contact.callsign}\n"
        f"Aircraft    {contact.aircraft}{reg}\n"
        f"Route       {contact.route}\n"
        f"Altitude    {alt}\n"
        f"Speed       {spd}\n"
        f"Heading     {hdg}"
)
