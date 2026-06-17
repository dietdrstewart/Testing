from __future__ import annotations

"""
Royal Caribbean Icon-class 7-night Caribbean cruise scraper.
Ships: Icon of the Seas (Miami), Star of the Seas (Port Canaveral).
Searches for 7-night sailings closest to each target Sunday.
Family of 6 — priced as a Family Stateroom or 2 connecting interiors.
"""

import logging
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PWTimeout

from .base import BaseScraper

logger = logging.getLogger(__name__)

SEARCH_URL = (
    "https://www.royalcaribbean.com/cruises?"
    "ship=icon-of-the-seas,star-of-the-seas"
    "&duration=7&homeport=11,14"   # 11=Miami, 14=Port Canaveral
)

FALLBACK_PER_PERSON = 1400   # 7-night Icon class, midrange estimate
TRAVELERS = 6                 # full family


class RoyalCaribbeanIconScraper(BaseScraper):
    SOURCE = "royal_icon_cruise"

    async def scrape(self) -> list:
        return []

    async def get_weekly_costs(self, week_starts: list[date]) -> dict[str, dict]:
        """Returns {week_start_iso: {accommodation_price, url}}"""
        sailings = await self._get_sailings()
        results = {}

        for ws in week_starts:
            # Find the sailing whose departure date is closest to this Sunday
            best = self._match_sailing(sailings, ws)
            if best:
                results[ws.isoformat()] = {
                    "accommodation_price": round(best["price"], 2),
                    "tickets_price": 0.0,
                    "url": SEARCH_URL,
                }
            else:
                # Use fallback
                results[ws.isoformat()] = {
                    "accommodation_price": round(FALLBACK_PER_PERSON * TRAVELERS, 2),
                    "tickets_price": 0.0,
                    "url": SEARCH_URL,
                }

        return results

    async def _get_sailings(self) -> list[dict]:
        sailings = []
        try:
            await self.page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=35_000)
            await self._delay(2, 4)

            for sel in [
                "#onetrust-accept-btn-handler",
                "button:has-text('Accept')",
                "button:has-text('No thanks')",
            ]:
                try:
                    await self.page.click(sel, timeout=3_000)
                    await self._delay(0.5, 1)
                    break
                except PWTimeout:
                    pass

            await self.page.wait_for_load_state("networkidle", timeout=25_000)

            cards = await self.page.locator(
                "[class*='cruise-card'], [class*='CruiseCard'], .cruiseCard, [class*='sailing']"
            ).all()

            logger.info(f"Royal Caribbean Icon: found {len(cards)} sailing cards")

            for card in cards:
                try:
                    text = (await card.text_content() or "").strip()

                    # Filter for 7-night
                    if "7" not in text or "night" not in text.lower():
                        continue

                    # Departure date
                    date_match = re.search(r"(\w+ \d{1,2},?\s*\d{4}|\d{4}-\d{2}-\d{2})", text)
                    if not date_match:
                        continue
                    dep_date = None
                    for fmt in ("%B %d %Y", "%B %d, %Y", "%Y-%m-%d"):
                        try:
                            dep_date = __import__("datetime").datetime.strptime(
                                date_match.group(1).replace(",", ""), fmt.replace(",", "")
                            ).date()
                            break
                        except ValueError:
                            continue
                    if not dep_date or dep_date < date.today():
                        continue

                    # Price — look for lowest per-person, then multiply by 6
                    price_matches = re.findall(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
                    if not price_matches:
                        continue
                    per_person = min(int(p.replace(",", "")) for p in price_matches)
                    if per_person < 200:
                        continue
                    total_price = per_person * TRAVELERS

                    sailings.append({"departure": dep_date, "price": total_price})

                except Exception as e:
                    logger.debug(f"Icon sailing card error: {e}")

        except Exception as e:
            logger.error(f"Royal Caribbean Icon scrape failed: {e}")

        logger.info(f"Royal Caribbean Icon: found {len(sailings)} valid sailings")
        return sailings

    def _match_sailing(self, sailings: list[dict], week_start: date) -> dict | None:
        """Find sailing within ±3 days of the target Sunday."""
        best = None
        best_delta = timedelta(days=4)
        for s in sailings:
            delta = abs(s["departure"] - week_start)
            if delta < best_delta:
                best = s
                best_delta = delta
        return best
