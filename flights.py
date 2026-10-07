"""Live aircraft lookup within a 90 km halo.

Primary feed: ADS-B aggregators (adsb.fi). Fallback: OpenSky Network.
Airline + route enrichment: ADSBdb (no API key).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx

HALO_KM = 90.0
NM_TO_KM = 1.852
USER_AGENT = "AeroHalo/1.0 (telegram aircraft watch)"


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


async def _get_json(client: httpx.AsyncClient, url: str, timeout: float) -> Any:
    res = await client.get(
        url,
        timeout=timeout,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    res.raise_for_status()
    return res.json()


def _route_line(info: dict[str, Any] | None) -> tuple[str, str]:
    if not info:
        return "Unknown operator", "Route unknown"
    airline = (info.get("airline") or {}).get("name") or "Unknown operator"
    origin = info.get("origin") or {}
    dest = info.get("destination") or {}
    o = origin.get("iata_code")
    d = dest.get("iata_code")
    on = origin.get("municipality") or ""
    dn = dest.get("municipality") or ""
    if o and d:
        left = f"{o} {on}".strip()
        right = f"{d} {dn}".strip()
        return airline, f"{left} → {right}"
    return airline, "Route unknown"


async def _enrich(client: httpx.AsyncClient, callsign: str) -> dict[str, Any] | None:
    key = callsign.strip().upper().replace(" ", "")
    if len(key) < 3:
        return None
    try:
        json = await _get_json(client, f"https://api.adsbdb.com/v0/callsign/{key}", 4.5)
        return (json.get("response") or {}).get("flightroute")
    except Exception:
        return None


def _airborne_alt(alt: Any) -> float | None:
    if isinstance(alt, (int, float)) and alt >= 400:
        return float(alt)
    return None


async def _from_adsb_fi(client: httpx.AsyncClient, lat: float, lon: float) -> list[Contact]:
    dist_nm = math.ceil(HALO_KM / NM_TO_KM) + 2
    json = await _get_json(
        client,
        f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{dist_nm}",
        12.0,
    )
    rows = json.get("ac") or []
    contacts: list[Contact] = []
    callsigns: list[str] = []
    pending: list[dict[str, Any]] = []
    for ac in rows:
        ac_lat, ac_lon = ac.get("lat"), ac.get("lon")
        if not isinstance(ac_lat, (int, float)) or not isinstance(ac_lon, (int, float)):
            continue
        alt = _airborne_alt(ac.get("alt_baro"))
        if alt is None:
            continue
        dst = ac.get("dst")
        km = float(dst) * NM_TO_KM if isinstance(dst, (int, float)) else haversine_km(lat, lon, ac_lat, ac_lon)
        if km > HALO_KM + 0.5:
            continue
        cs = str(ac.get("flight") or "").strip().upper() or str(ac.get("hex") or "UNKNOWN").upper()
        pending.append(ac)
        callsigns.append(cs)

    unique = list(dict.fromkeys(c for c in callsigns if len(c) >= 3))[:40]
    routes: dict[str, dict[str, Any] | None] = {}
    for cs in unique:
        routes[cs] = await _enrich(client, cs)

    for ac, cs in zip(pending, callsigns, strict=False):
        info = routes.get(cs)
        airline, route = _route_line(info)
        dst = ac.get("dst")
        km = float(dst) * NM_TO_KM if isinstance(dst, (int, float)) else haversine_km(
            lat, lon, float(ac["lat"]), float(ac["lon"])
        )
        contacts.append(
            Contact(
                hex=str(ac.get("hex") or cs).lower(),
                callsign=cs,
                registration=(str(ac["r"]).strip() if ac.get("r") else None),
                airline=airline,
                aircraft=str(ac.get("desc") or ac.get("t") or "Unknown type"),
                type_code=str(ac["t"]).strip() if ac.get("t") else None,
                route=route,
                altitude_ft=float(ac["alt_baro"]) if isinstance(ac.get("alt_baro"), (int, float)) else None,
                speed_kt=float(ac["gs"]) if isinstance(ac.get("gs"), (int, float)) else None,
                heading=float(ac["track"]) if isinstance(ac.get("track"), (int, float)) else None,
                lat=float(ac["lat"]),
                lon=float(ac["lon"]),
                distance_km=km,
            )
        )
    contacts.sort(key=lambda c: c.distance_km)
    return contacts[:80]


async def _from_opensky(client: httpx.AsyncClient, lat: float, lon: float) -> list[Contact]:
    box = _bbox(lat, lon, HALO_KM + 8)
    url = (
        "https://opensky-network.org/api/states/all"
        f"?lamin={box['lamin']}&lomin={box['lomin']}&lamax={box['lamax']}&lomax={box['lomax']}"
    )
    json = await _get_json(client, url, 10.0)
    contacts: list[Contact] = []
    for s in json.get("states") or []:
        try:
            hex_id = str(s[0] or "").lower()
            cs = str(s[1] or "").strip().upper() or hex_id.upper()
            lon_s, lat_s, alt_m, on_ground, vel, track = s[5], s[6], s[7], s[8], s[9], s[10]
        except (IndexError, TypeError):
            continue
        if not isinstance(lat_s, (int, float)) or not isinstance(lon_s, (int, float)):
            continue
        if on_ground:
            continue
        if not isinstance(alt_m, (int, float)):
            continue
        alt_ft = alt_m * 3.28084
        if alt_ft < 400:
            continue
        km = haversine_km(lat, lon, lat_s, lon_s)
        if km > HALO_KM:
            continue
        contacts.append(
            Contact(
                hex=hex_id,
                callsign=cs,
                registration=None,
                airline="Unknown operator",
                aircraft="Unknown type",
                type_code=None,
                route="Route unknown",
                altitude_ft=alt_ft,
                speed_kt=vel * 1.94384 if isinstance(vel, (int, float)) else None,
                heading=float(track) if isinstance(track, (int, float)) else None,
                lat=float(lat_s),
                lon=float(lon_s),
                distance_km=km,
            )
        )
    unique = list(dict.fromkeys(c.callsign for c in contacts))[:24]
    routes = {cs: await _enrich(client, cs) for cs in unique}
    out: list[Contact] = []
    for c in contacts:
        airline, route = _route_line(routes.get(c.callsign))
        out.append(
            Contact(
                hex=c.hex,
                callsign=c.callsign,
                registration=c.registration,
                airline=airline,
                aircraft=c.aircraft,
                type_code=c.type_code,
                route=route,
                altitude_ft=c.altitude_ft,
                speed_kt=c.speed_kt,
                heading=c.heading,
                lat=c.lat,
                lon=c.lon,
                distance_km=c.distance_km,
            )
        )
    out.sort(key=lambda c: c.distance_km)
    return out[:80]


async def scan_halo(lat: float, lon: float) -> list[Contact]:
    async with httpx.AsyncClient() as client:
        try:
            return await _from_adsb_fi(client, lat, lon)
        except Exception:
            return await _from_opensky(client, lat, lon)


def format_alert(contact: Contact) -> str:
    alt = f"{int(round(contact.altitude_ft)):,} ft" if contact.altitude_ft is not None else "n/a"
    spd = f"{int(round(contact.speed_kt))} kt" if contact.speed_kt is not None else "n/a"
    hdg = f"{int(round(contact.heading)) % 360:03d}°" if contact.heading is not None else "n/a"
    dist = f"{contact.distance_km:.1f} km" if contact.distance_km < 10 else f"{int(round(contact.distance_km))} km"
    reg = f" ({contact.registration})" if contact.registration else ""
    return (
        f"NEW CONTACT — {dist}\n\n"
        f"Airline     {contact.airline}\n"
        f"Flight      {contact.callsign}\n"
        f"Aircraft    {contact.aircraft}{reg}\n"
        f"Route       {contact.route}\n"
        f"Altitude    {alt}\n"
        f"Speed       {spd}\n"
        f"Heading     {hdg}"
  )
