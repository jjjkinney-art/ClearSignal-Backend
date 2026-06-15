"""
Entitlement Enforcement — Phase 17 · Slice 6.

Provides five check helpers that translate EntitlementSet limits/features
into HTTP 402 blocks.  All checks are no-ops when ENTITLEMENTS_ENFORCED=false
(the default throughout every Phase 17 build slice).

API:
    check_watchlist_limit(ent, current_usage) → None | raises EntitlementViolation
    check_portfolio_limit(ent, current_usage) → None | raises EntitlementViolation
    check_briefing_limit(ent, current_usage)  → None | raises EntitlementViolation
    check_delivery_limit(ent, current_usage)  → None | raises EntitlementViolation
    require_feature(ent, feature_name)        → None | raises EntitlementViolation

Callers convert EntitlementViolation → HTTPException(status_code=402) and
return the violation fields as the response body.

Safety contract:
    ENTITLEMENTS_ENFORCED=false → all helpers return None immediately.
    System user (SYSTEM_DEFAULT_USER_ID) always bypasses every check.
    Callers should wrap check calls in try/except Exception so any unexpected
    error is failure-open (never block a user due to enforcement code crashing).
"""

from __future__ import annotations

from typing import Optional

SYSTEM_DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

_UPGRADE_CTAS: dict = {
    "watchlist_limit":             "Upgrade to Signal for unlimited watchlist entries.",
    "portfolio_limit":             "Upgrade to Signal for up to 5 portfolios.",
    "briefing_limit":              "Upgrade to Signal for unlimited morning briefs.",
    "delivery_limit":              "Upgrade to Signal for additional delivery channels.",
    "can_use_portfolio_intelligence": "Upgrade to Signal to access Portfolio Intelligence.",
    "can_use_email_delivery":      "Upgrade to Signal to enable email delivery.",
    "can_use_push_delivery":       "Upgrade to Syndicate to enable push delivery.",
    "can_set_briefing_time":       "Upgrade to Signal to set a custom briefing time.",
    "can_use_custom_quiet_hours":  "Upgrade to Signal to set custom quiet hours.",
    "can_export_data":             "Upgrade to Signal to export your data.",
    "can_use_api":                 "Upgrade to Syndicate to access the API.",
    "can_use_org_features":        "Upgrade to Syndicate to access organisation features.",
    "has_unlimited_inbox":         "Upgrade to Signal for unlimited inbox history.",
}


class EntitlementViolation(Exception):
    """Raised when a user is blocked by an entitlement limit or feature gate.

    Callers convert this to HTTPException(402) and include the fields below
    as the JSON response body.
    """

    def __init__(
        self,
        entitlement: str,
        plan: str,
        limit: int,
        current_usage: int,
        upgrade_cta: str,
    ) -> None:
        super().__init__(f"Entitlement blocked: {entitlement} (plan={plan})")
        self.entitlement   = entitlement
        self.plan          = plan
        self.limit         = limit
        self.current_usage = current_usage
        self.upgrade_cta   = upgrade_cta

    def as_dict(self) -> dict:
        return {
            "entitlement":   self.entitlement,
            "plan":          self.plan,
            "limit":         self.limit,
            "current_usage": self.current_usage,
            "upgrade_cta":   self.upgrade_cta,
        }


def _enforcement_enabled() -> bool:
    from app.config import settings
    return settings.entitlements_enforced


def _is_system_user(ent) -> bool:
    return ent.user_id == SYSTEM_DEFAULT_USER_ID


def _limit_check(
    ent,
    field: str,
    current_usage: int,
) -> None:
    """Raise EntitlementViolation if current_usage >= limit (and limit != -1)."""
    if not _enforcement_enabled():
        return
    if _is_system_user(ent):
        return

    limit: int = getattr(ent, field, -1)
    if limit == -1:
        return  # unlimited

    if current_usage >= limit:
        cta = _UPGRADE_CTAS.get(field, "Upgrade to access more.")
        raise EntitlementViolation(
            entitlement=field,
            plan=ent.plan_name,
            limit=limit,
            current_usage=current_usage,
            upgrade_cta=cta,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_watchlist_limit(ent, current_usage: int) -> None:
    """Raise EntitlementViolation when the user has reached their watchlist cap.

    current_usage: number of tickers currently in the watchlist (before add).
    """
    _limit_check(ent, "watchlist_limit", current_usage)


def check_portfolio_limit(ent, current_usage: int) -> None:
    """Raise EntitlementViolation when the user has reached their portfolio cap.

    current_usage: number of portfolios currently owned by the user.
    """
    _limit_check(ent, "portfolio_limit", current_usage)


def check_briefing_limit(ent, current_usage: int) -> None:
    """Raise EntitlementViolation when the user has reached their weekly briefing cap.

    current_usage: number of briefings generated this week.
    Note: when no weekly counter is available, pass 0 (enforcement is fail-open).
    """
    _limit_check(ent, "briefing_limit", current_usage)


def check_delivery_limit(ent, current_usage: int) -> None:
    """Raise EntitlementViolation when the user has reached their delivery channel cap.

    current_usage: number of delivery channels currently active for the user.
    """
    _limit_check(ent, "delivery_limit", current_usage)


def require_feature(ent, feature_name: str) -> None:
    """Raise EntitlementViolation when the user's plan does not include a feature.

    feature_name: an EntitlementSet boolean field such as
        "can_use_portfolio_intelligence", "can_use_email_delivery", etc.
    """
    if not _enforcement_enabled():
        return
    if _is_system_user(ent):
        return

    if not getattr(ent, feature_name, False):
        cta = _UPGRADE_CTAS.get(feature_name, "Upgrade to access this feature.")
        raise EntitlementViolation(
            entitlement=feature_name,
            plan=ent.plan_name,
            limit=0,
            current_usage=0,
            upgrade_cta=cta,
        )
