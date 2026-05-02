"""
Tests for the data pipeline modules.

These tests verify that the ingestion utilities correctly normalise
data from provider functions into structured records, that the
lightweight ML helpers operate on feature vectors as expected, and
that the simulated distributed compute functions run tasks
concurrently without reordering results.  Provider functions are
patched using ``monkeypatch`` to avoid external network calls.
"""

import asyncio
import os
import sys
from typing import List

import pytest

# Ensure the ``app`` package can be imported when tests run from
# ``ai_analyst_backend/tests``.  Adding the parent directory to
# sys.path is necessary for these relative imports.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.data_pipeline import ingestion, ml, distributed


def test_ingest_price_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Price ingestion should create a PriceRecord when provider returns a snapshot."""
    # Capture inserted price records via a local list
    inserted: List[Any] = []

    # Patch market snapshot provider to return a known value
    monkeypatch.setattr(
        ingestion, "get_market_snapshot", lambda symbol, api_key="": {"price": 42.0, "volume": 1234}
    )
    # Patch storage insertion to record the inserted record rather than writing to DB
    monkeypatch.setattr(
        ingestion, "insert_price_records", lambda records, db_path=None: inserted.extend(records)
    )
    # Run ingestion
    ingestion.ingest_price_history("FOO")
    # One record should be captured
    assert len(inserted) == 1
    rec = inserted[0]
    # Validate fields
    assert rec.ticker == "FOO"
    assert rec.price == 42.0
    assert rec.volume == 1234


def test_extract_features_and_model() -> None:
    """ML helpers should produce consistent feature extraction, training and prediction."""
    signals = [
        "Regulatory risk due to new policy",
        "Strong growth opportunities in emerging markets",
        "Macro headwinds from inflation and interest rates",
    ]
    feats = ml.extract_features(signals)
    # Feature length should match signals
    assert len(feats) == len(signals)
    # Train a simple model with dummy labels
    labels = [0.8, 0.2, 0.5]
    weights = ml.train_simple_model(feats, labels)
    # Weights should include feature keys
    assert all(k in weights for k in ["length", "risk_count", "opportunity_count", "macro_count"])
    # Predict importance scores
    scores = ml.predict_importance(feats, weights)
    assert len(scores) == len(signals)
    # At least one score should differ due to varying features
    assert len(set(scores)) > 1


def test_run_concurrent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distributed helper should run tasks concurrently and preserve order of results."""
    calls: List[int] = []

    def make_task(i: int):
        def _task():
            calls.append(i)
            return i * i
        return _task

    tasks = [make_task(i) for i in range(5)]
    results = distributed.run_concurrent(tasks, max_workers=2)
    # Results should be squares of indices in the same order
    assert results == [i * i for i in range(5)]
    # Ensure each task was called once
    assert calls == list(range(5))


@pytest.mark.anyio
async def test_run_asyncio_tasks() -> None:
    """Async distributed helper should run coroutines and return ordered results."""
    async def coro(i: int) -> int:
        await asyncio.sleep(0.01)
        return i + 1
    tasks = [coro(i) for i in range(3)]
    results = await distributed.run_asyncio_tasks(tasks)
    assert results == [1, 2, 3]