import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_cache: dict = {}
_CACHE_TTL_SECONDS = 1800  # 30 minutes


def get_current_location() -> dict:
    now = time.time()
    if _cache.get("ts", 0) + _CACHE_TTL_SECONDS > now:
        return _cache["data"]

    try:
        resp = requests.get("https://ipinfo.io/json", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        result = {
            "city": data.get("city", "Unknown"),
            "region": data.get("region", ""),
            "country": data.get("country", ""),
        }
    except Exception as e:
        logger.warning(f"Location lookup failed: {e}")
        result = {"city": "Unknown", "region": "", "country": ""}

    _cache["ts"] = now
    _cache["data"] = result
    return result


def format_location(loc: Optional[dict] = None) -> str:
    if loc is None:
        loc = get_current_location()
    parts = [p for p in (loc.get("city"), loc.get("region")) if p and p != "Unknown"]
    return ", ".join(parts) if parts else "Unknown location"
