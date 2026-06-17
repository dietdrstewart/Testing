from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class FlightData:
    flight_number: str
    origin: str
    destination: str
    scheduled_departure: datetime
    scheduled_arrival: datetime
    actual_departure: Optional[datetime]
    actual_arrival: Optional[datetime]
    status: str
    gate: Optional[str]
    departure_date: date
    scraped_at: datetime

    @property
    def key(self) -> str:
        return f"{self.flight_number.replace(' ', '')}_{self.origin}_{self.destination}_{self.departure_date}"

    def to_dict(self) -> dict:
        return {
            "flight_number": self.flight_number,
            "origin": self.origin,
            "destination": self.destination,
            "scheduled_departure": self.scheduled_departure.isoformat(),
            "scheduled_arrival": self.scheduled_arrival.isoformat(),
            "actual_departure": self.actual_departure.isoformat() if self.actual_departure else None,
            "actual_arrival": self.actual_arrival.isoformat() if self.actual_arrival else None,
            "status": self.status,
            "gate": self.gate,
            "departure_date": self.departure_date.isoformat(),
            "scraped_at": self.scraped_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> FlightData:
        def _dt(val: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(val) if val else None

        return cls(
            flight_number=d["flight_number"],
            origin=d["origin"],
            destination=d["destination"],
            scheduled_departure=datetime.fromisoformat(d["scheduled_departure"]),
            scheduled_arrival=datetime.fromisoformat(d["scheduled_arrival"]),
            actual_departure=_dt(d.get("actual_departure")),
            actual_arrival=_dt(d.get("actual_arrival")),
            status=d.get("status", "Unknown"),
            gate=d.get("gate"),
            departure_date=date.fromisoformat(d["departure_date"]),
            scraped_at=datetime.fromisoformat(d["scraped_at"]),
        )

    def display_departure(self) -> str:
        """Returns actual departure time if available, else scheduled."""
        dt = self.actual_departure or self.scheduled_departure
        return dt.strftime("%-I:%M %p")

    def display_arrival(self) -> str:
        dt = self.actual_arrival or self.scheduled_arrival
        return dt.strftime("%-I:%M %p")
