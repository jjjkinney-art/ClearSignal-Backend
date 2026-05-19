"""
Access control and feature gating.

Architecture for plan-based feature gating. Currently operates in
stub mode — all features accessible, no enforcement. Wire to a real
auth/billing system by replacing the stub methods.

Plans:
  Free         — Basic analysis, 5 watchlist slots, 10 analyses/day
  Pro          — Full analysis, 50 watchlist slots, unlimited, morning brief
  Institutional — All features, unlimited, team workspace, API access

Usage:
    gate = FeatureGate(plan="free")
    gate.require("morning_brief")  # raises PlanGateError if not on Pro+
    gate.check("morning_brief")    # returns bool
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

# ── Plan definitions ───────────────────────────────────────────────────────────

@dataclass
class PlanEntitlements:
    """What a plan tier allows."""
    plan_name: str
    max_watchlist_slots: int
    max_analyses_per_day: int
    features: Set[str]   # feature keys this plan can access
    rate_limit_rpm: int  # requests per minute
    api_access: bool = False
    team_workspace: bool = False

_PLANS: Dict[str, PlanEntitlements] = {
    "free": PlanEntitlements(
        plan_name="free",
        max_watchlist_slots=5,
        max_analyses_per_day=10,
        rate_limit_rpm=20,
        features={
            "analyze",
            "watchlist_basic",
            "alerts_basic",
            "timeline_basic",
        },
    ),
    "pro": PlanEntitlements(
        plan_name="pro",
        max_watchlist_slots=50,
        max_analyses_per_day=0,   # unlimited
        rate_limit_rpm=60,
        features={
            "analyze",
            "watchlist_basic",
            "watchlist_intelligence",
            "alerts_basic",
            "alerts_priority",
            "timeline_basic",
            "timeline_events",
            "morning_brief",
            "evidence_traceability",
            "thesis_memory",
        },
    ),
    "institutional": PlanEntitlements(
        plan_name="institutional",
        max_watchlist_slots=0,    # unlimited
        max_analyses_per_day=0,   # unlimited
        rate_limit_rpm=300,
        api_access=True,
        team_workspace=True,
        features={
            "analyze",
            "watchlist_basic",
            "watchlist_intelligence",
            "alerts_basic",
            "alerts_priority",
            "timeline_basic",
            "timeline_events",
            "morning_brief",
            "evidence_traceability",
            "thesis_memory",
            "api_access",
            "team_workspace",
            "custom_alert_rules",
            "data_export",
            "bulk_analysis",
        },
    ),
}

# ── Exceptions ─────────────────────────────────────────────────────────────────

class PlanGateError(Exception):
    """Raised when a feature requires a higher plan tier."""
    def __init__(self, feature: str, current_plan: str, required_plan: str):
        self.feature = feature
        self.current_plan = current_plan
        self.required_plan = required_plan
        super().__init__(
            f"Feature '{feature}' requires plan '{required_plan}' "
            f"(current: '{current_plan}')"
        )

class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""

# ── User/Workspace model ──────────────────────────────────────────────────────

@dataclass
class UserAccount:
    """Lightweight user account model. Populate from auth provider."""
    user_id: str
    email: str = ""
    plan: str = "free"
    workspace_id: Optional[str] = None
    # Usage tracking (in-memory for now; replace with Redis/DB)
    _daily_analysis_count: int = field(default=0, repr=False)

    def get_entitlements(self) -> PlanEntitlements:
        return _PLANS.get(self.plan, _PLANS["free"])

    def increment_analysis_count(self) -> None:
        self._daily_analysis_count += 1

    def analysis_limit_reached(self) -> bool:
        ents = self.get_entitlements()
        if ents.max_analyses_per_day == 0:
            return False  # unlimited
        return self._daily_analysis_count >= ents.max_analyses_per_day

@dataclass
class Workspace:
    """Team workspace for institutional plan."""
    workspace_id: str
    name: str
    owner_user_id: str
    member_user_ids: List[str] = field(default_factory=list)
    plan: str = "institutional"

# ── Feature Gate ──────────────────────────────────────────────────────────────

class FeatureGate:
    """
    Checks plan entitlements for a user.

    In stub mode (no user provided), all features pass.
    Wire to real auth by passing a UserAccount.
    """

    def __init__(
        self,
        user: Optional[UserAccount] = None,
        stub_mode: bool = True,  # True = bypass all gates (dev mode)
    ):
        self._user = user
        self._stub_mode = stub_mode

    def check(self, feature: str) -> bool:
        """Return True if the user has access to *feature*."""
        if self._stub_mode:
            return True
        if self._user is None:
            return False
        ents = self._user.get_entitlements()
        return feature in ents.features

    def require(self, feature: str) -> None:
        """Raise PlanGateError if the user cannot access *feature*."""
        if self._stub_mode:
            return
        if not self.check(feature):
            plan = self._user.plan if self._user else "anonymous"
            # Find the minimum plan that has this feature
            for plan_name in ("free", "pro", "institutional"):
                if feature in _PLANS[plan_name].features:
                    raise PlanGateError(feature, plan, plan_name)
            raise PlanGateError(feature, plan, "institutional")

    def check_rate_limit(self) -> bool:
        """Return True if the user is within their rate limit."""
        if self._stub_mode:
            return True
        if self._user is None:
            return False
        ents = self._user.get_entitlements()
        # Actual RPM tracking would use Redis; stub always passes
        return True

# ── Module-level default gate (stub mode for development) ──────────────────────
default_gate = FeatureGate(stub_mode=True)

def get_gate(user: Optional[UserAccount] = None) -> FeatureGate:
    """Factory: returns a configured FeatureGate for a user."""
    if user is None:
        return default_gate
    return FeatureGate(user=user, stub_mode=False)
