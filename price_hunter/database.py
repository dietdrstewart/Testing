from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Generator

_default_db = Path.home() / ".price_hunter.db"
DB_PATH = Path(os.environ.get("DB_PATH", str(_default_db)))


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            -- Legacy component-level prices (kept for backward compat)
            CREATE TABLE IF NOT EXISTS prices (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source       TEXT    NOT NULL,
                product_name TEXT    NOT NULL,
                category     TEXT    NOT NULL,
                travel_date  TEXT    NOT NULL,
                price        REAL    NOT NULL,
                url          TEXT,
                scraped_at   TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_prices_lookup
                ON prices (source, product_name, category, travel_date);

            -- New: total package prices per vacation per week
            CREATE TABLE IF NOT EXISTS package_prices (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                vacation_id          TEXT    NOT NULL,
                week_start           TEXT    NOT NULL,   -- Sunday ISO date
                week_end             TEXT    NOT NULL,   -- Saturday ISO date
                flight_price         REAL,               -- Round-trip total, all travelers
                accommodation_price  REAL,               -- Hotel/cruise total
                tickets_price        REAL,               -- Park tickets total (0 if N/A)
                total_price          REAL    NOT NULL,
                url                  TEXT,
                scraped_at           TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pkg_lookup
                ON package_prices (vacation_id, week_start);

            CREATE TABLE IF NOT EXISTS scans (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at   TEXT    NOT NULL,
                completed_at TEXT,
                status       TEXT    NOT NULL DEFAULT 'running',
                deals_found  INTEGER DEFAULT 0,
                notes        TEXT
            );
        """)


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL mode allows concurrent reads during writes — essential for parallel scrapers
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Package prices ─────────────────────────────────────────────────────────

def insert_package_prices(rows: list[dict]) -> None:
    if not rows:
        return
    now = datetime.now().isoformat()
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO package_prices
               (vacation_id, week_start, week_end,
                flight_price, accommodation_price, tickets_price,
                total_price, url, scraped_at)
               VALUES (:vacation_id, :week_start, :week_end,
                       :flight_price, :accommodation_price, :tickets_price,
                       :total_price, :url, :scraped_at)""",
            [{**r, "scraped_at": now} for r in rows],
        )


def get_package_history(days_back: int = 180) -> list[dict]:
    """All package price records for anomaly analysis and charting."""
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT vacation_id, week_start, week_end,
                      flight_price, accommodation_price, tickets_price,
                      total_price, url, scraped_at
               FROM package_prices
               WHERE scraped_at >= ?
               ORDER BY vacation_id, week_start, scraped_at""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_prices_per_week() -> list[dict]:
    """Most recent total_price per (vacation_id, week_start) — used for the chart."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT vacation_id, week_start, week_end,
                      flight_price, accommodation_price, tickets_price,
                      total_price, url, MAX(scraped_at) as scraped_at
               FROM package_prices
               WHERE week_start >= date('now')
               GROUP BY vacation_id, week_start
               ORDER BY vacation_id, week_start"""
        ).fetchall()
    return [dict(r) for r in rows]


# ── Scan tracking ──────────────────────────────────────────────────────────

def start_scan() -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO scans (started_at, status) VALUES (?, 'running')",
            (datetime.now().isoformat(),),
        )
        return cur.lastrowid


def finish_scan(scan_id: int, deals_found: int, status: str = "done", notes: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE scans SET completed_at=?, status=?, deals_found=?, notes=? WHERE id=?",
            (datetime.now().isoformat(), status, deals_found, notes, scan_id),
        )


def get_last_scan() -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def get_scan_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM scans WHERE status='done'").fetchone()[0]


# ── Legacy (component prices) ──────────────────────────────────────────────

def insert_prices(rows: list[dict]) -> None:
    if not rows:
        return
    now = datetime.now().isoformat()
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO prices (source, product_name, category, travel_date, price, url, scraped_at)
               VALUES (:source, :product_name, :category, :travel_date, :price, :url, :scraped_at)""",
            [{**r, "scraped_at": now} for r in rows],
        )


def get_all_recent_prices(days_back: int = 90) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT source, product_name, category, travel_date, price, url, scraped_at
               FROM prices WHERE scraped_at >= ?
               ORDER BY source, product_name, category, travel_date, scraped_at""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def prune_old_prices(days_keep: int = 180) -> None:
    cutoff = (datetime.now() - timedelta(days=days_keep)).isoformat()
    with _conn() as conn:
        conn.execute("DELETE FROM prices WHERE scraped_at < ?", (cutoff,))
        conn.execute("DELETE FROM package_prices WHERE scraped_at < ?", (cutoff,))
