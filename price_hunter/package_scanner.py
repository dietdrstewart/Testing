from __future__ import annotations

"""
Orchestrates scraping all 5 vacation packages and storing complete
total-cost records (flights + accommodation + tickets) per week.
"""

import asyncio
import logging
from collections.abc import Generator
from typing import Any

from . import database as db
from .vacations import VACATIONS, FAMILY, get_sunday_weeks
from .scrapers.flights import FlightScraper
from .scrapers.disney_package import DisneyPackageScraper
from .scrapers.universal_package import UniversalPackageScraper
from .scrapers.royal_caribbean_icon import RoyalCaribbeanIconScraper
from .scrapers.xcaret_package import XcaretPackageScraper
from .scrapers.nice_marriott import NiceMarriottScraper

logger = logging.getLogger(__name__)

N_WEEKS = 26   # Look 6 months ahead


def run_package_scan(headed: bool = False) -> Generator[dict[str, Any], None, None]:
    """Generator that runs the full scan and yields SSE-style progress events."""
    scan_id = db.start_scan()
    weeks = get_sunday_weeks(N_WEEKS)
    yield {"type": "start", "total": 6, "scan_id": scan_id, "weeks": len(weeks)}

    # ── Step 1: Flight prices (shared across packages) ─────────────────────
    yield {"type": "progress", "source": "✈ Flights (all routes)", "step": 1, "total": 6, "status": "running"}
    try:
        flight_prices = asyncio.run(_scrape_flights(weeks, headed))
        yield {"type": "progress", "source": "✈ Flights (all routes)", "step": 1, "total": 6,
               "status": "done", "count": sum(len(v) for v in flight_prices.values())}
    except Exception as e:
        logger.exception(f"Flight scrape failed: {e}")
        flight_prices = {}
        yield {"type": "progress", "source": "✈ Flights (all routes)", "step": 1, "total": 6,
               "status": "error", "error": str(e)[:200]}

    week_starts = [ws for ws, _ in weeks]

    # ── Steps 2-6: Each vacation package ──────────────────────────────────
    package_steps = [
        (2, "disney_week",       "🏰 Disney World",              DisneyPackageScraper,       "MCO"),
        (3, "universal_week",    "🎬 Universal Studios",          UniversalPackageScraper,    "MCO"),
        (4, "royal_icon_cruise", "🚢 Royal Caribbean Icon",       RoyalCaribbeanIconScraper,  "MIA"),
        (5, "xcaret_cancun",     "🌴 Xcaret Cancún",              XcaretPackageScraper,       "CUN"),
        (6, "nice_france",       "🇫🇷 Nice, France",              NiceMarriottScraper,        "NCE"),
    ]

    total_rows = 0
    for step, vac_id, label, ScraperClass, flight_dest in package_steps:
        yield {"type": "progress", "source": label, "step": step, "total": 6, "status": "running"}
        try:
            rows = asyncio.run(
                _scrape_package(vac_id, ScraperClass, week_starts, weeks, flight_prices, flight_dest, headed)
            )
            if rows:
                db.insert_package_prices(rows)
            total_rows += len(rows)
            yield {"type": "progress", "source": label, "step": step, "total": 6,
                   "status": "done", "count": len(rows)}
        except Exception as e:
            logger.exception(f"Package scrape {vac_id} failed: {e}")
            yield {"type": "progress", "source": label, "step": step, "total": 6,
                   "status": "error", "error": str(e)[:200]}

    db.finish_scan(scan_id, deals_found=0)
    db.prune_old_prices()
    yield {"type": "done", "total_rows": total_rows, "scan_id": scan_id}


async def _scrape_flights(weeks, headed: bool) -> dict[str, dict[str, float]]:
    async with FlightScraper(headed=headed) as scraper:
        return await scraper.scrape_all_routes(weeks)


async def _scrape_package(
    vac_id: str,
    ScraperClass,
    week_starts,
    weeks,
    flight_prices: dict,
    flight_dest: str,
    headed: bool,
) -> list[dict]:
    vacation = VACATIONS[vac_id]

    async with ScraperClass(headed=headed) as scraper:
        pkg_costs = await scraper.get_weekly_costs(week_starts)

    rows = []
    for ws, we in weeks:
        ws_iso = ws.isoformat()
        we_iso = we.isoformat()
        pkg = pkg_costs.get(ws_iso)
        if not pkg:
            continue

        # Flight: round-trip for all paid seats
        flight_price = flight_prices.get(flight_dest, {}).get(ws_iso)
        if flight_price is None:
            # Skip weeks with no flight data rather than guessing
            continue

        accommodation = pkg.get("accommodation_price", 0) or 0
        tickets = pkg.get("tickets_price", 0) or 0
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

    logger.info(f"{vac_id}: stored {len(rows)} week-price records")
    return rows
