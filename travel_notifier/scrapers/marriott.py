from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..config import Config
from ..models.hotel import HotelStay
from .base import (
    BaseScraper,
    LoginFailedError,
    SessionExpiredError,
)

logger = logging.getLogger(__name__)


class MarriottScraper(BaseScraper):
    COOKIE_FILE = Path("marriott.json")

    LOGIN_URL = "https://www.marriott.com/sign-in.mi"
    MY_TRIPS_URL = "https://www.marriott.com/loyalty/myAccount/myTrips.mi"

    async def is_logged_in(self) -> bool:
        try:
            await self.page.goto(self.MY_TRIPS_URL, wait_until="domcontentloaded", timeout=30000)
            await self.page.wait_for_load_state("networkidle", timeout=15000)
            url = self.page.url
            if "sign-in" in url.lower() or "login" in url.lower():
                return False
            try:
                await self.page.wait_for_selector(
                    "[data-component='trip-summary'], .mytrips, .upcoming-stays, .reservation-card",
                    timeout=8000,
                )
                return True
            except PlaywrightTimeout:
                # May be logged in but with no trips
                return "myAccount" in url or "loyalty" in url
        except Exception as e:
            logger.debug(f"Marriott is_logged_in failed: {e}")
            return False

    async def login(self) -> bool:
        logger.info("Logging in to Marriott Bonvoy...")
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await self._random_delay(1000, 2000)

        await self._check_captcha()

        # Step 1: Enter email/username
        try:
            await self.page.wait_for_selector("#username, input[name='username'], input[type='email']", timeout=10000)
        except PlaywrightTimeout:
            raise LoginFailedError("Could not find Marriott username field")

        await self._human_type(
            "#username, input[name='username'], input[type='email']",
            self._config.marriott_username,
        )
        await self._random_delay(600, 1200)

        # Click "Next" for two-step login flow
        try:
            next_btn = self.page.locator("button:has-text('Next'), input[value='Next'], [data-test='next-btn']").first
            await next_btn.click(timeout=8000)
            await self._random_delay(1200, 2000)
        except PlaywrightTimeout:
            # Single-step form — password may already be visible
            pass

        # Step 2: Enter password
        try:
            await self.page.wait_for_selector("#password, input[name='password'], input[type='password']", timeout=10000)
        except PlaywrightTimeout:
            raise LoginFailedError("Could not find Marriott password field")

        await self._human_type(
            "#password, input[name='password'], input[type='password']",
            self._config.marriott_password,
        )
        await self._random_delay(400, 900)

        # Submit
        submit = self.page.locator(
            "button[type='submit']:has-text('Sign In'), button:has-text('Sign In'), input[type='submit']"
        ).first
        await submit.click()
        await self._random_delay(2000, 3500)

        # Handle MFA
        mfa_selectors = [
            "input[name='passcode']",
            "input[name='otpCode']",
            "input[placeholder*='code']",
            "input[aria-label*='verification']",
        ]
        for sel in mfa_selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=5000)
                code = await self._prompt_mfa("Enter Marriott MFA/verification code: ")
                await self._human_type(sel, code.strip())
                verify_btn = self.page.locator("button:has-text('Verify'), button:has-text('Submit'), button[type='submit']").first
                await verify_btn.click()
                await self._random_delay(2000, 3500)
                break
            except PlaywrightTimeout:
                continue

        # Confirm login
        try:
            await self.page.wait_for_url(
                re.compile(r"(myAccount|loyalty|dashboard)", re.I), timeout=15000
            )
            logger.info("Marriott login successful")
            return True
        except PlaywrightTimeout:
            err = await self.page.locator(".error-message, [role='alert'], .alert").text_content()
            raise LoginFailedError(f"Marriott login failed: {err[:200] if err else 'unknown error'}")

    async def scrape(self) -> list[HotelStay]:
        if not await self.is_logged_in():
            logger.info("Marriott session expired, re-logging in")
            if not await self.login():
                raise SessionExpiredError("Marriott re-login failed")

        logger.info("Scraping Marriott My Trips...")
        await self.page.goto(self.MY_TRIPS_URL, wait_until="networkidle", timeout=30000)

        await self._check_captcha()

        # Click "Upcoming" tab if present
        try:
            upcoming_tab = self.page.locator("text=Upcoming, [data-tab='upcoming'], [aria-label*='Upcoming']").first
            await upcoming_tab.click(timeout=5000)
            await self._random_delay(800, 1500)
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            pass  # May not have a tab

        # Wait for stay cards
        try:
            await self.page.wait_for_selector(
                "[data-component='trip-summary'], .reservation-card, .stay-card, .trip-item",
                timeout=20000,
            )
        except PlaywrightTimeout:
            logger.info("Marriott My Trips: no upcoming stays found")
            return []

        stays: list[HotelStay] = []
        cards = await self.page.locator(
            "[data-component='trip-summary'], .reservation-card, .stay-card, .trip-item"
        ).all()

        logger.info(f"Found {len(cards)} Marriott stay card(s)")

        today = date.today()
        for card in cards:
            try:
                stay = await self._parse_stay_card(card)
                if stay and stay.check_out_date >= today:
                    stays.append(stay)
            except Exception as e:
                logger.warning(f"Failed to parse Marriott stay card: {e}")

        logger.info(f"Marriott scrape complete: {len(stays)} upcoming stay(s)")
        return stays

    async def _parse_stay_card(self, card) -> HotelStay | None:
        now = datetime.now()
        raw = await card.text_content() or ""

        if not raw.strip():
            return None

        # Hotel name: look for heading elements first
        hotel_name = "Unknown Hotel"
        for sel in [".hotel-name", "h2", "h3", "[data-test='hotel-name']", ".property-name"]:
            try:
                el = card.locator(sel).first
                name = await el.text_content(timeout=2000)
                if name and name.strip():
                    hotel_name = name.strip()
                    break
            except Exception:
                continue

        if hotel_name == "Unknown Hotel":
            # Last resort: first line of raw text
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            if lines:
                hotel_name = lines[0][:80]

        # Confirmation number
        conf_match = re.search(r"(?:Confirmation|Conf\.?|#)\s*:?\s*([A-Z0-9]{6,12})", raw, re.I)
        confirmation = conf_match.group(1) if conf_match else f"UNKNOWN_{abs(hash(hotel_name)) % 100000}"

        # Dates — prefer <time> elements with datetime attribute
        dates: list[date] = []
        time_els = await card.locator("time[datetime]").all()
        for el in time_els:
            dt_attr = await el.get_attribute("datetime")
            if dt_attr:
                try:
                    dates.append(datetime.fromisoformat(dt_attr.split("T")[0]).date())
                except ValueError:
                    pass

        if len(dates) < 2:
            # Parse from raw text
            date_patterns = [
                r"(\w+ \d{1,2},?\s*\d{4})",
                r"(\d{1,2}/\d{1,2}/\d{4})",
                r"(\d{4}-\d{2}-\d{2})",
            ]
            for pattern in date_patterns:
                matches = re.findall(pattern, raw)
                for m in matches:
                    for fmt in ("%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%Y-%m-%d"):
                        try:
                            dates.append(datetime.strptime(m.replace(",", ""), fmt.replace(",", "")).date())
                            break
                        except ValueError:
                            continue
                if len(dates) >= 2:
                    break

        dates = sorted(set(dates))
        check_in = dates[0] if dates else now.date()
        check_out = dates[1] if len(dates) >= 2 else check_in

        return HotelStay(
            confirmation_number=confirmation,
            hotel_name=hotel_name,
            check_in_date=check_in,
            check_out_date=check_out,
            scraped_at=now,
        )

    async def _check_captcha(self) -> None:
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            ".g-recaptcha",
        ]
        for sel in captcha_selectors:
            try:
                if await self.page.locator(sel).count() > 0:
                    logger.warning("CAPTCHA detected on Marriott.")
                    print("\n⚠️  CAPTCHA detected. Please solve it in the browser window, then press Enter.")
                    loop = __import__("asyncio").get_event_loop()
                    await loop.run_in_executor(None, input, "Press Enter after solving CAPTCHA...")
                    return
            except Exception:
                continue
