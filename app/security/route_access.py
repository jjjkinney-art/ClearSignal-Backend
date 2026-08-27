"""Central launch access policy for protected and operator-only routes.

Legacy routers predate authentication and cannot safely rely on every handler
remembering its own dependency.  This policy runs after JWT resolution and
before route work, providing one auditable boundary for the production API.
"""
from __future__ import annotations

from fastapi import HTTPException
from starlette.requests import Request

from ..dependencies.auth import require_user_id
from .authz import require_admin


# Deliberately small public surface.  Product and intelligence routes are
# authenticated by default so a newly-added legacy handler cannot accidentally
# become anonymous.  Individual auth handlers still decide what session data
# they return; this allowlist only permits the request to reach them.
PUBLIC_PATHS = frozenset(
    {
        "/",
        "/docs",
        "/docs/oauth2-redirect",
        "/health",
        "/healthz",
        "/openapi.json",
        "/readyz",
        "/redoc",
        "/version",
        "/billing/webhook",
    }
)
PUBLIC_PREFIXES = ("/auth/",)

# Internal mutation surfaces are operator-only even though they live outside
# the historical /admin namespace.
ADMIN_ROUTES = frozenset(
    {
        ("POST", "/events/ingest"),
        ("POST", "/events/process"),
        ("POST", "/pipeline/run"),
    }
)


def normalized_route(request: Request) -> tuple[str, str]:
    path = request.url.path.rstrip("/") or "/"
    return request.method.upper(), path


def requires_admin(request: Request) -> bool:
    method, path = normalized_route(request)
    return path == "/admin" or path.startswith("/admin/") or (method, path) in ADMIN_ROUTES


def requires_authentication(request: Request) -> bool:
    method, path = normalized_route(request)
    if method == "OPTIONS":
        return False
    if path in PUBLIC_PATHS or any(
        path.startswith(prefix) for prefix in PUBLIC_PREFIXES
    ):
        return False
    return not requires_admin(request)


def enforce_route_access(request: Request) -> str | None:
    """Return the acting identity or raise a truthful 401/403 before routing."""
    if requires_admin(request):
        return require_admin(request)
    if requires_authentication(request):
        return require_user_id(request)
    return None


def access_denied_response(exc: HTTPException) -> tuple[int, dict[str, str]]:
    """Small pure helper used by middleware and unit tests."""
    return exc.status_code, {"detail": str(exc.detail)}
