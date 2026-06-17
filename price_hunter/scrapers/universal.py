from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper, PriceRecord

logger = logging.getLogger(__name__)

SOURCE = "universal"
TICKETS_URL = "https://www.universalorlando.com/web/en/us/tickets-passes"
HOTELS_URL = "https://www.universalorlando.com/web/en/us/plan-your-visit/hotels"


class UniversalScraper(BaseScraper):
    SOURCE = SOURCE

    async def scrape(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        records.extend(await self._scrape_tickets())
        records.extend(await self._scrape_hotels())
        logger.info(f"Universal: scraped {len(records)} price records")
        return records

    async def _scrape_tickets(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        today = date.today()

        try:
            await self.page.goto(TICKETS_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(2, 3)

            for sel in ["button:has-text('Accept')", "#onetrust-accept-btn-handler", "button:has-text('Close')"]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    await self._delay(0.5, 1)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            # Scrape ticket cards
            ticket_cards = await self.page.locator(
                "[class*='ticket'], [class*='pass-card'], [class*='product-card'], [class*='TicketCard']"
            ).all()

            for card in ticket_cards[:10]:
                try:
                    text = (await card.text_content() or "").strip()
                    price_matches = re.findall(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
                    if not price_matches:
                        continue

                    price = min(float(p.replace(",", "")) for p in price_matches)
                    if price < 50 or price > 1500:
                        continue

                    name = "Universal Ticket"
                    for sel2 in ["h2", "h3", "[class*='name']", "[class*='title']"]:
                        try:
                            n = await card.locator(sel2).first.text_content(timeout=1_000)
                            if n and n.strip():
                                name = n.strip()[:60]
                                break
                        except Exception:
                            pass

                    category = "General Admission"
                    if "express" in name.lower():
                        category = "Express Pass"
                    elif "annual" in name.lower():
                        category = "Annual Pass"

                    for weeks_ahead in range(1, 26):
                        travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                        records.append(PriceRecord(
                            source=SOURCE,
                            product_name=name,
                            category=category,
                            travel_date=travel_date,
                            price=price,
                            url=TICKETS_URL,
                        ))

                except Exception as e:
                    logger.debug(f"Universal ticket card error: {e}")

        except Exception as e:
            logger.error(f"Universal tickets scrape failed: {e}")

        return records

    async def _scrape_hotels(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        today = date.today()

        try:
            await self.page.goto(HOTELS_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(2, 3)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            hotel_cards = await self.page.locator(
                "[class*='hotel'], [class*='resort'], article[class*='card']"
            ).all()

            for card in hotel_cards[:8]:
                try:
                    text = (await card.text_content() or "").strip()
                    price_match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
                    if not price_match:
                        continue

                    price = float(price_match.group(1).replace(",", ""))
                    if price < 80 or price > 2000:
                        continue

                    hotel_name = "Universal Hotel"
                    for sel2 in ["h2", "h3", "[class*='name']"]:
                        try:
                            n = await card.locator(sel2).first.text_content(timeout=1_000)
                            if n and n.strip():
                                hotel_name = n.strip()[:80]
                                break
                        except Exception:
                            pass

                    for weeks_ahead in range(1, 26):
                        travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                        records.append(PriceRecord(
                            source=SOURCE,
                            product_name=hotel_name,
                            category="Standard Room",
                            travel_date=travel_date,
                            price=price,
                            url=HOTELS_URL,
                        ))

                except Exception as e:
                    logger.debug(f"Universal hotel card error: {e}")

        except Exception as e:
            logger.error(f"Universal hotels scrape failed: {e}")

        return records
