from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class HotelStay:
    confirmation_number: str
    hotel_name: str
    check_in_date: date
    check_out_date: date
    scraped_at: datetime

    @property
    def key(self) -> str:
        return self.confirmation_number

    def to_dict(self) -> dict:
        return {
            "confirmation_number": self.confirmation_number,
            "hotel_name": self.hotel_name,
            "check_in_date": self.check_in_date.isoformat(),
            "check_out_date": self.check_out_date.isoformat(),
            "scraped_at": self.scraped_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> HotelStay:
        return cls(
            confirmation_number=d["confirmation_number"],
            hotel_name=d["hotel_name"],
            check_in_date=date.fromisoformat(d["check_in_date"]),
            check_out_date=date.fromisoformat(d["check_out_date"]),
            scraped_at=datetime.fromisoformat(d["scraped_at"]),
        )
