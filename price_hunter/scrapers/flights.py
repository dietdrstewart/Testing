from __future__ import annotations

"""
Flight price scraper — parallel routes, sampled dates.

Optimizations vs. v1:
  - All 4 routes run CONCURRENTLY (separate browser contexts, one per route).
  - Staggered 1.5-second starts so Google sees sequential-ish traffic.
  - Sampled date set (17 weeks instead of 26) passed in by the caller.
  - Per-route functions accept an explicit `page` arg (no self.page dependency).
"""

import asyncio
import logging
import random
import re
from collections import defaultdict
from datetime import date, timedelta

from playwright.async_api import Browser, Page, TimeoutError as PWTimeout

from .base import BaseScraper, _USER_AGENT, _STEALTH_SCRIPT

logger = logging.getLogger(__name__)

ROUTES = {
    "MCO": ("PHL", "MCO"),   # Disney + Universal
    "MIA": ("PHL", "MIA"),   # Royal Caribbean
    "CUN": ("PHL", "CUN"),   # Xcaret
    "NCE": ("PHL", "NCE"),   # Nice France
}

DOMESTIC_ROUTES = {"MCO", "MIA"}
INTL_INFANT_FACTOR = 1.05   # ~5% international infant surcharge
PAID_SEATS = 5               # 2 adults + 3 children; infant on lap

# Fallback family round-trip prices (5 paid seats) used when live scraping is blocked.
# Based on typical PHL departure prices; updated manually if averages drift significantly.
ROUTE_FALLBACKS: dict[str, float] = {
    "MCO": 1_500.0,   # PHL→MCO ~$300/person × 5 (domestic)
    "MIA": 1_750.0,   # PHL→MIA ~$350/person × 5 (domestic)
    "CUN": 2_625.0,   # PHL→CUN ~$500/person × 5 × 1.05 (international)
    "NCE": 5_775.0,   # PHL→NCE ~$1,100/person × 5 × 1.05 (international)
}


class FlightScraper(BaseScraper):
    SOURCE = "flights"

    async def scrape(self) -> list:
        return []

    # ── Public API ──────────────────────────────────────────────────────────

    async def scrape_all_routes_parallel(
        self,
        sampled_weeks: list[tuple[date, date]],
        browser: Browser,
    ) -> dict[str, dict[str, float]]:
        """
        Runs all 4 routes concurrently, each in its own BrowserContext.
        Returns {dest_code: {sunday_iso: round_trip_family_price}}.
        """
        sunday_dates = sorted({ws for ws, _ in sampled_weeks})

        async def _one_route(dest_code: str, origin: str, dest: str, delay: float):
            await asyncio.sleep(delay)   # stagger starts to reduce simultaneous fingerprinting
            from playwright.async_api import async_playwright
            ctx = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={
                    "width": random.randint(1280, 1440),
                    "height": random.randint(720, 900),
                },
                locale="en-US",
            )
            page = await ctx.new_page()
            await page.add_init_script(_STEALTH_SCRIPT)
            try:
                prices = await _scrape_route_on_page(page, origin, dest, sunday_dates, dest_code)
                return dest_code, prices
            except Exception as e:
                logger.error(f"Route {origin}→{dest} failed: {e}")
                return dest_code, {}
            finally:
                await ctx.close()

        tasks = [
            _one_route(dest_code, origin, dest, i * 1.5)
            for i, (dest_code, (origin, dest)) in enumerate(ROUTES.items())
        ]
        route_results = await asyncio.gather(*tasks, return_exceptions=True)

        out: dict[str, dict[str, float]] = defaultdict(dict)
        for item in route_results:
            if isinstance(item, Exception):
                logger.error(f"Route task exception: {item}")
                continue
            dest_code, prices = item
            out[dest_code].update(prices)

        # For any route that returned nothing (bot-blocked, timeout, etc.), fill in fallbacks
        # so package assembler always has flight costs to work with.
        for dest_code in ROUTES:
            if not out.get(dest_code):
                fallback = ROUTE_FALLBACKS.get(dest_code, 0.0)
                logger.warning(
                    f"Flight route {dest_code}: no live prices scraped — "
                    f"using fallback ${fallback:,.0f} per week"
                )
                out[dest_code] = {d.isoformat(): fallback for d in sunday_dates}

        total = sum(len(v) for v in out.values())
        logger.info(f"Flights: collected {total} price points across {len(out)} routes")
        return dict(out)


# ── Page-level helpers (module-level so they can be called without self.page) ──

async def _scrape_route_on_page(
    page: Page,
    origin: str,
    dest: str,
    outbound_dates: list[date],
    dest_code: str,
) -> dict[str, float]:
    prices: dict[str, float] = {}
    for out_date in outbound_dates:
        ret_date = out_date + timedelta(days=6)
        price = await _get_price_on_page(page, origin, dest, out_date, ret_date, dest_code)
        if price:
            prices[out_date.isoformat()] = price
    return prices


async def _get_price_on_page(
    page: Page,
    origin: str,
    dest: str,
    out: date,
    ret: date,
    dest_code: str,
) -> float | None:
    # Passenger string: a=adults, c=children count, il=infants on lap
    url = (
        f"https://www.google.com/travel/flights?hl=en&curr=USD"
        f"#flt={origin}.{dest}.{out.isoformat()}*{dest}.{origin}.{ret.isoformat()}"
        f";a2;c:3;il:1;t:f;tt:o"
    )
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(random.uniform(2.0, 3.5))

        for sel in ["button:has-text('Accept all')", "button:has-text('I agree')", "[aria-label*='Accept']"]:
            try:
                await page.click(sel, timeout=2_000)
                await asyncio.sleep(0.5)
                break
            except PWTimeout:
                pass

        await page.wait_for_load_state("networkidle", timeout=18_000)

        text = await page.text_content("body") or ""
        found = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
        numeric = sorted(int(p.replace(",", "")) for p in found if 50 <= int(p.replace(",", "")) <= 3000)

        if not numeric:
            return None

        # Google shows per-person; multiply by paid seats
        family_total = numeric[0] * PAID_SEATS
        if dest_code not in DOMESTIC_ROUTES:
            family_total = int(family_total * INTL_INFANT_FACTOR)

        return float(family_total)

    except Exception as e:
        logger.debug(f"Flight price error {origin}→{dest} {out}: {e}")
        return None
