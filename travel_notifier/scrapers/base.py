from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from ..config import Config

logger = logging.getLogger(__name__)

# Realistic macOS Chrome user-agent
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Injected on every page to hide automation flags
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = {runtime: {}};
"""


class ScraperError(Exception):
    pass


class SessionExpiredError(ScraperError):
    pass


class LoginFailedError(ScraperError):
    pass


class CaptchaError(ScraperError):
    pass


class ParseError(ScraperError):
    pass


class BaseScraper:
    COOKIE_FILE: Path  # Set by subclass

    def __init__(self, config: Config):
        self._config = config
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> BaseScraper:
        self._playwright = await async_playwright().start()
        self._browser = await self._launch_browser()
        self._context = await self._create_context(self._browser)
        await self._load_cookies()
        self.page = await self._context.new_page()
        await self.page.add_init_script(_STEALTH_SCRIPT)
        return self

    async def __aexit__(self, *args) -> None:
        try:
            await self._save_cookies()
        except Exception as e:
            logger.warning(f"Could not save cookies: {e}")
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _launch_browser(self) -> Browser:
        return await self._playwright.chromium.launch(
            headless=not self._config.headed_browser,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ],
        )

    async def _create_context(self, browser: Browser) -> BrowserContext:
        return await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/Chicago",
        )

    async def _load_cookies(self) -> None:
        cookie_path = self._config.cookie_dir / self.COOKIE_FILE.name
        if not cookie_path.exists():
            return
        try:
            with open(cookie_path) as f:
                cookies = json.load(f)
            await self._context.add_cookies(cookies)
            logger.debug(f"Loaded {len(cookies)} cookies from {cookie_path}")
        except Exception as e:
            logger.warning(f"Could not load cookies from {cookie_path}: {e}")

    async def _save_cookies(self) -> None:
        if not self._context:
            return
        cookie_path = self._config.cookie_dir / self.COOKIE_FILE.name
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        cookies = await self._context.cookies()
        with open(cookie_path, "w") as f:
            json.dump(cookies, f)
        logger.debug(f"Saved {len(cookies)} cookies to {cookie_path}")

    async def _random_delay(self, min_ms: int = 500, max_ms: int = 2000) -> None:
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)

    async def _human_type(self, selector: str, text: str) -> None:
        """Type text character by character with random keystroke delays."""
        locator = self.page.locator(selector).first
        await locator.click()
        for char in text:
            await self.page.keyboard.type(char, delay=random.randint(50, 150))

    async def _prompt_mfa(self, prompt: str) -> str:
        """Pause async loop to collect MFA code from the terminal."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, input, prompt)

    async def is_logged_in(self) -> bool:
        raise NotImplementedError

    async def login(self) -> bool:
        raise NotImplementedError

    async def scrape(self) -> list:
        raise NotImplementedError
