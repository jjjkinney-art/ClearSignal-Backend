"""Versioned issuer registry and coverage audit for Intelligence Benchmark cases.

The registry is metadata, not market truth.  A market-cap classification is
frozen as of the registry's stated date and must be revised by publishing a new
registry version, never by silently changing an old benchmark result.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .intelligence_benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkContractError,
    MarketCapTier,
    content_hash,
)
from .models import QueryFixture


REGISTRY_PATH = Path(__file__).with_name("issuer_registry.v1.json")
REQUIRED_CORE_CATEGORIES = frozenset(
    {"core_thesis", "decision_threshold", "structural_risk"}
)


@dataclass(frozen=True)
class IssuerProfile:
    ticker: str
    company: str
    market_cap_tier: MarketCapTier
    sector: str
    domicile: str
    reporting_basis: str
    complexity_tags: Tuple[str, ...] = ()

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "IssuerProfile":
        try:
            tier = MarketCapTier(str(value["market_cap_tier"]))
        except (KeyError, ValueError) as exc:
            raise BenchmarkContractError("issuer has an invalid market_cap_tier") from exc
        required = ("ticker", "company", "sector", "domicile", "reporting_basis")
        if any(not str(value.get(key, "")).strip() for key in required):
            raise BenchmarkContractError(f"issuer is missing required metadata: {required}")
        tags = tuple(str(tag).strip() for tag in value.get("complexity_tags", ()))
        if any(not tag for tag in tags) or tuple(sorted(set(tags))) != tags:
            raise BenchmarkContractError(
                "complexity_tags must be non-empty, unique, and sorted"
            )
        return IssuerProfile(
            ticker=str(value["ticker"]).upper(),
            company=str(value["company"]),
            market_cap_tier=tier,
            sector=str(value["sector"]),
            domicile=str(value["domicile"]),
            reporting_basis=str(value["reporting_basis"]),
            complexity_tags=tags,
        )


@dataclass(frozen=True)
class CoverageTargets:
    issuer_count: int
    minimum_by_market_cap: Tuple[Tuple[MarketCapTier, int], ...]
    minimum_sector_count: int
    minimum_complexity_tag_count: int

    @staticmethod
    def from_dict(value: Mapping[str, Any]) -> "CoverageTargets":
        tier_values = []
        for key, count in value.get("minimum_by_market_cap", {}).items():
            try:
                tier = MarketCapTier(str(key))
            except ValueError as exc:
                raise BenchmarkContractError(f"unknown coverage tier: {key}") from exc
            if int(count) < 0:
                raise BenchmarkContractError("coverage minimums cannot be negative")
            tier_values.append((tier, int(count)))
        return CoverageTargets(
            issuer_count=int(value["issuer_count"]),
            minimum_by_market_cap=tuple(sorted(tier_values, key=lambda item: item[0].value)),
            minimum_sector_count=int(value["minimum_sector_count"]),
            minimum_complexity_tag_count=int(value["minimum_complexity_tag_count"]),
        )


@dataclass(frozen=True)
class IssuerRegistry:
    registry_version: int
    schema_version: int
    classification_as_of: str
    issuers: Tuple[IssuerProfile, ...]
    targets: CoverageTargets

    @property
    def registry_sha256(self) -> str:
        return content_hash(self)

    def by_ticker(self) -> Dict[str, IssuerProfile]:
        return {issuer.ticker: issuer for issuer in self.issuers}


@dataclass(frozen=True)
class CoverageReport:
    registry_version: int
    registry_sha256: str
    issuer_count: int
    fixture_count: int
    market_cap_counts: Tuple[Tuple[str, int], ...]
    sector_count: int
    complexity_tag_count: int
    target_deficits: Tuple[str, ...]
    integrity_errors: Tuple[str, ...]

    @property
    def integrity_passed(self) -> bool:
        return not self.integrity_errors

    @property
    def launch_coverage_ready(self) -> bool:
        return self.integrity_passed and not self.target_deficits

    def to_dict(self) -> Dict[str, Any]:
        return {
            "registry_version": self.registry_version,
            "registry_sha256": self.registry_sha256,
            "issuer_count": self.issuer_count,
            "fixture_count": self.fixture_count,
            "market_cap_counts": dict(self.market_cap_counts),
            "sector_count": self.sector_count,
            "complexity_tag_count": self.complexity_tag_count,
            "target_deficits": list(self.target_deficits),
            "integrity_errors": list(self.integrity_errors),
            "integrity_passed": self.integrity_passed,
            "launch_coverage_ready": self.launch_coverage_ready,
        }


def load_registry(path: Path = REGISTRY_PATH) -> IssuerRegistry:
    data = json.loads(path.read_text())
    if int(data.get("schema_version", -1)) != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkContractError("registry schema_version is unsupported")
    version = int(data.get("registry_version", 0))
    if version < 1:
        raise BenchmarkContractError("registry_version must be positive")
    classification_as_of = str(data.get("classification_as_of", ""))
    if len(classification_as_of) != 10:
        raise BenchmarkContractError("classification_as_of must be YYYY-MM-DD")

    issuers = tuple(IssuerProfile.from_dict(item) for item in data.get("issuers", ()))
    tickers = [issuer.ticker for issuer in issuers]
    if tickers != sorted(tickers):
        raise BenchmarkContractError("issuers must be sorted by ticker")
    if len(tickers) != len(set(tickers)):
        raise BenchmarkContractError("issuer tickers must be unique")
    return IssuerRegistry(
        registry_version=version,
        schema_version=BENCHMARK_SCHEMA_VERSION,
        classification_as_of=classification_as_of,
        issuers=issuers,
        targets=CoverageTargets.from_dict(data["coverage_targets"]),
    )


def load_query_fixtures(path: Path) -> Tuple[QueryFixture, ...]:
    data = json.loads(path.read_text())
    return tuple(QueryFixture.from_dict(item) for item in data["fixtures"])


def audit_registry(
    registry: IssuerRegistry,
    fixtures: Sequence[QueryFixture],
) -> CoverageReport:
    errors = []
    fixture_ids = [fixture.id for fixture in fixtures]
    if len(fixture_ids) != len(set(fixture_ids)):
        errors.append("fixture ids are not unique")

    issuers = registry.by_ticker()
    fixture_groups: Dict[str, set] = {}
    for fixture in fixtures:
        ticker = fixture.ticker.upper()
        fixture_groups.setdefault(ticker, set()).add(fixture.category)
        issuer = issuers.get(ticker)
        if issuer is None:
            errors.append(f"fixture {fixture.id} has no issuer registry entry")
        elif fixture.company.casefold() != issuer.company.casefold():
            errors.append(
                f"fixture {fixture.id} company does not match registry company"
            )

    for ticker in sorted(fixture_groups):
        missing = REQUIRED_CORE_CATEGORIES - fixture_groups[ticker]
        if missing:
            errors.append(
                f"issuer {ticker} is missing core categories: {', '.join(sorted(missing))}"
            )
    for ticker in sorted(set(issuers) - set(fixture_groups)):
        errors.append(f"registry issuer {ticker} has no fixture")

    tier_counts = {tier: 0 for tier in MarketCapTier}
    sectors = set()
    tags = set()
    for issuer in registry.issuers:
        tier_counts[issuer.market_cap_tier] += 1
        sectors.add(issuer.sector)
        tags.update(issuer.complexity_tags)

    deficits = []
    if len(registry.issuers) < registry.targets.issuer_count:
        deficits.append(
            f"issuer target shortfall: {len(registry.issuers)}/{registry.targets.issuer_count}"
        )
    for tier, minimum in registry.targets.minimum_by_market_cap:
        actual = tier_counts[tier]
        if actual < minimum:
            deficits.append(
                f"{tier.value} target shortfall: {actual}/{minimum}"
            )
    if len(sectors) < registry.targets.minimum_sector_count:
        deficits.append(
            f"sector target shortfall: {len(sectors)}/{registry.targets.minimum_sector_count}"
        )
    if len(tags) < registry.targets.minimum_complexity_tag_count:
        deficits.append(
            "complexity-tag target shortfall: "
            f"{len(tags)}/{registry.targets.minimum_complexity_tag_count}"
        )

    return CoverageReport(
        registry_version=registry.registry_version,
        registry_sha256=registry.registry_sha256,
        issuer_count=len(registry.issuers),
        fixture_count=len(fixtures),
        market_cap_counts=tuple(
            (tier.value, tier_counts[tier]) for tier in MarketCapTier
        ),
        sector_count=len(sectors),
        complexity_tag_count=len(tags),
        target_deficits=tuple(deficits),
        integrity_errors=tuple(errors),
    )

