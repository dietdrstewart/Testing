from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper, PriceRecord

logger = logging.getLogger(__name__)

SOURCE = "royal_caribbean"
# Homeport codes: 9 = Cape Liberty NJ, 11 = Miami, 14 = Port Canaveral
SEARCH_URL = (
    "https://www.royalcaribbean.com/cruises?"
    "homeport=9,11,14&duration=3-14"
)


class RoyalCaribbeanScraper(BaseScraper):
    SOURCE = SOURCE

    async def scrape(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []

        try:
            await self.page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=35_000)
            await self._delay(2, 4)

            # Dismiss cookie/modal banners
            for sel in [
                "button[aria-label*='close']",
                "button:has-text('Accept')",
                "#onetrust-accept-btn-handler",
                "button:has-text('No thanks')",
            ]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    await self._delay(0.5, 1)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=25_000)

            # Wait for cruise cards
            await self.page.wait_for_selector(
                "[class*='cruise-card'], [data-testid*='cruise'], [class*='CruiseCard'],"
                " .cruiseCard, [class*='sailing-card']",
                timeout=25_000,
            )

            cards = await self.page.locator(
                "[class*='cruise-card'], [class*='CruiseCard'], .cruiseCard, [class*='sailing-card']"
            ).all()

            logger.info(f"Royal Caribbean: found {len(cards)} cruise cards")

            today = date.today()
            cutoff = today + timedelta(days=180)

            for card in cards:
                try:
                    text = (await card.text_content() or "").strip()

                    # Ship name
                    ship = "Royal Caribbean Ship"
                    for sel in ["h2", "h3", "[class*='ship']", "[class*='name']"]:
                        try:
                            name = await card.locator(sel).first.text_content(timeout=1_000)
                            if name and name.strip() and len(name.strip()) < 80:
                                ship = name.strip()
                                break
                        except Exception:
                            pass

                    # Sail date
                    sail_date = today
                    date_match = re.search(
                        r"(\w+ \d{1,2},?\s*\d{4}|\d{4}-\d{2}-\d{2})", text
                    )
                    if date_match:
                        for fmt in ("%B %d, %Y", "%B %d %Y", "%Y-%m-%d"):
                            try:
                                sail_date = __import__("datetime").datetime.strptime(
                                    date_match.group(1).replace(",", ""), fmt.replace(",", "")
                                ).date()
                                break
                            except ValueError:
                                continue

                    if not (today <= sail_date <= cutoff):
                        continue

                    # Nights
                    nights_match = re.search(r"(\d+)\s*[Nn]ight", text)
                    nights = nights_match.group(1) if nights_match else "?"

                    # Homeport
                    port = "Unknown Port"
                    for p in ["Cape Liberty", "Miami", "Port Canaveral"]:
                        if p.lower() in text.lower():
                            port = p
                            break

                    # Price
                    price_matches = re.findall(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
                    if not price_matches:
                        continue
                    price = min(float(p.replace(",", "")) for p in price_matches)

                    # Cabin category
                    category = "Interior"
                    for cat in ["Suite", "Junior Suite", "Balcony", "Ocean View", "Interior"]:
                        if cat.lower() in text.lower():
                            category = cat
                            break

                    records.append(PriceRecord(
                        source=SOURCE,
                        product_name=f"{ship} ({nights}N from {port})",
                        category=category,
                        travel_date=sail_date.isoformat(),
                        price=price,
                        url=SEARCH_URL,
                    ))

                except Exception as e:
                    logger.debug(f"Royal Caribbean card parse error: {e}")

        except Exception as e:
            logger.error(f"Royal Caribbean scrape failed: {e}")

        logger.info(f"Royal Caribbean: scraped {len(records)} price records")
        return records
