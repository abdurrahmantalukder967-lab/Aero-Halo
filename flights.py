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
    "BBC": "Biman Bangladesh Airlines",
    "UBG": "US-Bangla Airlines",
    "AHJ": "Novoair",
    "NVQ": "Novoair",
    "NVC": "Air Astra",
    "IGO": "IndiGo",
    "AIC": "Air India",
    "SEJ": "SpiceJet",
    "AXB": "Air India Express",
    "IAD": "Air India Express",
    "AKJ": "Akasa Air",
    "VTI": "Vistara",
    "SLK": "SriLankan Airlines",
    "UAE": "Emirates",
    "ETD": "Etihad Airways",
    "QTR": "Qatar Airways",
    "FDB": "flydubai",
    "ABY": "Air Arabia",
    "GFA": "Gulf Air",
    "OMA": "Oman Air",
    "KNE": "flynas",
    "SVA": "Saudia",
    "KAC": "Kuwait Airways",
    "THY": "Turkish Airlines",
    "PGT": "Pegasus Airlines",
    "SIA": "Singapore Airlines",
    "TGW": "Scoot",
    "MAS": "Malaysia Airlines",
    "AXM": "AirAsia",
    "THA": "Thai Airways",
    "HVN": "Vietnam Airlines",
    "VJC": "VietJet Air",
    "CPA": "Cathay Pacific",
    "CCA": "Air China",
    "CES": "China Eastern Airlines",
    "CSN": "China Southern Airlines",
    "CAL": "China Airlines",
    "EVA": "EVA Air",
    "ANA": "All Nippon Airways",
    "JAL": "Japan Airlines",
    "KAL": "Korean Air",
    "AAR": "Asiana Airlines",
    "PIA": "Pakistan International Airlines",
    "BAW": "British Airways",
    "DLH": "Lufthansa",
    "AFR": "Air France",
    "KLM": "KLM",
    "UAE": "Emirates",
    "QFA": "Qantas",
    "ETH": "Ethiopian Airlines",
    "MSR": "EgyptAir",
    "RJA": "Royal Jordanian",
    "ELY": "El Al",
    "AAL": "American Airlines",
    "UAL": "United Airlines",
    "DAL": "Delta Air Lines",
    "SWA": "Southwest Airlines",
    "FDX": "FedEx Express",
    "UPS": "UPS Airlines",
    "GIA": "Garuda Indonesia",
    "PAL": "Philippine Airlines",
    "CEB": "Cebu Pacific",
    "BOX": "AeroLogic",
    "CLX": "Cargolux",
    "BG": "Biman Bangladesh Airlines",
    "BS": "US-Bangla Airlines",
    "VQ": "Novoair",
    "2A": "Air Astra",
    "6E": "IndiGo",
    "AI": "Air India",
    "EK": "Emirates",
    "QR": "Qatar Airways",
    "EY": "Etihad Airways",
    "SQ": "Singapore Airlines",
    "TK": "Turkish Airlines",
    "UL": "SriLankan Airlines",
    "MH": "Malaysia Airlines",
    "TG": "Thai Airways",
    "FZ": "flydubai",
    "SV": "Saudia",
    "GF": "Gulf Air",
    "WY": "Oman Air",
    "KU": "Kuwait Airways",
}

TYPES: dict[str, str] = {
    "A318": "Airbus A318",
    "A319": "Airbus A319",
    "A320": "Airbus A320",
    "A20N": "Airbus A320neo",
    "A321": "Airbus A321",
    "A21N": "Airbus A321neo",
    "A332": "Airbus A330-200",
    "A333": "Airbus A330-300",
    "A338": "Airbus A330-800",
    "A339": "Airbus A330-900",
    "A359": "Airbus A350-900",
    "A35K": "Airbus A350-1000",
    "A388": "Airbus A380",
    "B738": "Boeing 737-800",
    "B38M": "Boeing 737 MAX 8",
    "B39M": "Boeing 737 MAX 9",
    "B744": "Boeing 747-400",
    "B748": "Boeing 747-8",
    "B772": "Boeing 777-200",
    "B77W": "Boeing 777-300ER",
    "B77L": "Boeing 777F",
    "B788": "Boeing 787-8",
    "B789": "Boeing 787-9",
    "B78X": "Boeing 787-10",
    "AT72": "ATR 72",
    "AT75": "ATR 72-500",
    "AT76": "ATR 72-600",
    "DH8D": "Dash 8 Q400",
    "E190": "Embraer E190",
    "E195": "Embraer E195",
    "E75L": "Embraer E175",
    "BCS3": "Airbus A220-300",
}


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
