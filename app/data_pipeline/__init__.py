"""
Data pipeline package for the AI analyst backend.

This package contains modules for ingesting, storing, and streaming
financial and event data from external sources.  It is designed to
extend the existing backend toward an institutional‑scale intelligence
platform by introducing layered data infrastructure.  The modules
exposed here support Phase 1 (data ingestion and storage) and
Phase 2 (lightweight real‑time streaming) of the scaling roadmap.

Modules included:

* ``schemas`` – definitions of structured records for historical data.
* ``storage`` – simple SQLite‑based storage backend for persisting
  historical data.
* ``ingestion`` – functions to fetch data from providers and
  normalise it into structured records.  These functions call
  existing provider utilities and should be idempotent.
* ``streaming`` – asynchronous utilities for polling external
  sources and generating update events.  Streaming is implemented
  with lightweight polling loops and does not require external
  message brokers.
* ``ml`` – stubs for future feature extraction and learning
  pipelines.  Provides simple helpers today and defines where
  more advanced ML will be integrated in later phases.
* ``distributed`` – stubs for future distributed compute patterns.

The package is intentionally modular and extensible.  Further
subpackages can be added for advanced ingestion (e.g. websockets),
additional storage backends, or integration with message brokers.
"""

# Re‑export submodules for convenient access.  Import order is
# intentionally explicit so that dependent modules can reference
# ``data_pipeline.ml`` and ``data_pipeline.distributed`` without
# triggering import errors when these files are added.
from . import schemas as schemas  # noqa: F401
from . import storage as storage  # noqa: F401
from . import ingestion as ingestion  # noqa: F401
from . import streaming as streaming  # noqa: F401
from . import ml as ml  # noqa: F401
from . import distributed as distributed  # noqa: F401

__all__ = [
    "schemas",
    "storage",
    "ingestion",
    "streaming",
    "ml",
    "distributed",
]