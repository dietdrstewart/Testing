from __future__ import annotations

import asyncio
import logging
import random
from typing import AsyncGenerator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}};
"""


class PriceRecord:
    """Lightweight container for a scraped price."""
    __slots__ = ("source", "product_name", "category", "travel_date", "price", "url")

    def __init__(
        self,
        source: str,
        product_name: str,
        category: str,
        travel_date: str,
        price: float,
        url: str = "",
    ):
        self.source = source
        self.product_name = product_name
        self.category = category
        self.travel_date = travel_date
        self.price = price
        self.url = url

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "product_name": self.product_name,
            "category": self.category,
            "travel_date": self.travel_date,
            "price": self.price,
            "url": self.url,
        }


class BaseScraper:
    SOURCE = "base"

    def __init__(self, headed: bool = False):
        self._headed = headed
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> BaseScraper:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=not self._headed,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        self.page = await self._context.new_page()
        await self.page.add_init_script(_STEALTH_SCRIPT)
        return self

    async def __aexit__(self, *_) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _delay(self, lo: float = 0.8, hi: float = 2.0) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    async def scrape(self) -> list[PriceRecord]:
        raise NotImplementedError
