from __future__ import annotations

"""
Disney World package scraper.
Fetches: Art of Animation Family Suite nightly rate + 4-day park ticket prices.
Tickets for: 2 adults + 3 children (9,6,4). Child under 3 is free.
Returns total accommodation + tickets cost (flights added by package_scanner).
"""

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper

logger = logging.getLogger(__name__)

RESORT_URL = "https://disneyworld.disney.go.com/resorts/art-of-animation-resort/"
TICKETS_URL = "https://disneyworld.disney.go.com/admission/tickets/"

# Fallback estimates when scraping fails (updated periodically)
FALLBACK_HOTEL_PER_NIGHT = 400    # Art of Animation Family Suite midrange
FALLBACK_TICKET_ADULT = 109       # 4-day adult base ticket per day estimate
FALLBACK_TICKET_CHILD = 104       # 4-day child base ticket per day estimate

# Family: 2 adults + 3 children; infant under 3 is free at Disney
ADULTS = 2
CHILDREN = 3   # ages 9, 6, 4
NIGHTS = 7
TICKET_DAYS = 4


class DisneyPackageScraper(BaseScraper):
    SOURCE = "disney_package"

    async def scrape(self) -> list:
        return []

    async def get_weekly_costs(self, week_starts: list[date]) -> dict[str, dict]:
        """Returns {week_start_iso: {accommodation, tickets, total}}"""
        results = {}
        hotel_per_night = await self._get_hotel_rate()
        ticket_costs = await self._get_ticket_costs()

        accommodation = hotel_per_night * NIGHTS
        tickets = ticket_costs

        for ws in week_starts:
            results[ws.isoformat()] = {
                "accommodation_price": round(accommodation, 2),
                "tickets_price": round(tickets, 2),
                "url": RESORT_URL,
            }
        return results

    async def _get_hotel_rate(self) -> float:
        try:
            await self.page.goto(RESORT_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(1.5, 2.5)

            for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept All')"]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            text = await self.page.text_content("body") or ""

            prices = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
            numeric = [int(p.replace(",", "")) for p in prices if 100 <= int(p.replace(",", "")) <= 2000]
            if numeric:
                rate = min(numeric)
                logger.info(f"Disney hotel rate: ${rate}/night")
                return float(rate)
        except Exception as e:
            logger.warning(f"Disney hotel scrape failed: {e}")

        logger.info(f"Disney hotel: using fallback ${FALLBACK_HOTEL_PER_NIGHT}/night")
        return float(FALLBACK_HOTEL_PER_NIGHT)

    async def _get_ticket_costs(self) -> float:
        try:
            await self.page.goto(TICKETS_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(1.5, 2.5)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
            text = await self.page.text_content("body") or ""

            prices = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
            numeric = sorted([int(p.replace(",", "")) for p in prices if 50 <= int(p.replace(",", "")) <= 200])

            if len(numeric) >= 2:
                adult_per_day = numeric[-1]  # Higher price = adult
                child_per_day = numeric[0]   # Lower price = child
                total = (adult_per_day * ADULTS + child_per_day * CHILDREN) * TICKET_DAYS
                logger.info(f"Disney tickets: ${adult_per_day} adult, ${child_per_day} child/day → ${total} total")
                return float(total)
        except Exception as e:
            logger.warning(f"Disney ticket scrape failed: {e}")

        fallback = (FALLBACK_TICKET_ADULT * ADULTS + FALLBACK_TICKET_CHILD * CHILDREN) * TICKET_DAYS
        logger.info(f"Disney tickets: using fallback ${fallback}")
        return float(fallback)
