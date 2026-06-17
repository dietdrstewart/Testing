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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


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


def get_price_history(
    source: str,
    product_name: str,
    category: str,
    travel_date: str,
    days_back: int = 90,
) -> list[float]:
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT price FROM prices
               WHERE source=? AND product_name=? AND category=? AND travel_date=?
                 AND scraped_at >= ?
               ORDER BY scraped_at""",
            (source, product_name, category, travel_date, cutoff),
        ).fetchall()
    return [r["price"] for r in rows]


def get_all_recent_prices(days_back: int = 90) -> list[dict]:
    """Return every price record grouped for anomaly analysis."""
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT source, product_name, category, travel_date,
                      price, url, scraped_at
               FROM prices
               WHERE scraped_at >= ?
               ORDER BY source, product_name, category, travel_date, scraped_at""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_last_scan() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_scan_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM scans WHERE status='done'").fetchone()[0]


def prune_old_prices(days_keep: int = 180) -> None:
    cutoff = (datetime.now() - timedelta(days=days_keep)).isoformat()
    with _conn() as conn:
        conn.execute("DELETE FROM prices WHERE scraped_at < ?", (cutoff,))
