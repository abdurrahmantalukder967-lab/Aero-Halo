"""SQLite store for multi-user watch positions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DB_PATH = Path(__file__).resolve().parent / "data" / "aerohalo.db"


@dataclass
class Watcher:
    chat_id: int
    lat: float
    lon: float
    label: str
    active: bool
    seen_hexes: set[str]


class Store:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchers (
                chat_id INTEGER PRIMARY KEY,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                seen_hexes TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        self._conn.commit()

    def upsert_location(self, chat_id: int, lat: float, lon: float, label: str) -> Watcher:
        self._conn.execute(
            """
            INSERT INTO watchers (chat_id, lat, lon, label, active, seen_hexes)
            VALUES (?, ?, ?, ?, 1, '[]')
            ON CONFLICT(chat_id) DO UPDATE SET
                lat = excluded.lat,
                lon = excluded.lon,
                label = excluded.label,
                active = 1,
                seen_hexes = '[]'
            """,
            (chat_id, lat, lon, label),
        )
        self._conn.commit()
        return self.get(chat_id)  # type: ignore[return-value]

    def set_active(self, chat_id: int, active: bool) -> None:
        self._conn.execute("UPDATE watchers SET active = ? WHERE chat_id = ?", (1 if active else 0, chat_id))
        self._conn.commit()

    def get(self, chat_id: int) -> Watcher | None:
        row = self._conn.execute("SELECT * FROM watchers WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row(row) if row else None

    def active_watchers(self) -> Iterable[Watcher]:
        rows = self._conn.execute("SELECT * FROM watchers WHERE active = 1").fetchall()
        return [self._row(r) for r in rows]

    def save_seen(self, chat_id: int, hexes: set[str]) -> None:
        self._conn.execute(
            "UPDATE watchers SET seen_hexes = ? WHERE chat_id = ?",
            (json.dumps(sorted(hexes)), chat_id),
        )
        self._conn.commit()

    def _row(self, row: sqlite3.Row) -> Watcher:
        try:
            seen = set(json.loads(row["seen_hexes"] or "[]"))
        except json.JSONDecodeError:
            seen = set()
        return Watcher(
            chat_id=int(row["chat_id"]),
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            label=str(row["label"] or ""),
            active=bool(row["active"]),
            seen_hexes=seen,
        )
