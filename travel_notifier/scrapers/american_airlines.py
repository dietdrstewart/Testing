from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..config import Config
from ..models.flight import FlightData
from .base import (
    BaseScraper,
    CaptchaError,
    LoginFailedError,
    ParseError,
    SessionExpiredError,
)

logger = logging.getLogger(__name__)


class AAScraper(BaseScraper):
    COOKIE_FILE = Path("aa.json")

    BASE_URL = "https://www.aa.com"
    LOGIN_URL = "https://www.aa.com/homePage.do"
    MY_TRIPS_URL = "https://www.aa.com/reservation/myTripsPage.do"
    FLIGHT_STATUS_URL = "https://www.aa.com/flightStatus/retrieve.do"

    async def is_logged_in(self) -> bool:
        try:
            await self.page.goto(self.MY_TRIPS_URL, wait_until="domcontentloaded", timeout=30000)
            await self.page.wait_for_load_state("networkidle", timeout=15000)
            url = self.page.url
            # Redirected to login page = not logged in
            if "sign_in" in url.lower() or "login" in url.lower():
                return False
            # Check for a logged-in indicator
            try:
                await self.page.wait_for_selector(
                    "[data-test='my-trips'], .trips-container, #myTrips, .mytrips-container",
                    timeout=8000,
                )
                return True
            except PlaywrightTimeout:
                return False
        except Exception as e:
            logger.debug(f"is_logged_in check failed: {e}")
            return False

    async def login(self) -> bool:
        logger.info("Logging in to American Airlines...")
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await self._random_delay(1000, 2000)

        # Click the Log in link/button
        try:
            login_btn = self.page.locator("text=Log in, [aria-label*='Log in'], #aa-header-login-btn").first
            await login_btn.click(timeout=8000)
            await self._random_delay(800, 1500)
        except PlaywrightTimeout:
            # Some AA layouts go directly to a login form
            pass

        # Check for CAPTCHA
        await self._check_captcha()

        # Fill username
        try:
            await self.page.wait_for_selector(
                "#signin_username, input[name='username'], input[type='email']",
                timeout=10000,
            )
        except PlaywrightTimeout:
            raise LoginFailedError("Could not find AA login form")

        await self._human_type(
            "#signin_username, input[name='username'], input[type='email']",
            self._config.aa_username,
        )
        await self._random_delay(600, 1200)

        # Fill password
        await self._human_type(
            "#signin_password, input[name='password'], input[type='password']",
            self._config.aa_password,
        )
        await self._random_delay(400, 900)

        # Submit
        submit = self.page.locator(
            "button[type='submit'], input[type='submit'], [data-test='login-submit'], text=Log in"
        ).first
        await submit.click()
        await self._random_delay(2000, 3500)

        # Handle MFA
        mfa_selectors = [
            "input[name='passcode']",
            "input[name='otpCode']",
            "input[placeholder*='code']",
            "input[aria-label*='code']",
        ]
        for sel in mfa_selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=5000)
                code = await self._prompt_mfa("Enter American Airlines MFA code: ")
                await self._human_type(sel, code.strip())
                submit = self.page.locator("button[type='submit'], text=Submit, text=Verify").first
                await submit.click()
                await self._random_delay(2000, 3500)
                break
            except PlaywrightTimeout:
                continue

        # Confirm login succeeded
        try:
            await self.page.wait_for_url(
                re.compile(r"(homePage|myAccount|myTrips)", re.I), timeout=15000
            )
            logger.info("AA login successful")
            return True
        except PlaywrightTimeout:
            # Check for error message
            err = await self.page.locator(".error-message, [role='alert'], .alert-danger").text_content()
            raise LoginFailedError(f"AA login failed: {err[:200] if err else 'unknown error'}")

    async def scrape(self) -> list[FlightData]:
        if not await self.is_logged_in():
            logger.info("AA session expired, re-logging in")
            if not await self.login():
                raise SessionExpiredError("AA re-login failed")

        logger.info("Scraping AA My Trips...")
        await self.page.goto(self.MY_TRIPS_URL, wait_until="networkidle", timeout=30000)

        await self._check_captcha()

        try:
            await self.page.wait_for_selector(
                ".trips-container, [data-test='my-trips'], #upcoming-trips, .trip-card",
                timeout=20000,
            )
        except PlaywrightTimeout:
            logger.warning("AA My Trips: no trip container found (may have no upcoming trips)")
            return []

        flights: list[FlightData] = []

        # Collect all trip cards
        cards = await self.page.locator(".trip-card, [data-test='trip-card'], .reservation-card").all()
        if not cards:
            # Try a broader approach: find flight segment rows
            cards = await self.page.locator("[class*='trip'], [class*='reservation']").all()

        logger.info(f"Found {len(cards)} trip card(s) on AA My Trips")

        today = date.today()
        for card in cards:
            try:
                segments = await self._parse_trip_card(card)
                for f in segments:
                    if f.departure_date >= today:
                        flights.append(f)
            except Exception as e:
                logger.warning(f"Failed to parse AA trip card: {e}")

        # For flights departing today or tomorrow, enrich with live status
        from datetime import timedelta
        soon = today + timedelta(days=1)
        enriched: list[FlightData] = []
        for f in flights:
            if f.departure_date <= soon:
                try:
                    f = await self._get_live_status(f)
                except Exception as e:
                    logger.debug(f"Live status fetch failed for {f.flight_number}: {e}")
            enriched.append(f)

        logger.info(f"AA scrape complete: {len(enriched)} upcoming flight(s)")
        return enriched

    async def _parse_trip_card(self, card) -> list[FlightData]:
        """Extract one or more FlightData objects from a trip card element."""
        now = datetime.now()
        flights: list[FlightData] = []

        # Try to find flight number elements within the card
        flight_num_els = await card.locator(
            "[data-test='flight-number'], .flight-number, [aria-label*='Flight'], text=/AA \\d+/i"
        ).all()

        if not flight_num_els:
            # Fallback: look for any text matching "AA NNNN"
            text = await card.text_content() or ""
            matches = re.findall(r"AA\s*(\d{1,4})", text, re.I)
            if not matches:
                return []

        # Collect raw text for parsing when structured selectors fail
        raw = await card.text_content() or ""

        # Extract flight numbers
        flight_numbers = re.findall(r"AA\s*(\d{1,4})", raw, re.I)
        # Extract airports (IATA codes)
        airports = re.findall(r"\b([A-Z]{3})\b", raw)
        # Extract dates (various formats)
        date_matches = re.findall(
            r"(\w+ \d{1,2},?\s*\d{4}|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", raw
        )
        # Extract times
        time_matches = re.findall(r"(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)", raw)
        # Extract status
        status_match = re.search(
            r"\b(On Time|Delayed|Boarding|Departed|Landed|Arrived|Cancelled|Scheduled)\b",
            raw,
            re.I,
        )
        status = status_match.group(1).title() if status_match else "Scheduled"
        # Extract gate
        gate_match = re.search(r"Gate\s*([A-Z]?\d{1,3}[A-Z]?)", raw, re.I)
        gate = gate_match.group(1) if gate_match else None

        # Build a FlightData for each flight number found (handles connections)
        for i, num in enumerate(flight_numbers[:4]):  # cap at 4 segments
            # Pick origin/destination from airport list
            orig = airports[i * 2] if i * 2 < len(airports) else "UNK"
            dest = airports[i * 2 + 1] if i * 2 + 1 < len(airports) else "UNK"

            # Parse departure date
            dep_date = now.date()
            if date_matches:
                for dm in date_matches:
                    for fmt in ("%B %d, %Y", "%B %d %Y", "%Y-%m-%d", "%m/%d/%Y"):
                        try:
                            dep_date = datetime.strptime(dm.replace(",", ""), fmt.replace(",", "")).date()
                            break
                        except ValueError:
                            continue

            # Parse times (first pair = dep/arr for this segment)
            dep_time = now
            arr_time = now
            if len(time_matches) >= 2:
                for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
                    try:
                        dep_time = datetime.combine(
                            dep_date, datetime.strptime(time_matches[0].upper(), fmt).time()
                        )
                        arr_time = datetime.combine(
                            dep_date, datetime.strptime(time_matches[1].upper(), fmt).time()
                        )
                        break
                    except ValueError:
                        continue

            flights.append(
                FlightData(
                    flight_number=f"AA {num}",
                    origin=orig,
                    destination=dest,
                    scheduled_departure=dep_time,
                    scheduled_arrival=arr_time,
                    actual_departure=None,
                    actual_arrival=None,
                    status=status,
                    gate=gate,
                    departure_date=dep_date,
                    scraped_at=now,
                )
            )

        return flights

    async def _get_live_status(self, flight: FlightData) -> FlightData:
        """Navigate to AA flight status page and merge real-time data."""
        num = re.sub(r"\D", "", flight.flight_number)
        url = (
            f"{self.FLIGHT_STATUS_URL}"
            f"?flightNumber={num}"
            f"&flightDate={flight.departure_date.strftime('%Y-%m-%d')}"
            f"&origin={flight.origin}"
        )
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=20000)
            raw = await self.page.text_content("body") or ""

            status_match = re.search(
                r"\b(On Time|Delayed|Boarding|Departed|Landed|Arrived|Cancelled)\b", raw, re.I
            )
            if status_match:
                flight.status = status_match.group(1).title()

            gate_match = re.search(r"Gate\s*([A-Z]?\d{1,3}[A-Z]?)", raw, re.I)
            if gate_match:
                flight.gate = gate_match.group(1)

            # Try to parse actual times
            time_matches = re.findall(r"(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))", raw)
            if len(time_matches) >= 2:
                for fmt in ("%I:%M %p", "%I:%M%p"):
                    try:
                        flight.actual_departure = datetime.combine(
                            flight.departure_date,
                            datetime.strptime(time_matches[0].upper(), fmt).time(),
                        )
                        flight.actual_arrival = datetime.combine(
                            flight.departure_date,
                            datetime.strptime(time_matches[1].upper(), fmt).time(),
                        )
                        break
                    except ValueError:
                        continue

        except Exception as e:
            logger.debug(f"Live status page error for AA{num}: {e}")

        return flight

    async def _check_captcha(self) -> None:
        """Detect common CAPTCHA patterns and pause for manual resolution."""
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            ".g-recaptcha",
            "#captcha",
        ]
        for sel in captcha_selectors:
            try:
                if await self.page.locator(sel).count() > 0:
                    logger.warning("CAPTCHA detected on AA — please solve it in the browser window.")
                    print("\n⚠️  CAPTCHA detected. Please solve it in the browser window, then press Enter.")
                    loop = __import__("asyncio").get_event_loop()
                    await loop.run_in_executor(None, input, "Press Enter after solving CAPTCHA...")
                    return
            except Exception:
                continue
