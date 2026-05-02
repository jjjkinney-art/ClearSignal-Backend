"""
Simulated distributed compute patterns for the data pipeline.

This module introduces simple abstractions to separate tasks into
logical workers.  While the current implementation executes
functions concurrently within a single process, the design mirrors
the way a distributed system might organise ingestion, analysis and
monitoring workers.  The functions here can be swapped out for
real message queues or distributed task runners in later phases
without changing the call sites.

Functions provided:

* :func:`run_concurrent` – Execute a collection of callables
  concurrently using threads and return their results in order.
* :func:`run_asyncio_tasks` – Utility to run asynchronous coroutines
  concurrently using ``asyncio.gather``.  This can be used to
  simulate separate event loops per worker type.

These helpers are intentionally lightweight and avoid external
dependencies.  They provide an abstraction boundary for future
distributed integration.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, List, Any, Awaitable
import asyncio


def run_concurrent(tasks: Iterable[Callable[[], Any]], max_workers: int = 5) -> List[Any]:
    """Run a collection of synchronous callables concurrently.

    This helper uses a ``ThreadPoolExecutor`` to execute each task
    in its own thread.  Results are returned in the same order as
    the tasks were provided.  Exceptions are propagated to the
    caller.

    Parameters
    ----------
    tasks: iterable[callable]
        A sequence of zero‑argument callables to run concurrently.
    max_workers: int
        The maximum number of worker threads to use.  Defaults to 5.

    Returns
    -------
    list
        The results of each task in the original order.
    """
    tasks_list = list(tasks)
    if not tasks_list:
        return []
    results: List[Any] = [None] * len(tasks_list)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(task): i for i, task in enumerate(tasks_list)}
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            results[idx] = future.result()
    return results


async def run_asyncio_tasks(tasks: Iterable[Awaitable[Any]]) -> List[Any]:
    """Run a collection of asynchronous tasks concurrently.

    This function wraps ``asyncio.gather`` and returns a list of
    results.  It ensures that tasks execute concurrently within the
    current event loop and propagate exceptions.

    Parameters
    ----------
    tasks: iterable[awaitable]
        A sequence of awaitable objects (coroutines or futures).

    Returns
    -------
    list
        The results of each awaitable, in the same order as the
        input.
    """
    tasks_list = list(tasks)
    if not tasks_list:
        return []
    return await asyncio.gather(*tasks_list)