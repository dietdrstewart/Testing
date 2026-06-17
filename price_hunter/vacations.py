from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Vacation:
    id: str
    name: str
    subtitle: str
    color: str
    emoji: str
    flight_origin: str
    flight_destination: str   # airport code
    nights: int               # 7 for all
    tickets_days: int         # 0 if no separate tickets (cruise/AI/hotel-only)
    notes: str


VACATIONS: dict[str, Vacation] = {
    "disney_week": Vacation(
        id="disney_week",
        name="Disney World",
        subtitle="Art of Animation + 4-Day Tickets + PHL→MCO Flights",
        color="#6366f1",
        emoji="🏰",
        flight_origin="PHL",
        flight_destination="MCO",
        nights=7,
        tickets_days=4,
        notes="Family Suite (sleeps 6). Tickets: 2 adult + 3 child; infant under 3 is free.",
    ),
    "universal_week": Vacation(
        id="universal_week",
        name="Universal Studios",
        subtitle="Hard Rock Hotel + 4-Day Tickets + PHL→MCO Flights",
        color="#f59e0b",
        emoji="🎬",
        flight_origin="PHL",
        flight_destination="MCO",
        nights=7,
        tickets_days=4,
        notes="Family room for 6. Tickets: 2 adult + 3 child; infant under 3 is free.",
    ),
    "royal_icon_cruise": Vacation(
        id="royal_icon_cruise",
        name="Royal Caribbean — Icon Class",
        subtitle="7-Night Caribbean Cruise + PHL→MIA Flights",
        color="#10b981",
        emoji="🚢",
        flight_origin="PHL",
        flight_destination="MIA",
        nights=7,
        tickets_days=0,
        notes="Icon of the Seas or Star of the Seas. Family stateroom for 6.",
    ),
    "xcaret_cancun": Vacation(
        id="xcaret_cancun",
        name="Xcaret Cancún",
        subtitle="All-Inclusive 7 Nights + PHL→CUN Flights",
        color="#ec4899",
        emoji="🌴",
        flight_origin="PHL",
        flight_destination="CUN",
        nights=7,
        tickets_days=0,
        notes="All-inclusive resort. Xcaret experiences included.",
    ),
    "nice_france": Vacation(
        id="nice_france",
        name="Nice, France",
        subtitle="Marriott Nice + PHL→NCE Flights",
        color="#8b5cf6",
        emoji="🇫🇷",
        flight_origin="PHL",
        flight_destination="NCE",
        nights=7,
        tickets_days=0,
        notes="JW Marriott or Le Méridien Nice. 2 rooms for family of 6.",
    ),
}

# Family composition (constant across all vacations)
FAMILY = {
    "adults": 2,
    "children": 3,       # ages 9, 6, 4
    "infants_lap": 1,    # under 1 — lap infant
    "total_travelers": 6,
    "paid_seats": 5,     # infant on lap = no separate seat (domestic); may vary intl
}


def get_sunday_weeks(n_weeks: int = 26) -> list[tuple[date, date]]:
    """Return (sunday, saturday) pairs for the next n_weeks weeks."""
    today = date.today()
    days_to_sunday = (6 - today.weekday()) % 7
    if days_to_sunday == 0:
        days_to_sunday = 7  # next Sunday, not today if today is Sunday
    first_sunday = today + timedelta(days=days_to_sunday)
    return [
        (first_sunday + timedelta(weeks=i), first_sunday + timedelta(weeks=i, days=6))
        for i in range(n_weeks)
    ]
