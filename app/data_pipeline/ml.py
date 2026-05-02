"""
Lightweight machine learning utilities for the data pipeline.

This module provides simple feature extraction and prediction helpers
that operate on signals and other structured inputs.  It serves as
the starting point for Phase 5 of the institutional‑scale roadmap,
where custom ML pipelines will be developed.  The goal here is
interpretability and minimalism: rather than training deep models,
these helpers expose clear heuristics and allow the system to
incrementally learn from past analyses.

Functions provided:

* :func:`extract_features` – Convert a list of signal strings into a
  list of feature dictionaries.  Features include keyword counts and
  length measures.  This can be fed into simple models.
* :func:`train_simple_model` – Train a linear model from features and
  labels by computing average weights.  This is not intended for
  production ML but shows where more advanced models can be plugged
  in later.
* :func:`predict_importance` – Apply learned weights to new feature
  dictionaries to produce importance scores.  Returns a list of
  floats corresponding to input feature dicts.

These functions deliberately avoid external ML libraries to keep
dependencies light and the behaviour easy to test.
"""

from __future__ import annotations

from typing import Dict, List, Iterable


def _keyword_counts(text: str, keywords: Iterable[str]) -> int:
    """Count occurrences of any keyword in the given text."""
    lower = text.lower()
    return sum(lower.count(kw) for kw in keywords)


def extract_features(signals: List[str]) -> List[Dict[str, float]]:
    """Extract simple numeric features from a list of signal strings.

    Each signal is transformed into a dictionary of numeric features
    that measure its composition.  Features include the length of the
    signal (number of words), counts of risk‑related keywords,
    opportunity‑related keywords, and macro‑related keywords.  These
    features form the basis for simple linear models.

    Parameters
    ----------
    signals: list[str]
        A list of signal descriptions to be featurised.

    Returns
    -------
    list[dict[str, float]]
        A list of feature dictionaries corresponding to each signal.
    """
    risk_keywords = ["risk", "regulatory", "litigation", "legal"]
    opportunity_keywords = ["growth", "opportunity", "expansion", "innovation"]
    macro_keywords = ["macro", "inflation", "interest", "unemployment", "gdp"]

    features: List[Dict[str, float]] = []
    for sig in signals:
        words = sig.split()
        feat = {
            "length": float(len(words)),
            "risk_count": float(_keyword_counts(sig, risk_keywords)),
            "opportunity_count": float(_keyword_counts(sig, opportunity_keywords)),
            "macro_count": float(_keyword_counts(sig, macro_keywords)),
        }
        features.append(feat)
    return features


def train_simple_model(features: List[Dict[str, float]], labels: List[float]) -> Dict[str, float]:
    """Train a simple linear model from features and labels.

    This function computes average weights by correlating each feature
    dimension with the provided labels.  It sums the product of
    feature values and labels, then divides by the sum of squares of
    the feature values.  A small epsilon is added to the denominator
    to avoid division by zero.  The result is a weight vector
    mapping feature names to floats.

    Parameters
    ----------
    features: list[dict[str, float]]
        A list of feature vectors.
    labels: list[float]
        A list of numeric labels (e.g. importance scores) with the
        same length as ``features``.

    Returns
    -------
    dict[str, float]
        A dictionary of learned weights keyed by feature name.
    """
    if not features or not labels or len(features) != len(labels):
        return {}

    # Initialise accumulators for numerator and denominator per feature.
    numerators: Dict[str, float] = {}
    denominators: Dict[str, float] = {}
    for feat, label in zip(features, labels):
        for name, value in feat.items():
            numerators[name] = numerators.get(name, 0.0) + value * label
            denominators[name] = denominators.get(name, 0.0) + value * value

    # Compute weights using simple linear regression formula.
    weights: Dict[str, float] = {}
    epsilon = 1e-6
    for name in numerators:
        denom = denominators.get(name, 0.0) + epsilon
        weights[name] = numerators[name] / denom
    return weights


def predict_importance(features: List[Dict[str, float]], weights: Dict[str, float]) -> List[float]:
    """Predict importance scores from features using learned weights.

    The importance of each feature vector is computed as the dot
    product between the vector and the weight vector.  If a feature
    name is missing from the weight dictionary, its weight is
    assumed to be zero.

    Parameters
    ----------
    features: list[dict[str, float]]
        Feature vectors to evaluate.
    weights: dict[str, float]
        Learned weights from ``train_simple_model``.

    Returns
    -------
    list[float]
        A list of predicted importance scores.
    """
    scores: List[float] = []
    for feat in features:
        score = 0.0
        for name, value in feat.items():
            score += value * weights.get(name, 0.0)
        scores.append(score)
    return scores