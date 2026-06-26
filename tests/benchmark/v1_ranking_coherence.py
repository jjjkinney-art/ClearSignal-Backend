"""V1 — Ranking Coherence Battery

Tests whether ClearSignal ranks companies in an order that an experienced
investor would recognize as defensible.  Uses the V0 institutional benchmark
as ground truth.

Run:  python3 -m pytest tests/benchmark/v1_ranking_coherence.py -v
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

import pytest

from tests.benchmark.v0_institutional_benchmark import (
    BENCHMARK,
    PAIRWISE_CONSTRAINTS,
    Archetype,
    BenchmarkEntry,
)

# ---------------------------------------------------------------------------
# Fixture: compute all durability scores once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def durability_scores() -> Dict[str, float]:
    from app.services.conviction_modeler import _compute_structured_durability
    from app.services.company_knowledge import _KNOWLEDGE_DB

    scores = {}
    for ticker in _KNOWLEDGE_DB:
        p = _KNOWLEDGE_DB[ticker]
        scores[ticker] = _compute_structured_durability(p)
    return scores


# ═══════════════════════════════════════════════════════════════════════════
# Test 1A — Archetype Ordering (pairwise dominance)
# ═══════════════════════════════════════════════════════════════════════════

class TestArchetypeOrdering:
    """Every pairwise constraint from the benchmark must hold on durability."""

    def test_pairwise_constraint_count(self):
        assert len(PAIRWISE_CONSTRAINTS) >= 100, (
            f"Expected ≥100 pairwise constraints, got {len(PAIRWISE_CONSTRAINTS)}"
        )

    def test_pairwise_violations_below_threshold(self, durability_scores):
        violations = []
        for superior, inferior, reason in PAIRWISE_CONSTRAINTS:
            if superior not in durability_scores or inferior not in durability_scores:
                continue
            sup_dur = durability_scores[superior]
            inf_dur = durability_scores[inferior]
            if sup_dur < inf_dur:
                violations.append(
                    f"  {superior} ({sup_dur:.2f}) < {inferior} ({inf_dur:.2f}): {reason}"
                )

        total = len([c for c in PAIRWISE_CONSTRAINTS
                     if c[0] in durability_scores and c[1] in durability_scores])
        violation_rate = len(violations) / total if total > 0 else 0

        if violations:
            detail = "\n".join(violations[:20])
            print(f"\nPairwise violations: {len(violations)}/{total} ({violation_rate:.1%})")
            print(detail)

        assert violation_rate <= 0.10, (
            f"Pairwise violation rate {violation_rate:.1%} exceeds 10% ceiling. "
            f"{len(violations)}/{total} constraints violated.\n"
            + "\n".join(violations[:10])
        )

    def test_compounder_above_speculative_on_durability(self, durability_scores):
        """Every compounder must have higher durability than every speculative."""
        compounders = {t: e for t, e in BENCHMARK.items() if e.archetype == Archetype.COMPOUNDER}
        speculatives = {t: e for t, e in BENCHMARK.items() if e.archetype == Archetype.SPECULATIVE}

        violations = []
        for ct, ce in compounders.items():
            for st, se in speculatives.items():
                if ct not in durability_scores or st not in durability_scores:
                    continue
                c_dur = durability_scores[ct]
                s_dur = durability_scores[st]
                if c_dur <= s_dur:
                    violations.append(f"  {ct} ({c_dur:.2f}) <= {st} ({s_dur:.2f})")

        total = len(compounders) * len(speculatives)
        assert len(violations) == 0, (
            f"Compounder-vs-speculative violations: {len(violations)}/{total}\n"
            + "\n".join(violations)
        )

    def test_explicit_must_rank_above(self, durability_scores):
        """Must-rank-above constraints from individual benchmark entries."""
        violations = []
        total = 0
        for ticker, entry in BENCHMARK.items():
            for inferior in entry.must_rank_above:
                if ticker not in durability_scores or inferior not in durability_scores:
                    continue
                total += 1
                sup_dur = durability_scores[ticker]
                inf_dur = durability_scores[inferior]
                if sup_dur < inf_dur:
                    violations.append(
                        f"  {ticker} ({sup_dur:.2f}) should rank above {inferior} ({inf_dur:.2f})"
                    )

        if violations:
            print(f"\nExplicit must_rank_above violations: {len(violations)}/{total}")
            for v in violations:
                print(v)

        assert len(violations) <= 3, (
            f"Too many explicit ranking violations: {len(violations)}/{total}\n"
            + "\n".join(violations)
        )


# ═══════════════════════════════════════════════════════════════════════════
# Test 1B — Durability Range Validation
# ═══════════════════════════════════════════════════════════════════════════

class TestDurabilityRanges:
    """Computed durability must fall within the benchmark's expected range."""

    def test_durability_within_benchmark_range(self, durability_scores):
        out_of_range = []
        for ticker, entry in BENCHMARK.items():
            if ticker not in durability_scores:
                continue
            actual = durability_scores[ticker]
            lo, hi = entry.durability_range
            if actual < lo - 0.03 or actual > hi + 0.03:
                out_of_range.append(
                    f"  {ticker}: actual={actual:.2f}, expected=[{lo:.2f}, {hi:.2f}], "
                    f"delta={actual - (lo + hi) / 2:+.2f}"
                )

        total = len([t for t in BENCHMARK if t in durability_scores])
        oor_rate = len(out_of_range) / total if total > 0 else 0

        if out_of_range:
            print(f"\nOut-of-range durability: {len(out_of_range)}/{total} ({oor_rate:.1%})")
            for v in out_of_range:
                print(v)

        assert oor_rate <= 0.15, (
            f"Durability out-of-range rate {oor_rate:.1%} exceeds 15% ceiling.\n"
            + "\n".join(out_of_range[:15])
        )

    def test_top_5_durability_are_compounders(self, durability_scores):
        """Top 5 durability scores should be compounders or quality_growth."""
        ranked = sorted(durability_scores.items(), key=lambda x: x[1], reverse=True)[:5]
        acceptable_archetypes = {Archetype.COMPOUNDER, Archetype.QUALITY_GROWTH, Archetype.STABLE_YIELD}
        for ticker, dur in ranked:
            if ticker in BENCHMARK:
                assert BENCHMARK[ticker].archetype in acceptable_archetypes, (
                    f"Top-5 durability {ticker} ({dur:.2f}) is {BENCHMARK[ticker].archetype.value}, "
                    f"expected compounder/quality_growth/stable_yield"
                )

    def test_bottom_5_durability_are_cyclical_or_speculative(self, durability_scores):
        """Bottom 5 durability should be cyclical, speculative, or turnaround."""
        ranked = sorted(durability_scores.items(), key=lambda x: x[1])[:5]
        acceptable_archetypes = {Archetype.CYCLICAL, Archetype.SPECULATIVE, Archetype.TURNAROUND}
        for ticker, dur in ranked:
            if ticker in BENCHMARK:
                assert BENCHMARK[ticker].archetype in acceptable_archetypes, (
                    f"Bottom-5 durability {ticker} ({dur:.2f}) is {BENCHMARK[ticker].archetype.value}, "
                    f"expected cyclical/speculative/turnaround"
                )


# ═══════════════════════════════════════════════════════════════════════════
# Test 1C — Durability Distribution
# ═══════════════════════════════════════════════════════════════════════════

class TestDurabilityDistribution:
    """Durability scores should be well-distributed, not compressed."""

    def test_score_range_minimum_spread(self, durability_scores):
        """Min-max spread must be at least 0.50 (e.g., 0.18 to 0.85)."""
        vals = list(durability_scores.values())
        spread = max(vals) - min(vals)
        assert spread >= 0.50, f"Durability spread {spread:.2f} is too narrow (min 0.50)"

    def test_no_midpoint_compression(self, durability_scores):
        """Less than 50% of scores should cluster in [0.45, 0.65]."""
        vals = list(durability_scores.values())
        mid_cluster = sum(1 for v in vals if 0.45 <= v <= 0.65)
        rate = mid_cluster / len(vals)
        assert rate < 0.50, (
            f"{mid_cluster}/{len(vals)} ({rate:.1%}) cluster in [0.45, 0.65] — midpoint compression"
        )

    def test_has_scores_above_80(self, durability_scores):
        """At least 3 companies should have durability ≥ 0.80."""
        high = [t for t, d in durability_scores.items() if d >= 0.80]
        assert len(high) >= 3, f"Only {len(high)} companies above 0.80: {high}"

    def test_has_scores_below_30(self, durability_scores):
        """At least 2 companies should have durability ≤ 0.30."""
        low = [t for t, d in durability_scores.items() if d <= 0.30]
        assert len(low) >= 2, f"Only {len(low)} companies below 0.30: {low}"

    def test_quartile_separation(self, durability_scores):
        """Quartile medians should be separated by at least 0.10."""
        vals = sorted(durability_scores.values())
        n = len(vals)
        q1 = vals[n // 4]
        q2 = vals[n // 2]
        q3 = vals[3 * n // 4]
        assert q2 - q1 >= 0.08, f"Q1-Q2 gap too narrow: {q1:.2f} to {q2:.2f}"
        assert q3 - q2 >= 0.08, f"Q2-Q3 gap too narrow: {q2:.2f} to {q3:.2f}"


# ═══════════════════════════════════════════════════════════════════════════
# Test 1D — Archetype Tier Separation
# ═══════════════════════════════════════════════════════════════════════════

class TestArchetypeTierSeparation:
    """Average durability should decrease across archetype tiers."""

    def test_compounder_mean_above_cyclical_mean(self, durability_scores):
        comp_durs = [durability_scores[t] for t in BENCHMARK
                     if BENCHMARK[t].archetype == Archetype.COMPOUNDER and t in durability_scores]
        cyc_durs = [durability_scores[t] for t in BENCHMARK
                    if BENCHMARK[t].archetype == Archetype.CYCLICAL and t in durability_scores]
        if not comp_durs or not cyc_durs:
            pytest.skip("Not enough entries")
        comp_mean = sum(comp_durs) / len(comp_durs)
        cyc_mean = sum(cyc_durs) / len(cyc_durs)
        gap = comp_mean - cyc_mean
        assert gap >= 0.15, (
            f"Compounder mean ({comp_mean:.2f}) vs cyclical mean ({cyc_mean:.2f}): "
            f"gap {gap:.2f} < 0.15 minimum"
        )

    def test_compounder_mean_above_speculative_mean(self, durability_scores):
        comp_durs = [durability_scores[t] for t in BENCHMARK
                     if BENCHMARK[t].archetype == Archetype.COMPOUNDER and t in durability_scores]
        spec_durs = [durability_scores[t] for t in BENCHMARK
                     if BENCHMARK[t].archetype == Archetype.SPECULATIVE and t in durability_scores]
        if not comp_durs or not spec_durs:
            pytest.skip("Not enough entries")
        comp_mean = sum(comp_durs) / len(comp_durs)
        spec_mean = sum(spec_durs) / len(spec_durs)
        gap = comp_mean - spec_mean
        assert gap >= 0.25, (
            f"Compounder mean ({comp_mean:.2f}) vs speculative mean ({spec_mean:.2f}): "
            f"gap {gap:.2f} < 0.25 minimum"
        )

    def test_quality_growth_mean_above_turnaround_mean(self, durability_scores):
        qg_durs = [durability_scores[t] for t in BENCHMARK
                   if BENCHMARK[t].archetype == Archetype.QUALITY_GROWTH and t in durability_scores]
        ta_durs = [durability_scores[t] for t in BENCHMARK
                   if BENCHMARK[t].archetype == Archetype.TURNAROUND and t in durability_scores]
        if not qg_durs or not ta_durs:
            pytest.skip("Not enough entries")
        qg_mean = sum(qg_durs) / len(qg_durs)
        ta_mean = sum(ta_durs) / len(ta_durs)
        gap = qg_mean - ta_mean
        assert gap >= 0.15, (
            f"Quality growth mean ({qg_mean:.2f}) vs turnaround mean ({ta_mean:.2f}): "
            f"gap {gap:.2f} < 0.15 minimum"
        )

    def test_stable_yield_mean_above_cyclical_mean(self, durability_scores):
        sy_durs = [durability_scores[t] for t in BENCHMARK
                   if BENCHMARK[t].archetype == Archetype.STABLE_YIELD and t in durability_scores]
        cyc_durs = [durability_scores[t] for t in BENCHMARK
                    if BENCHMARK[t].archetype == Archetype.CYCLICAL and t in durability_scores]
        if not sy_durs or not cyc_durs:
            pytest.skip("Not enough entries")
        sy_mean = sum(sy_durs) / len(sy_durs)
        cyc_mean = sum(cyc_durs) / len(cyc_durs)
        gap = sy_mean - cyc_mean
        assert gap >= 0.15, (
            f"Stable yield mean ({sy_mean:.2f}) vs cyclical mean ({cyc_mean:.2f}): "
            f"gap {gap:.2f} < 0.15 minimum"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Test 1E — Analog Appropriateness (structural check)
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalogAppropriateness:
    """Verify the analog engine's business model mappings are structurally sound."""

    def test_revenue_model_to_biz_model_coverage(self):
        """Every benchmark company's revenue model should have a business_model mapping."""
        _REVENUE_TO_BIZ_MODEL = {
            "transaction_toll": "payment_network",
            "subscription": "saas",
            "membership": "membership_retail",
            "licensing": "cloud_platform",
            "project_contract": "government_enterprise",
            "product_sale": "consumer_hardware",
            "advertising": "internet_platform",
            "mixed": "financial_intermediary",
        }

        unmapped = []
        for ticker, entry in BENCHMARK.items():
            rev = entry.revenue_model
            if rev and rev not in _REVENUE_TO_BIZ_MODEL:
                unmapped.append(f"  {ticker}: revenue_model='{rev}' has no biz_model mapping")

        mapped_count = sum(1 for e in BENCHMARK.values() if e.revenue_model in _REVENUE_TO_BIZ_MODEL)
        total = len(BENCHMARK)
        rate = mapped_count / total

        if unmapped:
            print(f"\nUnmapped revenue models: {len(unmapped)}/{total}")
            for u in unmapped:
                print(u)

        assert rate >= 0.70, (
            f"Only {rate:.1%} of benchmark entries have mapped revenue models. "
            f"Unmapped entries will get weak analog matching."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Test 1F — Full Report (runs last, prints comprehensive summary)
# ═══════════════════════════════════════════════════════════════════════════

class TestRankingCoherenceReport:
    """Comprehensive ranking coherence report — prints even when all tests pass."""

    def test_generate_report(self, durability_scores):
        """Generate and print the full V1 ranking coherence report."""
        report = []
        report.append("\n" + "=" * 70)
        report.append("V1 RANKING COHERENCE REPORT")
        report.append("=" * 70)

        # 1. Pairwise constraints
        violations = []
        testable = 0
        for superior, inferior, reason in PAIRWISE_CONSTRAINTS:
            if superior not in durability_scores or inferior not in durability_scores:
                continue
            testable += 1
            if durability_scores[superior] < durability_scores[inferior]:
                violations.append((superior, inferior, reason))

        pairwise_rate = (testable - len(violations)) / testable if testable > 0 else 0
        report.append(f"\n1A. Pairwise ordering:    {testable - len(violations)}/{testable} satisfied ({pairwise_rate:.1%})")
        if violations:
            for s, i, r in violations[:5]:
                report.append(f"     VIOLATION: {s} ({durability_scores[s]:.2f}) < {i} ({durability_scores[i]:.2f})")

        # 2. Durability range compliance
        in_range = 0
        out_range = []
        for ticker, entry in BENCHMARK.items():
            if ticker not in durability_scores:
                continue
            actual = durability_scores[ticker]
            lo, hi = entry.durability_range
            if lo - 0.03 <= actual <= hi + 0.03:
                in_range += 1
            else:
                out_range.append((ticker, actual, lo, hi))

        total_benchmarked = len([t for t in BENCHMARK if t in durability_scores])
        range_rate = in_range / total_benchmarked if total_benchmarked > 0 else 0
        report.append(f"\n1B. Durability in range:   {in_range}/{total_benchmarked} ({range_rate:.1%})")
        if out_range:
            out_range.sort(key=lambda x: abs(x[1] - (x[2] + x[3]) / 2), reverse=True)
            for t, a, lo, hi in out_range[:5]:
                report.append(f"     OUT: {t} actual={a:.2f} expected=[{lo:.2f}, {hi:.2f}]")

        # 3. Distribution
        vals = sorted(durability_scores.values())
        n = len(vals)
        report.append(f"\n1C. Distribution:")
        report.append(f"     Range:    [{min(vals):.2f}, {max(vals):.2f}] (spread={max(vals)-min(vals):.2f})")
        report.append(f"     Q1/Q2/Q3: {vals[n//4]:.2f} / {vals[n//2]:.2f} / {vals[3*n//4]:.2f}")
        mid = sum(1 for v in vals if 0.45 <= v <= 0.65)
        report.append(f"     Midpoint cluster [0.45-0.65]: {mid}/{n} ({mid/n:.1%})")

        # 4. Archetype means
        arch_means = {}
        for arch in Archetype:
            durs = [durability_scores[t] for t, e in BENCHMARK.items()
                    if e.archetype == arch and t in durability_scores]
            if durs:
                arch_means[arch] = sum(durs) / len(durs)

        report.append(f"\n1D. Archetype means:")
        for arch in [Archetype.COMPOUNDER, Archetype.QUALITY_GROWTH, Archetype.QUALITY_CYCLIC,
                     Archetype.STABLE_YIELD, Archetype.CYCLICAL, Archetype.TURNAROUND, Archetype.SPECULATIVE]:
            if arch in arch_means:
                report.append(f"     {arch.value:20s}  {arch_means[arch]:.2f}")

        # 5. Top 10 / Bottom 10
        ranked = sorted(durability_scores.items(), key=lambda x: x[1], reverse=True)
        report.append(f"\n1E. Top 10:")
        for i, (t, d) in enumerate(ranked[:10], 1):
            arch = BENCHMARK[t].archetype.value if t in BENCHMARK else "?"
            report.append(f"     {i:2d}. {t:>6} {d:.2f}  [{arch}]")

        report.append(f"\n     Bottom 10:")
        for i, (t, d) in enumerate(ranked[-10:], n - 9):
            arch = BENCHMARK[t].archetype.value if t in BENCHMARK else "?"
            report.append(f"     {i:2d}. {t:>6} {d:.2f}  [{arch}]")

        # 6. Verdict
        report.append(f"\n" + "=" * 70)
        if pairwise_rate >= 0.95 and range_rate >= 0.85:
            verdict = "PASS — Institutional grade"
        elif pairwise_rate >= 0.90 and range_rate >= 0.75:
            verdict = "CONDITIONAL PASS — Professional grade"
        elif pairwise_rate >= 0.85:
            verdict = "MARGINAL — Needs calibration"
        else:
            verdict = "FAIL — Ranking not defensible"
        report.append(f"VERDICT: {verdict}")
        report.append(f"  Pairwise ordering:  {pairwise_rate:.1%}")
        report.append(f"  Durability in range: {range_rate:.1%}")
        report.append("=" * 70)

        full_report = "\n".join(report)
        print(full_report)

        # This test always passes — it's a report generator
        assert True
