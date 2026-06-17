from __future__ import annotations

"""
Universal Studios Orlando package scraper.
Fetches: Hard Rock Hotel nightly rate + 4-day park ticket prices.
Tickets: 2 adults + 3 children (9,6,4). Infant under 3 is free.
"""

import logging
import re
from datetime import date

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper

logger = logging.getLogger(__name__)

HOTEL_URL = (
    "https://www.universalorlando.com/web/en/us/plan-your-visit/hotels"
    "/hard-rock-hotel-at-universal-orlando-resort"
)
TICKETS_URL = "https://www.universalorlando.com/web/en/us/tickets-passes"

FALLBACK_HOTEL_PER_NIGHT = 320
FALLBACK_TICKET_ADULT = 115
FALLBACK_TICKET_CHILD = 110

ADULTS = 2
CHILDREN = 3
NIGHTS = 7
TICKET_DAYS = 4


class UniversalPackageScraper(BaseScraper):
    SOURCE = "universal_package"

    async def scrape(self) -> list:
        return []

    async def get_weekly_costs(self, week_starts: list[date]) -> dict[str, dict]:
        hotel_per_night = await self._get_hotel_rate()
        ticket_costs = await self._get_ticket_costs()
        accommodation = hotel_per_night * NIGHTS

        results = {}
        for ws in week_starts:
            results[ws.isoformat()] = {
                "accommodation_price": round(accommodation, 2),
                "tickets_price": round(ticket_costs, 2),
                "url": HOTEL_URL,
            }
        return results

    async def _get_hotel_rate(self) -> float:
        try:
            await self.page.goto(HOTEL_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(1.5, 2.5)

            for sel in ["button:has-text('Accept')", "#onetrust-accept-btn-handler"]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            text = await self.page.text_content("body") or ""
            prices = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
            numeric = [int(p.replace(",", "")) for p in prices if 80 <= int(p.replace(",", "")) <= 2000]
            if numeric:
                rate = min(numeric)
                logger.info(f"Universal Hard Rock rate: ${rate}/night")
                return float(rate)
        except Exception as e:
            logger.warning(f"Universal hotel scrape failed: {e}")

        logger.info(f"Universal hotel: using fallback ${FALLBACK_HOTEL_PER_NIGHT}/night")
        return float(FALLBACK_HOTEL_PER_NIGHT)

    async def _get_ticket_costs(self) -> float:
        try:
            await self.page.goto(TICKETS_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(1.5, 2.5)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            text = await self.page.text_content("body") or ""
            prices = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
            numeric = sorted([int(p.replace(",", "")) for p in prices if 80 <= int(p.replace(",", "")) <= 250])
            if len(numeric) >= 2:
                adult_per_day = numeric[-1]
                child_per_day = numeric[0]
                total = (adult_per_day * ADULTS + child_per_day * CHILDREN) * TICKET_DAYS
                logger.info(f"Universal tickets: ${total} total")
                return float(total)
        except Exception as e:
            logger.warning(f"Universal tickets scrape failed: {e}")

        fallback = (FALLBACK_TICKET_ADULT * ADULTS + FALLBACK_TICKET_CHILD * CHILDREN) * TICKET_DAYS
        logger.info(f"Universal tickets: using fallback ${fallback}")
        return float(fallback)
