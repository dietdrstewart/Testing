from __future__ import annotations

"""
Scrapes round-trip flight prices from Google Flights for all routes
used by the 5 vacation packages. Uses the price calendar view to get
multiple weeks of prices in a single browser session.

Family: 2 adults + 3 children (9,6,4) + 1 lap infant.
Prices are for all paid travelers (5 seats; infant is on lap = free domestic,
~10% of adult fare international — approximated here as a flat 5% add-on).
"""

import logging
import re
from collections import defaultdict
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Routes needed across all 5 vacation packages
ROUTES = {
    "MCO": ("PHL", "MCO"),   # Disney + Universal
    "MIA": ("PHL", "MIA"),   # Royal Caribbean
    "CUN": ("PHL", "CUN"),   # Xcaret
    "NCE": ("PHL", "NCE"),   # Nice France
}

# Multiplier for international infant surcharge (rough ~5% of total)
INTL_INFANT_FACTOR = 1.05
DOMESTIC_ROUTES = {"MCO", "MIA"}


class FlightScraper(BaseScraper):
    """Returns {destination_code: {iso_date: round_trip_price_for_family}}"""

    SOURCE = "flights"

    async def scrape_all_routes(self, weeks: list[tuple[date, date]]) -> dict[str, dict[str, float]]:
        """Scrapes all required routes for the given (sunday, saturday) week pairs."""
        results: dict[str, dict[str, float]] = defaultdict(dict)

        # Collect the outbound (Sunday) dates we need
        sunday_dates = sorted({ws for ws, _ in weeks})

        for dest_code, (origin, dest) in ROUTES.items():
            logger.info(f"Flights: scraping {origin}→{dest}")
            prices = await self._scrape_route(origin, dest, sunday_dates)
            for d, price in prices.items():
                results[dest_code][d] = price

        return results

    async def _scrape_route(
        self, origin: str, dest: str, outbound_dates: list[date]
    ) -> dict[str, float]:
        """Returns {outbound_iso_date: total_family_round_trip_price}."""
        prices: dict[str, float] = {}

        for outbound in outbound_dates:
            inbound = outbound + timedelta(days=6)   # Saturday return
            price = await self._get_price(origin, dest, outbound, inbound)
            if price:
                prices[outbound.isoformat()] = price

        return prices

    async def _get_price(
        self, origin: str, dest: str, out: date, ret: date
    ) -> float | None:
        """Get cheapest round-trip price for 2 adults + 3 children for one date pair."""
        # Google Flights URL: passenger params a2c3il1 = 2 adults, 3 children, 1 infant on lap
        url = (
            f"https://www.google.com/travel/flights?hl=en&curr=USD"
            f"#flt={origin}.{dest}.{out.isoformat()}*{dest}.{origin}.{ret.isoformat()}"
            f";a2;c:3;il:1;t:f;tt:o"
        )

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(2.5, 4.0)

            # Dismiss cookie/consent banners
            for sel in [
                "button:has-text('Accept all')",
                "button:has-text('I agree')",
                "[aria-label*='Accept']",
            ]:
                try:
                    await self.page.click(sel, timeout=2_000)
                    await self._delay(0.5, 1.0)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            # Try to find the cheapest price shown
            text = await self.page.text_content("body") or ""

            # Google Flights shows prices like "$342" or "$1,234"
            # Look for prices that are reasonable per-person flight costs
            prices_found = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
            numeric = sorted(
                [int(p.replace(",", "")) for p in prices_found if 50 <= int(p.replace(",", "")) <= 3000]
            )

            if not numeric:
                logger.debug(f"No prices found for {origin}→{dest} {out}")
                return None

            # Google shows per-person price; multiply by paid seats
            per_person = numeric[0]
            family_total = per_person * 5   # 5 paid seats

            # Add international infant fare approximation
            if dest not in DOMESTIC_ROUTES:
                family_total = int(family_total * INTL_INFANT_FACTOR)

            logger.debug(f"  {origin}→{dest} {out}: ${per_person}/person → ${family_total} family")
            return float(family_total)

        except Exception as e:
            logger.debug(f"Flight price error {origin}→{dest} {out}: {e}")
            return None

    async def scrape(self) -> list:
        # Not used directly; use scrape_all_routes()
        return []
