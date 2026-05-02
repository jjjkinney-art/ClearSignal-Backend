"""
Simple storage layer for historical data.

This module provides a minimal SQLite‑based storage backend to
persist price, financial, event and signal records.  It is the
foundation of the data infrastructure layer in Phase 1.  The
interface is intentionally low‑level: callers must construct
record models and pass them to the insert functions.  The storage
layer handles table creation on demand and ensures that basic
indexes exist for common queries.

The design aims to be modular so that the underlying implementation
can be swapped out for a more scalable database (e.g. Postgres or
data warehouse) in future phases without changing the ingestion
interfaces.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Any

from .schemas import PriceRecord, FinancialRecord, EventRecord, SignalRecord

DB_FILENAME = "data.db"


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a SQLite connection.  Creates the database file if needed."""
    path = Path(db_path or DB_FILENAME)
    conn = sqlite3.connect(path)
    # Enable foreign keys and row factory for dict-like access
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _init_tables(conn: sqlite3.Connection) -> None:
    """Create tables if they do not already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            price REAL NOT NULL,
            volume INTEGER
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            value REAL NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            source TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            signal TEXT NOT NULL,
            importance_score REAL NOT NULL,
            impact_type TEXT NOT NULL,
            time_horizon TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            weighted_score REAL NOT NULL
        );
        """
    )
    conn.commit()


def init_db(db_path: Optional[str] = None) -> None:
    """Create the database and tables.  Safe to call multiple times."""
    conn = _get_connection(db_path)
    try:
        _init_tables(conn)
    finally:
        conn.close()


def insert_price_records(records: Iterable[PriceRecord], db_path: Optional[str] = None) -> None:
    """Insert one or more price records into the database."""
    conn = _get_connection(db_path)
    try:
        _init_tables(conn)
        conn.executemany(
            "INSERT INTO price_history (ticker, timestamp, price, volume) VALUES (?, ?, ?, ?)",
            [(r.ticker, r.timestamp.isoformat(), r.price, r.volume) for r in records],
        )
        conn.commit()
    finally:
        conn.close()


def insert_financial_records(records: Iterable[FinancialRecord], db_path: Optional[str] = None) -> None:
    """Insert one or more financial records."""
    conn = _get_connection(db_path)
    try:
        _init_tables(conn)
        conn.executemany(
            "INSERT INTO financial_history (ticker, timestamp, metric_name, value) VALUES (?, ?, ?, ?)",
            [
                (r.ticker, r.timestamp.isoformat(), r.metric_name, r.value)
                for r in records
            ],
        )
        conn.commit()
    finally:
        conn.close()


def insert_event_records(records: Iterable[EventRecord], db_path: Optional[str] = None) -> None:
    """Insert one or more event records."""
    conn = _get_connection(db_path)
    try:
        _init_tables(conn)
        conn.executemany(
            "INSERT INTO event_history (ticker, timestamp, event_type, description, source) VALUES (?, ?, ?, ?, ?)",
            [
                (r.ticker, r.timestamp.isoformat(), r.event_type, r.description, r.source)
                for r in records
            ],
        )
        conn.commit()
    finally:
        conn.close()


def insert_signal_records(records: Iterable[SignalRecord], db_path: Optional[str] = None) -> None:
    """Insert one or more signal records."""
    conn = _get_connection(db_path)
    try:
        _init_tables(conn)
        conn.executemany(
            "INSERT INTO signal_history (timestamp, signal, importance_score, impact_type, time_horizon, confidence_score, weighted_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (r.timestamp.isoformat(), r.signal, r.importance_score, r.impact_type, r.time_horizon, r.confidence_score, r.weighted_score)
                for r in records
            ],
        )
        conn.commit()
    finally:
        conn.close()


def query_records(table: str, limit: Optional[int] = None, db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Return records from the specified table as a list of dicts."""
    conn = _get_connection(db_path)
    try:
        _init_tables(conn)
        sql = f"SELECT * FROM {table}"
        if limit:
            sql += " LIMIT ?"
            cur = conn.execute(sql, (limit,))
        else:
            cur = conn.execute(sql)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()