"""
Structured record definitions for the data pipeline.

This module defines simple Pydantic models representing rows in
historical data tables.  These schemas are used both for validating
ingested data before storage and for constructing objects when
retrieving data from the storage layer.  Fields are kept minimal
to avoid overconstraining the early implementation; additional
fields can be added in future phases as more data becomes
available.
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class PriceRecord(BaseModel):
    """Represents a single point in a security's price history."""

    ticker: str = Field(..., description="Ticker symbol, e.g., TSLA")
    timestamp: datetime = Field(..., description="Timestamp of the price observation")
    price: float = Field(..., description="Close price at the given timestamp")
    volume: Optional[int] = Field(None, description="Trade volume for the period")


class FinancialRecord(BaseModel):
    """Represents a historical financial metric for a company."""

    ticker: str = Field(..., description="Ticker symbol")
    timestamp: datetime = Field(..., description="Timestamp of the metric observation")
    metric_name: str = Field(..., description="Name of the financial metric, e.g. revenue")
    value: float = Field(..., description="Numeric value of the metric")


class EventRecord(BaseModel):
    """Represents a discrete event in a company's history."""

    ticker: str = Field(..., description="Ticker symbol")
    timestamp: datetime = Field(..., description="Event timestamp")
    event_type: str = Field(..., description="Categorised type of event, e.g. earnings, regulatory")
    description: str = Field(..., description="Human‑readable description of the event")
    source: str = Field(..., description="Source of the event data")


class SignalRecord(BaseModel):
    """Represents a historical intelligence signal and its scoring."""

    timestamp: datetime = Field(..., description="Time when the signal was generated")
    signal: str = Field(..., description="Signal description")
    importance_score: float = Field(..., description="Importance score (0–100)")
    impact_type: str = Field(..., description="Impact type (risk/growth/macro/structural)")
    time_horizon: str = Field(..., description="Time horizon (short/medium/long)")
    confidence_score: float = Field(..., description="Confidence score (0–1)")
    weighted_score: float = Field(..., description="Weighted score used for ranking")
