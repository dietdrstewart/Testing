from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Any

MIN_OBSERVATIONS = 3  # Need at least this many data points to flag a deal


def find_deals(all_prices: list[dict], std_dev_threshold: float = 1.0) -> list[dict]:
    """
    Groups price records by (source, product_name, category, travel_date),
    computes mean/stdev, and returns records where the latest price is
    std_dev_threshold or more standard deviations below the mean.
    """
    # Group all historical prices by product key
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in all_prices:
        key = (row["source"], row["product_name"], row["category"], row["travel_date"])
        groups[key].append(row)

    deals: list[dict] = []

    for key, records in groups.items():
        source, product_name, category, travel_date = key

        # Skip past travel dates
        try:
            td = date.fromisoformat(travel_date)
            if td < date.today():
                continue
        except ValueError:
            continue

        prices = [r["price"] for r in records]

        if len(prices) < MIN_OBSERVATIONS:
            continue

        mean = statistics.mean(prices)
        try:
            stdev = statistics.stdev(prices)
        except statistics.StatisticsError:
            continue

        if stdev == 0:
            continue

        # Use the most recently scraped price as "current"
        latest = max(records, key=lambda r: r["scraped_at"])
        current_price = latest["price"]

        z_score = (mean - current_price) / stdev  # positive = below average = deal

        if z_score >= std_dev_threshold:
            savings_pct = round((mean - current_price) / mean * 100, 1)
            deals.append({
                "source": source,
                "product_name": product_name,
                "category": category,
                "travel_date": travel_date,
                "current_price": round(current_price, 2),
                "mean_price": round(mean, 2),
                "std_dev": round(stdev, 2),
                "z_score": round(z_score, 2),
                "savings_pct": savings_pct,
                "savings_dollars": round(mean - current_price, 2),
                "url": latest.get("url", ""),
                "observations": len(prices),
                "scraped_at": latest["scraped_at"],
            })

    # Sort by z_score descending (biggest deals first)
    deals.sort(key=lambda d: d["z_score"], reverse=True)
    return deals


def get_baseline_summary(all_prices: list[dict]) -> dict[str, Any]:
    """Returns summary stats for the dashboard status bar."""
    sources: set[str] = set()
    total_records = len(all_prices)
    for r in all_prices:
        sources.add(r["source"])

    return {
        "total_records": total_records,
        "sources_tracked": len(sources),
        "ready_for_anomalies": total_records >= MIN_OBSERVATIONS * 3,
    }
