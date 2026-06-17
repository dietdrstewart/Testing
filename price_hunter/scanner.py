from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator
from typing import Any

from . import database as db
from .scrapers.disney_cruise import DisneyCruiseScraper
from .scrapers.disney_world import DisneyWorldScraper
from .scrapers.great_wolf import GreatWolfScraper
from .scrapers.hersheypark import HersheyparkScraper
from .scrapers.royal_caribbean import RoyalCaribbeanScraper
from .scrapers.universal import UniversalScraper

logger = logging.getLogger(__name__)

SCRAPERS = [
    ("Disney Cruise Line", DisneyCruiseScraper),
    ("Royal Caribbean", RoyalCaribbeanScraper),
    ("Disney World", DisneyWorldScraper),
    ("Universal Studios", UniversalScraper),
    ("Hersheypark", HersheyparkScraper),
    ("Great Wolf Lodge", GreatWolfScraper),
]


def run_full_scan(headed: bool = False) -> Generator[dict[str, Any], None, None]:
    """
    Generator that runs all scrapers sequentially and yields progress events.
    Each event is a dict suitable for SSE JSON.
    """
    scan_id = db.start_scan()
    total = len(SCRAPERS)
    all_records: list = []

    yield {"type": "start", "total": total, "scan_id": scan_id}

    for idx, (label, ScraperClass) in enumerate(SCRAPERS, 1):
        yield {"type": "progress", "source": label, "step": idx, "total": total, "status": "running"}

        try:
            records = asyncio.run(_run_one(ScraperClass, headed))
            all_records.extend(records)

            rows = [r.to_dict() for r in records]
            if rows:
                db.insert_prices(rows)

            yield {
                "type": "progress",
                "source": label,
                "step": idx,
                "total": total,
                "status": "done",
                "count": len(records),
            }
        except Exception as e:
            logger.exception(f"Scraper {label} failed: {e}")
            yield {
                "type": "progress",
                "source": label,
                "step": idx,
                "total": total,
                "status": "error",
                "error": str(e)[:200],
            }

    db.finish_scan(scan_id, deals_found=0)  # deals_found updated by caller
    db.prune_old_prices()

    yield {"type": "done", "total_records": len(all_records), "scan_id": scan_id}


async def _run_one(ScraperClass, headed: bool) -> list:
    async with ScraperClass(headed=headed) as scraper:
        return await scraper.scrape()
