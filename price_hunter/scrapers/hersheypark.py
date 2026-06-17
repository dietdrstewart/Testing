from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper, PriceRecord

logger = logging.getLogger(__name__)

SOURCE = "hersheypark"
TICKETS_URL = "https://www.hersheypark.com/tickets/"
HOTEL_URL = "https://www.hersheypark.com/lodging/"


class HersheyparkScraper(BaseScraper):
    SOURCE = SOURCE

    async def scrape(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        records.extend(await self._scrape_tickets())
        records.extend(await self._scrape_hotel())
        logger.info(f"Hersheypark: scraped {len(records)} price records")
        return records

    async def _scrape_tickets(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        today = date.today()

        try:
            await self.page.goto(TICKETS_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(1.5, 2.5)

            for sel in ["button:has-text('Accept')", "#onetrust-accept-btn-handler"]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            text = await self.page.text_content("body") or ""

            # Extract ticket name / price pairs from the page
            price_matches = re.findall(
                r"([A-Za-z][\w\s\-&]+?)\s+\$\s*([\d,]+(?:\.\d{2})?)", text
            )

            seen_prices: set[float] = set()
            for label, amount_str in price_matches[:20]:
                price = float(amount_str.replace(",", ""))
                if price < 20 or price > 500 or price in seen_prices:
                    continue
                seen_prices.add(price)

                label_clean = label.strip()[-60:]
                category = "General Admission"
                if "season" in label_clean.lower():
                    category = "Season Pass"
                elif "preview" in label_clean.lower():
                    category = "Preview Day"

                # Sample upcoming weekends (Hersheypark is a seasonal park)
                for weeks_ahead in range(1, 26):
                    travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                    records.append(PriceRecord(
                        source=SOURCE,
                        product_name="Hersheypark Admission",
                        category=category,
                        travel_date=travel_date,
                        price=price,
                        url=TICKETS_URL,
                    ))
                if len(seen_prices) >= 3:
                    break

        except Exception as e:
            logger.error(f"Hersheypark tickets scrape failed: {e}")

        return records

    async def _scrape_hotel(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        today = date.today()

        try:
            await self.page.goto(HOTEL_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(1.5, 2.5)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            text = await self.page.text_content("body") or ""
            price_matches = re.findall(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
            prices = [float(p.replace(",", "")) for p in price_matches if 80 <= float(p.replace(",", "")) <= 800]

            if prices:
                price = min(prices)
                for weeks_ahead in range(1, 26):
                    travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                    records.append(PriceRecord(
                        source=SOURCE,
                        product_name="Hershey Lodge",
                        category="Standard Room",
                        travel_date=travel_date,
                        price=price,
                        url=HOTEL_URL,
                    ))

        except Exception as e:
            logger.error(f"Hersheypark lodging scrape failed: {e}")

        return records
