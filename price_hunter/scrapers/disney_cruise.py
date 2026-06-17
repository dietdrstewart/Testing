from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper, PriceRecord

logger = logging.getLogger(__name__)

# Ports the user cares about
TARGET_PORTS = {"Port Canaveral", "Miami", "Cape Liberty", "New York"}

SOURCE = "disney_cruise"
BASE_URL = "https://disneycruise.disney.go.com"
SEARCH_URL = f"{BASE_URL}/cruises-and-packages/find-a-cruise/"


class DisneyCruiseScraper(BaseScraper):
    SOURCE = SOURCE

    async def scrape(self) -> list[PriceRecord]:
        records: list[PriceRecord] = []

        try:
            await self.page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._delay(2, 4)

            # Dismiss any overlays/cookie banners
            for sel in ["button[aria-label*='Accept']", "button:has-text('Accept')", "#onetrust-accept-btn-handler"]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    await self._delay(0.5, 1)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            # Collect all cruise result cards
            await self.page.wait_for_selector(
                "[class*='cruise-result'], [class*='CruiseCard'], [data-testid*='cruise'],"
                " .cruiseResult, article[class*='cruise']",
                timeout=20_000,
            )

            cards = await self.page.locator(
                "[class*='cruise-result'], [class*='CruiseCard'], .cruiseResult, article[class*='cruise']"
            ).all()

            logger.info(f"Disney Cruise: found {len(cards)} cruise cards")

            today = date.today()
            cutoff = today + timedelta(days=180)

            for card in cards:
                try:
                    text = (await card.text_content() or "").strip()

                    # Port filter
                    port_match = any(p.lower() in text.lower() for p in TARGET_PORTS)
                    if not port_match:
                        continue

                    # Ship name
                    ship = "Disney Cruise"
                    for sel in ["h2", "h3", "[class*='ship']", "[class*='title']"]:
                        try:
                            name = await card.locator(sel).first.text_content(timeout=1_000)
                            if name and name.strip():
                                ship = name.strip()[:80]
                                break
                        except Exception:
                            pass

                    # Sail date
                    sail_date = today
                    date_match = re.search(
                        r"(\w+ \d{1,2},?\s*\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", text
                    )
                    if date_match:
                        for fmt in ("%B %d, %Y", "%B %d %Y", "%Y-%m-%d", "%m/%d/%Y"):
                            try:
                                sail_date = __import__("datetime").datetime.strptime(
                                    date_match.group(1).replace(",", ""), fmt.replace(",", "")
                                ).date()
                                break
                            except ValueError:
                                continue

                    if not (today <= sail_date <= cutoff):
                        continue

                    # Night count
                    nights_match = re.search(r"(\d+)\s*[Nn]ight", text)
                    nights = nights_match.group(1) if nights_match else "?"

                    # Price — grab all dollar amounts, use the lowest as per-person
                    price_matches = re.findall(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
                    if not price_matches:
                        continue
                    prices = [float(p.replace(",", "")) for p in price_matches]
                    price = min(prices)

                    # Category (cabin type from text or default)
                    category = "Interior"
                    for cat in ["Suite", "Concierge", "Verandah", "Oceanview", "Interior"]:
                        if cat.lower() in text.lower():
                            category = cat
                            break

                    # Port
                    port = next((p for p in TARGET_PORTS if p.lower() in text.lower()), "Unknown Port")

                    records.append(PriceRecord(
                        source=SOURCE,
                        product_name=f"{ship} ({nights}N from {port})",
                        category=category,
                        travel_date=sail_date.isoformat(),
                        price=price,
                        url=SEARCH_URL,
                    ))

                except Exception as e:
                    logger.debug(f"Disney Cruise card parse error: {e}")

        except Exception as e:
            logger.error(f"Disney Cruise scrape failed: {e}")

        logger.info(f"Disney Cruise: scraped {len(records)} price records")
        return records
