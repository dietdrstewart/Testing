from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper, PriceRecord

logger = logging.getLogger(__name__)

SOURCE = "great_wolf"
# Scotrun PA is the closest location to Malvern PA (~1.5 hours)
RATES_URL = "https://www.greatwolf.com/pocono-mountains/rates"
LOCATION_NAME = "Great Wolf Lodge Pocono"


class GreatWolfScraper(BaseScraper):
    SOURCE = SOURCE

    async def scrape(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        today = date.today()

        try:
            await self.page.goto(RATES_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(2, 3)

            for sel in ["button:has-text('Accept')", "#onetrust-accept-btn-handler", "button:has-text('Close')"]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    await self._delay(0.5, 1)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=25_000)

            # Try to find rate cards / room cards
            cards = await self.page.locator(
                "[class*='rate'], [class*='room'], [class*='suite'], [class*='RoomCard'], article"
            ).all()

            seen_names: set[str] = set()

            for card in cards[:15]:
                try:
                    text = (await card.text_content() or "").strip()
                    price_matches = re.findall(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
                    if not price_matches:
                        continue

                    price = min(float(p.replace(",", "")) for p in price_matches)
                    if price < 80 or price > 1500:
                        continue

                    room_name = LOCATION_NAME
                    for sel2 in ["h2", "h3", "[class*='name']", "[class*='title']"]:
                        try:
                            n = await card.locator(sel2).first.text_content(timeout=1_000)
                            if n and n.strip() and len(n.strip()) > 3:
                                room_name = n.strip()[:80]
                                break
                        except Exception:
                            pass

                    if room_name in seen_names:
                        continue
                    seen_names.add(room_name)

                    category = "Standard Suite"
                    for cat_kw, cat_name in [
                        ("wolf den", "Wolf Den Suite"),
                        ("themed", "Themed Suite"),
                        ("deluxe", "Deluxe Suite"),
                        ("family", "Family Suite"),
                        ("cabin", "Cabin"),
                    ]:
                        if cat_kw in room_name.lower():
                            category = cat_name
                            break

                    for weeks_ahead in range(1, 26):
                        travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                        records.append(PriceRecord(
                            source=SOURCE,
                            product_name=room_name,
                            category=category,
                            travel_date=travel_date,
                            price=price,
                            url=RATES_URL,
                        ))

                except Exception as e:
                    logger.debug(f"Great Wolf card error: {e}")

            # Fallback: scrape prices from raw text if no cards found
            if not records:
                text = await self.page.text_content("body") or ""
                price_matches = re.findall(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
                prices = [float(p.replace(",", "")) for p in price_matches if 80 <= float(p.replace(",", "")) <= 1500]
                if prices:
                    price = min(prices)
                    for weeks_ahead in range(1, 26):
                        travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                        records.append(PriceRecord(
                            source=SOURCE,
                            product_name=LOCATION_NAME,
                            category="Standard Suite",
                            travel_date=travel_date,
                            price=price,
                            url=RATES_URL,
                        ))

        except Exception as e:
            logger.error(f"Great Wolf scrape failed: {e}")

        logger.info(f"Great Wolf: scraped {len(records)} price records")
        return records
