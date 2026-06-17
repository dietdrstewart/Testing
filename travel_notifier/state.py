from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models.flight import FlightData
from .models.hotel import HotelStay

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_NOTIFICATION_TTL_DAYS = 7


def _empty_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "last_successful_poll": None,
        "flights": {},
        "hotels": {},
        "sent_notifications": {},
    }


class StateManager:
    def __init__(self, state_file: Path):
        self._path = state_file
        self._state: dict = _empty_state()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            self._state = data
            self._prune_old_notifications()
        except (json.JSONDecodeError, KeyError) as e:
            backup = self._path.with_suffix(".json.bak")
            logger.error(f"State file corrupted ({e}), resetting. Backup at {backup}")
            try:
                self._path.rename(backup)
            except OSError:
                pass
            self._state = _empty_state()

    def save(self) -> None:
        self._prune_old_notifications()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self._state, f, indent=2)
        os.replace(tmp, self._path)

    def _prune_old_notifications(self) -> None:
        cutoff = (datetime.now() - timedelta(days=_NOTIFICATION_TTL_DAYS)).isoformat()
        sent = self._state.get("sent_notifications", {})
        self._state["sent_notifications"] = {
            k: v for k, v in sent.items() if v >= cutoff
        }

    def mark_poll_success(self) -> None:
        self._state["last_successful_poll"] = datetime.now().isoformat()

    # --- Flights ---

    def get_flight(self, key: str) -> Optional[FlightData]:
        d = self._state.get("flights", {}).get(key)
        return FlightData.from_dict(d) if d else None

    def update_flights(self, flights: list[FlightData]) -> None:
        self._state["flights"] = {f.key: f.to_dict() for f in flights}

    # --- Hotels ---

    def get_hotel(self, key: str) -> Optional[HotelStay]:
        d = self._state.get("hotels", {}).get(key)
        return HotelStay.from_dict(d) if d else None

    def update_hotels(self, stays: list[HotelStay]) -> None:
        self._state["hotels"] = {s.key: s.to_dict() for s in stays}

    # --- Notifications ---

    def was_sent(self, event_key: str) -> bool:
        return event_key in self._state.get("sent_notifications", {})

    def mark_sent(self, event_key: str) -> None:
        self._state.setdefault("sent_notifications", {})[event_key] = datetime.now().isoformat()

    def get_sent_keys(self) -> set[str]:
        return set(self._state.get("sent_notifications", {}).keys())


def detect_flight_changes(old: Optional[FlightData], new: FlightData) -> list[str]:
    """Returns a list of change event strings for any actionable differences."""
    if old is None:
        # First time seeing this flight — only notify if already in an active state
        active = {"Delayed", "Boarding", "Departed", "Landed", "Cancelled"}
        if new.status in active:
            return [f"STATUS_{new.status.upper()}"]
        return []

    events: list[str] = []

    # Normalize: AA sometimes says "Arrived" instead of "Landed"
    def norm(s: str) -> str:
        return "Landed" if s == "Arrived" else s

    old_status = norm(old.status)
    new_status = norm(new.status)

    if old_status != new_status:
        events.append(f"STATUS_{new_status.upper()}")

    if (old.gate or "") != (new.gate or "") and new.gate:
        events.append("GATE_CHANGED")

    return events


def detect_hotel_events(stay: HotelStay, sent_keys: set[str], checkin_hour: int) -> list[str]:
    """Returns hotel event strings for today's check-in."""
    events: list[str] = []
    today = datetime.now().date()
    now_hour = datetime.now().hour

    if stay.check_in_date == today and now_hour >= checkin_hour:
        event_key = f"{stay.key}_CHECKIN_TODAY_{stay.check_in_date}"
        if event_key not in sent_keys:
            events.append("CHECKIN_TODAY")

    return events
