"""
Lightweight streaming utilities.

This module implements asynchronous polling loops that simulate
real‑time streaming of data from external providers.  The goal is
to provide event‑driven updates without introducing heavy
dependencies like Kafka or Celery.  Each streamer runs in its own
async task and periodically invokes ingestion functions.  In later
phases these loops can be replaced by true streaming connectors.

Lifecycle
---------
- ``start_streaming(...)`` runs polling tasks until cancelled OR until
  ``stop_streaming()`` is called.
- ``stop_streaming()`` is a synchronous helper that signals the module
  ``_stop_event`` so all running ``_stream_for_symbol`` loops exit at
  their next sleep boundary (within 1 second).
- Tests that spawn streaming MUST call ``stop_streaming()`` and then
  await/cancel the task in teardown — otherwise pytest will hang on
  the open event loop.

Usage example::

    import asyncio
    from app.data_pipeline.streaming import start_streaming, stop_streaming

    async def main():
        await start_streaming(["TSLA", "AAPL"], interval_seconds=60)

    asyncio.run(main())

You can control polling intervals per source by passing separate
parameters.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Iterable, List, Optional

from .ingestion import ingest_price_history, ingest_financial_history, ingest_events

logger = logging.getLogger(__name__)


# ── Module-level stop event ──────────────────────────────────────────────
# This is a thread-safe flag that all streaming loops poll between
# iterations.  Tests and shutdown hooks can call ``stop_streaming()``
# to break out of every running loop within ~1 second.
_stop_event: threading.Event = threading.Event()


def stop_streaming() -> None:
    """Signal all running streaming loops to exit.

    Safe to call from tests, signal handlers, or shutdown hooks.
    Loops will exit at their next sleep boundary (within ~1 second).
    """
    _stop_event.set()


def reset_streaming_stop() -> None:
    """Clear the stop event so streaming can be restarted.

    Used after ``stop_streaming()`` if the same process needs to start
    streaming again (uncommon, but useful for tests that exercise both
    start and stop).
    """
    _stop_event.clear()


async def _stream_for_symbol(
    symbol: str,
    company: str,
    price_interval: int,
    events_interval: int,
    financial_interval: int,
) -> None:
    """Run polling loops for a single symbol.

    Exits cleanly when ``_stop_event`` is set or the task is cancelled.
    """
    # Track last run times to avoid overlapping tasks
    last_price = 0.0
    last_events = 0.0
    last_financial = 0.0
    while not _stop_event.is_set():
        now = asyncio.get_event_loop().time()
        # Price updates
        if now - last_price >= price_interval:
            try:
                ingest_price_history(symbol)
            except Exception as exc:
                logger.warning(f"Streaming price ingestion error for {symbol}: {exc}")
            last_price = now
        # Event updates
        if now - last_events >= events_interval:
            try:
                ingest_events(company, symbol)
            except Exception as exc:
                logger.warning(f"Streaming event ingestion error for {symbol}: {exc}")
            last_events = now
        # Financial updates
        if now - last_financial >= financial_interval:
            try:
                ingest_financial_history(symbol)
            except Exception as exc:
                logger.warning(f"Streaming financial ingestion error for {symbol}: {exc}")
            last_financial = now
        # Sleep briefly before next iteration; the stop_event check above
        # guarantees prompt exit when shutdown is requested.
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            return


async def start_streaming(
    symbols: Iterable[str],
    company_names: Optional[Iterable[str]] = None,
    price_interval: int = 60,
    events_interval: int = 300,
    financial_interval: int = 3600,
) -> None:
    """Start streaming data for multiple symbols.

    Lifecycle
    ---------
    - Each symbol gets its own ``_stream_for_symbol`` task.
    - Tasks run until ``stop_streaming()`` is called or this coroutine
      is cancelled.
    - On cancellation, all child tasks are cancelled and awaited so no
      task survives the shutdown.

    Parameters
    ----------
    symbols : Iterable[str]
        Ticker symbols to stream updates for.
    company_names : Iterable[str] or None
        Company names corresponding to the symbols.  If provided, its
        length must match ``symbols``.  Otherwise, symbol names are
        used as company names.
    price_interval : int, default 60
        Polling interval for price updates in seconds.
    events_interval : int, default 300
        Polling interval for news/filings updates in seconds.
    financial_interval : int, default 3600
        Polling interval for financial metrics updates in seconds.
    """
    # Reset any leftover stop signal from a prior run
    _stop_event.clear()

    companies: List[str]
    syms: List[str] = list(symbols)
    if company_names is None:
        companies = syms
    else:
        companies = list(company_names)
        if len(companies) != len(syms):
            raise ValueError("company_names must match symbols length")
    tasks: List[asyncio.Task] = []
    for sym, comp in zip(syms, companies):
        tasks.append(asyncio.create_task(
            _stream_for_symbol(sym, comp, price_interval, events_interval, financial_interval)
        ))
    # Run tasks until cancelled or stop_event is set.  Both paths
    # converge on cancelling all child tasks and awaiting them so
    # nothing survives shutdown.
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        # Wait for cancellations to settle — bounded so a misbehaving
        # task cannot block shutdown forever.
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Streaming shutdown exceeded 2s timeout; proceeding")
        raise
    finally:
        # Ensure any stragglers are cancelled even on normal exit
        for t in tasks:
            if not t.done():
                t.cancel()