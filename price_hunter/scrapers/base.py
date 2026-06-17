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
    __slots__ = ("source", "product_name", "category", "travel_date", "price", "url")

    def __init__(self, source, product_name, category, travel_date, price, url=""):
        self.source = source
        self.product_name = product_name
        self.category = category
        self.travel_date = travel_date
        self.price = price
        self.url = url

    def to_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}


class BaseScraper:
    """
    Supports two modes:
      - Standalone (default): launches and owns its own Playwright browser.
      - Shared-browser: accepts an external BrowserContext; only manages a page.

    Usage (shared mode):
        ctx = await browser.new_context(...)
        async with DisneyPackageScraper(context=ctx) as scraper:
            result = await scraper.get_weekly_costs(...)
        await ctx.close()   # caller closes the context
    """

    SOURCE = "base"

    def __init__(self, headed: bool = False, context: BrowserContext | None = None):
        self._headed = headed
        self._external_context = context
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = context  # pre-filled if shared
        self.page: Page | None = None

    async def __aenter__(self) -> BaseScraper:
        if self._external_context is not None:
            # Shared-browser path — context already exists, just open a page
            self.page = await self._context.new_page()
            await self.page.add_init_script(_STEALTH_SCRIPT)
            return self

        # Standalone path — launch our own browser
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=not self._headed,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await _make_context(self._browser)
        self.page = await self._context.new_page()
        await self.page.add_init_script(_STEALTH_SCRIPT)
        return self

    async def __aexit__(self, *_) -> None:
        if self.page:
            await self.page.close()
        if self._external_context is not None:
            return  # Context is managed by caller — do NOT close it
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _delay(self, lo: float = 0.8, hi: float = 2.0) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    async def scrape(self) -> list:
        raise NotImplementedError


async def _make_context(browser: Browser) -> BrowserContext:
    """Creates a stealth browser context. Used by both standalone and parallel paths."""
    ctx = await browser.new_context(
        user_agent=_USER_AGENT,
        viewport={"width": 1366, "height": 768},
        locale="en-US",
    )
    return ctx
