from __future__ import annotations

"""
Nice, France — Marriott hotel scraper.
High-end Marriott properties in Nice (JW Marriott, Le Méridien, Marriott).
7 nights, 2 rooms (family of 6 needs 2 rooms in European hotels).
"""

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper

logger = logging.getLogger(__name__)

SEARCH_URL = (
    "https://www.marriott.com/search/findHotels.mi"
    "?cityCode=NCE&countryCode=FR&numberOfRooms=2&numberOfAdults=2&numberOfChildren=4"
    "&brandCode=JW,MC,LM,RZ"   # JW Marriott, Marriott Hotels, Le Méridien, Ritz-Carlton
)
DIRECT_URLS = [
    "https://www.marriott.com/hotels/travel/ncejw-jw-marriott-hotel-nice/",
    "https://www.marriott.com/hotels/travel/ncemn-le-meridien-nice/",
]

FALLBACK_PER_ROOM_PER_NIGHT = 350   # High-end Marriott Nice, midrange estimate
ROOMS = 2
NIGHTS = 7


class NiceMarriottScraper(BaseScraper):
    SOURCE = "nice_france"

    async def scrape(self) -> list:
        return []

    async def get_weekly_costs(self, week_starts: list[date]) -> dict[str, dict]:
        rate_per_room_night = await self._get_room_rate()
        accommodation = rate_per_room_night * ROOMS * NIGHTS

        results = {}
        for ws in week_starts:
            results[ws.isoformat()] = {
                "accommodation_price": round(accommodation, 2),
                "tickets_price": 0.0,
                "url": DIRECT_URLS[0],
            }
        return results

    async def _get_room_rate(self) -> float:
        for url in DIRECT_URLS + [SEARCH_URL]:
            try:
                # Use a future date for the search (2 months out) to get a representative rate
                check_in = (date.today() + timedelta(weeks=8)).isoformat()
                check_out = (date.today() + timedelta(weeks=8, days=7)).isoformat()
                full_url = f"{url}?fromDate={check_in}&toDate={check_out}&numAdults=2&numChildren=4"

                await self.page.goto(full_url, wait_until="domcontentloaded", timeout=30_000)
                await self._delay(2, 3)

                for sel in [
                    "#onetrust-accept-btn-handler",
                    "button:has-text('Accept')",
                    "button:has-text('Reject All')",  # sometimes clicking reject is easier
                    "[aria-label='close']",
                ]:
                    try:
                        await self.page.click(sel, timeout=3_000)
                        await self._delay(0.5, 1)
                        break
                    except PWTimeout:
                        pass

                await self.page.wait_for_load_state("networkidle", timeout=20_000)
                text = await self.page.text_content("body") or ""

                # Marriott prices in EUR or USD
                prices = re.findall(r"(?:\$|€|USD|EUR)\s*([\d,]+)(?:\.\d{2})?", text)
                numeric = [int(p.replace(",", "")) for p in prices if 80 <= int(p.replace(",", "")) <= 2000]

                if numeric:
                    rate = min(numeric)
                    logger.info(f"Nice Marriott: ${rate}/room/night")
                    return float(rate)

            except Exception as e:
                logger.warning(f"Nice Marriott scrape failed ({url}): {e}")

        logger.info(f"Nice Marriott: using fallback ${FALLBACK_PER_ROOM_PER_NIGHT}/room/night")
        return float(FALLBACK_PER_ROOM_PER_NIGHT)
