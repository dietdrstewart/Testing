from __future__ import annotations

"""
Parallel package scanner — all 5 vacation scrapers + 4 flight routes run
concurrently under a single shared Playwright browser process.

Speed improvements vs. sequential v1:
  - 1 browser cold-start instead of 6
  - All scrapers run simultaneously via asyncio.gather
  - Flight routes run in parallel (4 concurrent contexts, staggered starts)
  - 17 sampled date points instead of 26 for flights
  - Estimated scan time: ~3-5 min vs ~15+ min previously
"""

import asyncio
import logging
import threading
from collections.abc import Generator
from datetime import date, timedelta
from typing import Any

from playwright.async_api import async_playwright

from . import database as db
from .scrapers.base import _USER_AGENT, _STEALTH_SCRIPT, _make_context
from .scrapers.flights import FlightScraper
from .scrapers.disney_package import DisneyPackageScraper
from .scrapers.universal_package import UniversalPackageScraper
from .scrapers.royal_caribbean_icon import RoyalCaribbeanIconScraper
from .scrapers.xcaret_package import XcaretPackageScraper
from .scrapers.nice_marriott import NiceMarriottScraper
from .vacations import VACATIONS, get_sunday_weeks, get_sampled_weeks

logger = logging.getLogger(__name__)

N_WEEKS = 26

# (step, vac_id, label, ScraperClass, flight_dest_code)
_PACKAGE_STEPS = [
    (2, "disney_week",       "🏰 Disney World",         DisneyPackageScraper,       "MCO"),
    (3, "universal_week",    "🎬 Universal Studios",     UniversalPackageScraper,    "MCO"),
    (4, "royal_icon_cruise", "🚢 Royal Caribbean Icon",  RoyalCaribbeanIconScraper,  "MIA"),
    (5, "xcaret_cancun",     "🌴 Xcaret Cancún",         XcaretPackageScraper,       "CUN"),
    (6, "nice_france",       "🇫🇷 Nice, France",         NiceMarriottScraper,        "NCE"),
]


# ── Public entry point (sync generator, backward-compatible with app.py) ───

def run_package_scan(headed: bool = False) -> Generator[dict[str, Any], None, None]:
    """
    Sync generator that runs the full async scan internally.
    Yields SSE-style progress dicts as they arrive from concurrent scrapers.
    """
    from queue import Queue as TQueue

    tq: TQueue[dict | None] = TQueue()

    def _thread():
        async def _bridge():
            aq: asyncio.Queue = asyncio.Queue()

            async def _collect():
                while True:
                    item = await aq.get()
                    tq.put(item)
                    if item.get("type") in ("done", "error"):
                        break

            await asyncio.gather(_run_scan_async(headed, aq), _collect())
            tq.put(None)  # sentinel — scan fully complete

        asyncio.run(_bridge())

    threading.Thread(target=_thread, daemon=True).start()

    while True:
        item = tq.get()
        if item is None:
            break
        yield item


# ── Core async orchestrator ────────────────────────────────────────────────

async def _run_scan_async(headed: bool, progress_q: asyncio.Queue) -> None:
    scan_id = db.start_scan()
    weeks = get_sunday_weeks(N_WEEKS)
    sampled_weeks = get_sampled_weeks(weeks)
    week_starts = [ws for ws, _ in weeks]

    await progress_q.put({"type": "start", "total": 6, "scan_id": scan_id, "weeks": len(weeks)})

    # Announce all scrapers as running upfront (they truly run concurrently)
    await progress_q.put({"type": "progress", "source": "✈ Flights (all routes)", "step": 1, "total": 6, "status": "running"})
    for step, _, label, _, _ in _PACKAGE_STEPS:
        await progress_q.put({"type": "progress", "source": label, "step": step, "total": 6, "status": "running"})

    # Shared flight results: package scrapers wait on this event
    flight_done = asyncio.Event()
    flight_prices: dict[str, dict[str, float]] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not headed,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            tasks = [
                asyncio.create_task(
                    _task_flights(browser, sampled_weeks, progress_q, flight_done, flight_prices)
                ),
                *[
                    asyncio.create_task(
                        _task_package(
                            vac_id, ScraperClass, flight_dest, browser,
                            week_starts, weeks, progress_q, step, label,
                            flight_done, flight_prices,
                        )
                    )
                    for step, vac_id, label, ScraperClass, flight_dest in _PACKAGE_STEPS
                ],
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await browser.close()

    total_rows = sum(r for r in results[1:] if isinstance(r, int))
    db.finish_scan(scan_id, deals_found=0)
    db.prune_old_prices()
    await progress_q.put({"type": "done", "total_rows": total_rows, "scan_id": scan_id})


# ── Individual task coroutines ─────────────────────────────────────────────

async def _task_flights(
    browser,
    sampled_weeks: list[tuple[date, date]],
    progress_q: asyncio.Queue,
    flight_done: asyncio.Event,
    flight_prices_out: dict,
) -> None:
    try:
        scraper = FlightScraper()
        prices = await scraper.scrape_all_routes_parallel(sampled_weeks, browser)
        flight_prices_out.update(prices)
        count = sum(len(v) for v in prices.values())
        await progress_q.put({
            "type": "progress", "source": "✈ Flights (all routes)",
            "step": 1, "total": 6, "status": "done", "count": count,
        })
    except Exception as e:
        logger.exception(f"Flight task failed: {e}")
        await progress_q.put({
            "type": "progress", "source": "✈ Flights (all routes)",
            "step": 1, "total": 6, "status": "error", "error": str(e)[:200],
        })
    finally:
        flight_done.set()   # always unblock package scrapers, even on error


async def _task_package(
    vac_id: str,
    ScraperClass,
    flight_dest: str,
    browser,
    week_starts: list[date],
    weeks: list[tuple[date, date]],
    progress_q: asyncio.Queue,
    step: int,
    label: str,
    flight_done: asyncio.Event,
    flight_prices_out: dict,
) -> int:
    try:
        # Create an isolated browser context for this scraper
        ctx = await _make_context(browser)
        try:
            # Do hotel/ticket scraping concurrently while flights are still running
            async with ScraperClass(context=ctx) as scraper:
                pkg_costs = await scraper.get_weekly_costs(week_starts)
        finally:
            await ctx.close()

        # Now wait for flights — usually already done, but ensure correctness
        await flight_done.wait()

        rows = _assemble_rows(vac_id, pkg_costs, weeks, flight_prices_out, flight_dest)
        if rows:
            db.insert_package_prices(rows)

        await progress_q.put({
            "type": "progress", "source": label, "step": step, "total": 6,
            "status": "done", "count": len(rows),
        })
        return len(rows)

    except Exception as e:
        logger.exception(f"Package task {vac_id} failed: {e}")
        await progress_q.put({
            "type": "progress", "source": label, "step": step, "total": 6,
            "status": "error", "error": str(e)[:200],
        })
        return 0


def _assemble_rows(
    vac_id: str,
    pkg_costs: dict[str, dict],
    weeks: list[tuple[date, date]],
    flight_prices: dict[str, dict[str, float]],
    flight_dest: str,
) -> list[dict]:
    rows = []
    route_prices = flight_prices.get(flight_dest, {})

    for ws, we in weeks:
        ws_iso = ws.isoformat()
        we_iso = we.isoformat()
        pkg = pkg_costs.get(ws_iso)
        if not pkg:
            continue

        flight_price = route_prices.get(ws_iso)
        if flight_price is None:
            continue   # skip weeks without flight data rather than guess

        accommodation = pkg.get("accommodation_price") or 0.0
        tickets = pkg.get("tickets_price") or 0.0
        total = flight_price + accommodation + tickets

        rows.append({
            "vacation_id": vac_id,
            "week_start": ws_iso,
            "week_end": we_iso,
            "flight_price": round(flight_price, 2),
            "accommodation_price": round(accommodation, 2),
            "tickets_price": round(tickets, 2),
            "total_price": round(total, 2),
            "url": pkg.get("url", ""),
        })

    return rows
