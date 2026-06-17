from __future__ import annotations

"""
Xcaret Hotel all-inclusive scraper (Cancún).
7 nights all-inclusive for family of 6 (2 adults + 4 kids).
"""

import logging
import re
from datetime import date

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper

logger = logging.getLogger(__name__)

HOTEL_URL = "https://www.xcaret.com/en/hotel/"
BOOKING_URL = "https://www.xcaret.com/en/hotel/xcaret-hotel/#rates"

FALLBACK_PER_ADULT_PER_NIGHT = 400   # All-inclusive, rough estimate
FALLBACK_PER_CHILD_PER_NIGHT = 200   # Children's rate

ADULTS = 2
CHILDREN = 4   # All 4 kids (note: different from Disney — under-1 included here for all-inclusive billing)
NIGHTS = 7


class XcaretPackageScraper(BaseScraper):
    SOURCE = "xcaret_cancun"

    async def scrape(self) -> list:
        return []

    async def get_weekly_costs(self, week_starts: list[date]) -> dict[str, dict]:
        per_night = await self._get_rate()
        accommodation = per_night * NIGHTS

        results = {}
        for ws in week_starts:
            results[ws.isoformat()] = {
                "accommodation_price": round(accommodation, 2),
                "tickets_price": 0.0,
                "url": HOTEL_URL,
            }
        return results

    async def _get_rate(self) -> float:
        for url in [BOOKING_URL, HOTEL_URL]:
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await self._delay(2, 3)

                for sel in [
                    "button:has-text('Accept')",
                    "#onetrust-accept-btn-handler",
                    "button:has-text('Aceptar')",
                    "[aria-label*='close']",
                ]:
                    try:
                        await self.page.click(sel, timeout=3_000)
                        await self._delay(0.5, 1)
                        break
                    except PWTimeout:
                        pass

                await self.page.wait_for_load_state("networkidle", timeout=20_000)
                text = await self.page.text_content("body") or ""

                prices = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?|USD\s*([\d,]+)", text)
                numeric = []
                for m in prices:
                    val_str = m[0] or m[1]
                    if val_str:
                        v = int(val_str.replace(",", ""))
                        if 100 <= v <= 1500:
                            numeric.append(v)

                if numeric:
                    # Per-person nightly rate — multiply by family
                    rate_per_person = min(numeric)
                    total_per_night = rate_per_person * ADULTS + rate_per_person * 0.5 * CHILDREN
                    logger.info(f"Xcaret: ${rate_per_person}/person/night → ${total_per_night:.0f}/night family")
                    return total_per_night

            except Exception as e:
                logger.warning(f"Xcaret scrape failed ({url}): {e}")

        fallback = FALLBACK_PER_ADULT_PER_NIGHT * ADULTS + FALLBACK_PER_CHILD_PER_NIGHT * CHILDREN
        logger.info(f"Xcaret: using fallback ${fallback}/night")
        return float(fallback)
