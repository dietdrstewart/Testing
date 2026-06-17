from __future__ import annotations

import asyncio
import logging
import logging.handlers
import time
from pathlib import Path

import schedule

from .config import ConfigError, load_config
from .location import format_location, get_current_location
from .models.flight import FlightData
from .models.hotel import HotelStay
from .notifier import EmailNotifier
from .scrapers.american_airlines import AAScraper
from .scrapers.base import ScraperError, SessionExpiredError
from .scrapers.marriott import MarriottScraper
from .state import (
    StateManager,
    detect_flight_changes,
    detect_hotel_events,
)

logger = logging.getLogger(__name__)

_CONSECUTIVE_FAILURE_ALERT = 10


def _setup_logging(level: str, log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    rotating = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    rotating.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.addHandler(console)
    root.addHandler(rotating)


def _dispatch_flight_event(
    notifier: EmailNotifier,
    event: str,
    flight: FlightData,
    old_flight: FlightData | None,
    location: str,
) -> None:
    if event == "STATUS_DELAYED":
        notifier.flight_delayed(flight, location)
    elif event == "STATUS_BOARDING":
        notifier.flight_boarding(flight, location)
    elif event == "STATUS_DEPARTED":
        notifier.flight_departed(flight, location)
    elif event in ("STATUS_LANDED", "STATUS_ARRIVED"):
        notifier.flight_landed(flight, location)
    elif event == "STATUS_CANCELLED":
        notifier.flight_cancelled(flight, location)
    elif event == "GATE_CHANGED":
        old_gate = old_flight.gate if old_flight else "Unknown"
        notifier.gate_changed(flight, old_gate or "Unknown", location)
    else:
        logger.debug(f"Unhandled event type: {event}")


async def _run_aa(config, state_mgr: StateManager, notifier: EmailNotifier, location: str) -> None:
    try:
        async with AAScraper(config) as aa:
            try:
                flights = await aa.scrape()
            except SessionExpiredError:
                await aa.login()
                flights = await aa.scrape()
    except ScraperError as e:
        logger.error(f"AA scrape error: {e}")
        return
    except Exception as e:
        logger.exception(f"AA unexpected error: {e}")
        return

    for flight in flights:
        old = state_mgr.get_flight(flight.key)
        events = detect_flight_changes(old, flight)
        for event in events:
            event_key = f"{flight.key}_{event}"
            if not state_mgr.was_sent(event_key):
                _dispatch_flight_event(notifier, event, flight, old, location)
                state_mgr.mark_sent(event_key)
                logger.info(f"Notification sent: {event_key}")

    state_mgr.update_flights(flights)


async def _run_marriott(config, state_mgr: StateManager, notifier: EmailNotifier, location: str) -> None:
    try:
        async with MarriottScraper(config) as marriott:
            try:
                stays = await marriott.scrape()
            except SessionExpiredError:
                await marriott.login()
                stays = await marriott.scrape()
    except ScraperError as e:
        logger.error(f"Marriott scrape error: {e}")
        return
    except Exception as e:
        logger.exception(f"Marriott unexpected error: {e}")
        return

    sent_keys = state_mgr.get_sent_keys()
    for stay in stays:
        events = detect_hotel_events(stay, sent_keys, config.checkin_notify_hour)
        for event in events:
            event_key = f"{stay.key}_{event}_{stay.check_in_date}"
            if not state_mgr.was_sent(event_key):
                notifier.hotel_checkin_today(stay, location)
                state_mgr.mark_sent(event_key)
                logger.info(f"Hotel notification sent: {event_key}")

    state_mgr.update_hotels(stays)


async def run_one_poll(config, state_mgr: StateManager) -> None:
    location = format_location(get_current_location())
    notifier = EmailNotifier(config)
    logger.info(f"Poll started — current location: {location}")

    await _run_aa(config, state_mgr, notifier, location)
    await _run_marriott(config, state_mgr, notifier, location)

    state_mgr.mark_poll_success()
    state_mgr.save()
    logger.info("Poll complete")


def main() -> None:
    try:
        config = load_config()
    except ConfigError as e:
        print(f"Configuration error: {e}")
        print("Copy .env.example to .env and fill in your credentials.")
        raise SystemExit(1)

    log_file = Path.home() / ".travel_notifier.log"
    _setup_logging(config.log_level, log_file)
    logger.info("Travel Status Notifier starting up")
    logger.info(f"Polling every {config.poll_interval_minutes} minute(s)")
    logger.info(f"Notifications → {config.notify_email}")

    config.cookie_dir.mkdir(parents=True, exist_ok=True)

    state_mgr = StateManager(config.state_file_path)
    consecutive_failures = 0

    def poll_job() -> None:
        nonlocal consecutive_failures
        try:
            asyncio.run(run_one_poll(config, state_mgr))
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            logger.exception(f"Poll cycle failed (#{consecutive_failures}): {e}")
            if consecutive_failures >= _CONSECUTIVE_FAILURE_ALERT:
                try:
                    notifier = EmailNotifier(config)
                    notifier.send_self(
                        "App health alert",
                        f"Travel Notifier has failed {consecutive_failures} consecutive polls.\n"
                        f"Last error: {e}\nCheck ~/.travel_notifier.log for details.",
                    )
                    consecutive_failures = 0  # Reset after alert so we don't spam
                except Exception:
                    pass

    # Run immediately on startup
    poll_job()

    # Schedule recurring polls
    schedule.every(config.poll_interval_minutes).minutes.do(poll_job)

    logger.info("Scheduler running. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
