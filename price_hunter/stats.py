from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Any

MIN_OBSERVATIONS = 3


# ── Package-level anomaly detection ────────────────────────────────────────

def analyze_packages(all_rows: list[dict], std_dev_threshold: float = 1.0) -> dict[str, Any]:
    """
    Groups package_prices records by (vacation_id, week_start).
    For each vacation, computes per-week stats using ALL historical prices
    scraped for that week, then returns:
      - chart_data: per-vacation list of {week_start, price, deviation_pct, is_deal, mean, std_dev}
      - deals: rows flagged as 1+ std_dev below mean
      - vacation_stats: {vacation_id: {mean, std_dev, min, max, observations}}
    """
    # Group by vacation → week → list of prices observed over time
    by_vac_week: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    latest_row: dict[str, dict[str, dict]] = defaultdict(dict)

    for row in all_rows:
        vid = row["vacation_id"]
        ws = row["week_start"]
        by_vac_week[vid][ws].append(row["total_price"])
        # Keep the most recently scraped row per (vacation, week)
        if ws not in latest_row[vid] or row["scraped_at"] > latest_row[vid][ws]["scraped_at"]:
            latest_row[vid][ws] = row

    today = date.today().isoformat()

    chart_data: dict[str, list[dict]] = {}
    deals: list[dict] = []
    vacation_stats: dict[str, dict] = {}

    for vid, weeks in by_vac_week.items():
        # Compute the vacation-level mean from ALL (week, scan) price points
        all_prices_for_vac = [p for prices in weeks.values() for p in prices]
        if len(all_prices_for_vac) < MIN_OBSERVATIONS:
            # Not enough data — include raw prices, no anomaly flagging
            chart_data[vid] = [
                {
                    "week_start": ws,
                    "price": latest_row[vid][ws]["total_price"],
                    "deviation_pct": None,
                    "is_deal": False,
                    "mean": None,
                    "std_dev": None,
                    "flight_price": latest_row[vid][ws].get("flight_price"),
                    "accommodation_price": latest_row[vid][ws].get("accommodation_price"),
                    "tickets_price": latest_row[vid][ws].get("tickets_price"),
                    "url": latest_row[vid][ws].get("url", ""),
                }
                for ws in sorted(weeks) if ws >= today
            ]
            vacation_stats[vid] = {"ready": False, "observations": len(all_prices_for_vac)}
            continue

        vac_mean = statistics.mean(all_prices_for_vac)
        try:
            vac_stdev = statistics.stdev(all_prices_for_vac)
        except statistics.StatisticsError:
            vac_stdev = 0.0

        vacation_stats[vid] = {
            "ready": True,
            "mean": round(vac_mean, 2),
            "std_dev": round(vac_stdev, 2),
            "min": round(min(all_prices_for_vac), 2),
            "max": round(max(all_prices_for_vac), 2),
            "observations": len(all_prices_for_vac),
        }

        points = []
        for ws in sorted(weeks):
            if ws < today:
                continue
            row = latest_row[vid][ws]
            current_price = row["total_price"]
            deviation_pct = ((current_price - vac_mean) / vac_mean * 100) if vac_mean else None
            z_score = ((vac_mean - current_price) / vac_stdev) if vac_stdev > 0 else 0
            is_deal = z_score >= std_dev_threshold

            point = {
                "week_start": ws,
                "price": round(current_price, 2),
                "deviation_pct": round(deviation_pct, 1) if deviation_pct is not None else None,
                "is_deal": is_deal,
                "z_score": round(z_score, 2),
                "mean": round(vac_mean, 2),
                "std_dev": round(vac_stdev, 2),
                "savings_dollars": round(vac_mean - current_price, 2) if is_deal else 0,
                "flight_price": row.get("flight_price"),
                "accommodation_price": row.get("accommodation_price"),
                "tickets_price": row.get("tickets_price"),
                "url": row.get("url", ""),
            }
            points.append(point)

            if is_deal:
                deals.append({"vacation_id": vid, **point})

        chart_data[vid] = points

    deals.sort(key=lambda d: d.get("z_score", 0), reverse=True)
    return {"chart_data": chart_data, "deals": deals, "vacation_stats": vacation_stats}


# ── Legacy component-level deals (kept for backward compat) ────────────────

def find_deals(all_prices: list[dict], std_dev_threshold: float = 1.0) -> list[dict]:
    from collections import defaultdict
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in all_prices:
        key = (row["source"], row["product_name"], row["category"], row["travel_date"])
        groups[key].append(row)

    deals: list[dict] = []
    for key, records in groups.items():
        source, product_name, category, travel_date = key
        try:
            if date.fromisoformat(travel_date) < date.today():
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
        latest = max(records, key=lambda r: r["scraped_at"])
        current_price = latest["price"]
        z_score = (mean - current_price) / stdev
        if z_score >= std_dev_threshold:
            deals.append({
                "source": source, "product_name": product_name, "category": category,
                "travel_date": travel_date, "current_price": round(current_price, 2),
                "mean_price": round(mean, 2), "std_dev": round(stdev, 2),
                "z_score": round(z_score, 2),
                "savings_pct": round((mean - current_price) / mean * 100, 1),
                "savings_dollars": round(mean - current_price, 2),
                "url": latest.get("url", ""), "observations": len(prices),
                "scraped_at": latest["scraped_at"],
            })
    deals.sort(key=lambda d: d["z_score"], reverse=True)
    return deals


def get_baseline_summary(all_prices: list[dict]) -> dict[str, Any]:
    sources: set[str] = {r["source"] for r in all_prices}
    return {
        "total_records": len(all_prices),
        "sources_tracked": len(sources),
        "ready_for_anomalies": len(all_prices) >= MIN_OBSERVATIONS * 3,
    }
