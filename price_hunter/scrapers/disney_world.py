from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper, PriceRecord

logger = logging.getLogger(__name__)

SOURCE = "disney_world"
TICKETS_URL = "https://disneyworld.disney.go.com/admission/tickets/"
HOTELS_URL = "https://disneyworld.disney.go.com/resorts/"


class DisneyWorldScraper(BaseScraper):
    SOURCE = SOURCE

    async def scrape(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        records.extend(await self._scrape_tickets())
        records.extend(await self._scrape_hotels())
        logger.info(f"Disney World: scraped {len(records)} price records")
        return records

    async def _scrape_tickets(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        today = date.today()

        try:
            await self.page.goto(TICKETS_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(2, 3)

            for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept All')"]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            # Grab all price elements from the tickets page
            text = await self.page.text_content("body") or ""
            price_blocks = re.findall(
                r"([\w\s]+?(?:ticket|pass|day|park)[\w\s]*?)\$\s*([\d,]+(?:\.\d{2})?)",
                text, re.IGNORECASE
            )

            seen: set[float] = set()
            for label, amount_str in price_blocks[:20]:
                price = float(amount_str.replace(",", ""))
                if price < 50 or price > 1500 or price in seen:
                    continue
                seen.add(price)
                label_clean = label.strip()[:60]
                category = "Park Hopper" if "hopper" in label_clean.lower() else "Single Park"

                # Ticket prices apply to each upcoming date; sample every 2 weeks
                for weeks_ahead in range(1, 26):
                    travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                    records.append(PriceRecord(
                        source=SOURCE,
                        product_name="Disney World Ticket",
                        category=category,
                        travel_date=travel_date,
                        price=price,
                        url=TICKETS_URL,
                    ))
                break  # Use the first valid price found

        except Exception as e:
            logger.error(f"Disney World tickets scrape failed: {e}")

        return records

    async def _scrape_hotels(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []
        today = date.today()

        try:
            await self.page.goto(HOTELS_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(2, 3)
            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            # Try to find resort cards with prices
            hotel_cards = await self.page.locator(
                "[class*='resort'], [class*='hotel'], article[class*='card']"
            ).all()

            for card in hotel_cards[:15]:
                try:
                    text = (await card.text_content() or "").strip()
                    price_match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
                    if not price_match:
                        continue

                    price = float(price_match.group(1).replace(",", ""))
                    if price < 100 or price > 5000:
                        continue

                    # Hotel name from heading
                    hotel_name = "Disney Resort"
                    for sel in ["h2", "h3", "[class*='name']", "[class*='title']"]:
                        try:
                            name = await card.locator(sel).first.text_content(timeout=1_000)
                            if name and name.strip():
                                hotel_name = name.strip()[:80]
                                break
                        except Exception:
                            pass

                    category = "Standard Room"
                    if "deluxe" in hotel_name.lower():
                        category = "Deluxe Room"
                    elif "value" in hotel_name.lower():
                        category = "Value Room"
                    elif "moderate" in hotel_name.lower():
                        category = "Moderate Room"

                    for weeks_ahead in range(1, 26):
                        travel_date = (today + timedelta(weeks=weeks_ahead)).isoformat()
                        records.append(PriceRecord(
                            source=SOURCE,
                            product_name=hotel_name,
                            category=category,
                            travel_date=travel_date,
                            price=price,
                            url=HOTELS_URL,
                        ))
                    break  # One sample rate per hotel is enough per scan

                except Exception as e:
                    logger.debug(f"Disney World hotel card error: {e}")

        except Exception as e:
            logger.error(f"Disney World hotels scrape failed: {e}")

        return records
