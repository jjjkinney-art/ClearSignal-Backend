"""
JWT verification middleware — Phase 16 · Slice 3.

Resolves the identity of every incoming request and stamps three attributes
onto request.state before the route handler runs:

    request.state.user_id        str | None  — the acting user's ID
    request.state.auth_subject   str | None  — Supabase JWT 'sub' claim
    request.state.is_authenticated bool      — True only for verified JWTs

Bypass mode (AUTH_ENABLED=false — the default for all Phase 16 build slices)
  Every request resolves to SYSTEM_DEFAULT_USER_ID with is_authenticated=False.
  No JWT is parsed, no network call is made, no DB is read.
  Production behaviour is identical to the pre-16 single-user system.

Enforcement mode (AUTH_ENABLED=true — PART 7 rollout only)
  Extracts the bearer token from the Authorization header and verifies it
  cryptographically (HS256 with the legacy Supabase JWT secret, or an
  asymmetric RS256/ES256 signing key via JWKS
  if supabase_jwt_secret is empty and supabase_project_url is configured).
  Sets is_authenticated=True only for a fully valid, non-expired token with
  the correct audience claim.  Invalid / absent tokens set user_id=None and
  is_authenticated=False — route protection (401) is handled by the
  require_auth dependency (Slice 5), not by this middleware.

No-password guarantee
  This module never reads, writes, or validates any credential.
  It only verifies a cryptographic signature on a token Supabase issued.

PyJWT dependency
  JWT verification requires PyJWT >= 2.8.0 (in requirements.txt).
  When PyJWT is unavailable and AUTH_ENABLED=true, all requests are treated
  as unauthenticated and a startup warning is emitted.  AUTH_ENABLED=false
  (the safe default) works without PyJWT installed.
"""

from __future__ import annotations

import logging
import asyncio
from typing import Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level JWT library detection
# ---------------------------------------------------------------------------
try:
    import jwt as _pyjwt                                  # PyJWT >= 2.8.0
    _JWT_AVAILABLE = True
except ImportError:                                        # pragma: no cover
    _pyjwt = None  # type: ignore[assignment]
    _JWT_AVAILABLE = False
    logger.warning(
        "[auth] PyJWT not installed; JWT verification unavailable. "
        "Install PyJWT>=2.8.0 (in requirements.txt) before enabling AUTH_ENABLED=true."
    )

# ---------------------------------------------------------------------------
# JWKS cache lifetime used by PyJWT's client. Supabase edge caches the endpoint
# for ten minutes, so matching that interval avoids holding rotated keys longer.
# ---------------------------------------------------------------------------
_JWKS_TTL_S: float = 600.0
_jwks_clients: Dict[str, object] = {}


# ---------------------------------------------------------------------------
# JWT helpers — internal, patched in tests
# ---------------------------------------------------------------------------

def _extract_bearer_token(request: Request) -> Optional[str]:
    """Return the bearer token from the Authorization header, or None."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        return token if token else None
    return None


def _verify_jwt_hs256(token: str, secret: str, audience: str) -> Optional[Dict]:
    """Verify an HS256 JWT using the Supabase JWT secret.

    Returns the decoded payload on success, or None on any failure
    (expired, wrong audience, bad signature, malformed).
    """
    if not _JWT_AVAILABLE or not _pyjwt:
        return None
    if not secret:
        logger.warning("[auth] supabase_jwt_secret is empty; HS256 verification disabled")
        return None

    try:
        payload: Dict = _pyjwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            options={"verify_exp": True, "require": ["sub", "exp", "aud"]},
        )
        return payload
    except _pyjwt.ExpiredSignatureError:
        logger.debug("[auth] JWT rejected: expired")
        return None
    except _pyjwt.InvalidAudienceError:
        logger.debug("[auth] JWT rejected: wrong audience")
        return None
    except _pyjwt.InvalidSignatureError:
        logger.debug("[auth] JWT rejected: bad signature")
        return None
    except _pyjwt.DecodeError:
        logger.debug("[auth] JWT rejected: malformed token")
        return None
    except Exception as exc:
        logger.debug("[auth] JWT rejected: %r", exc)
        return None


async def _verify_jwt_asymmetric(
    token: str,
    project_url: str,
    audience: str,
) -> Optional[Dict]:
    """Verify a Supabase RS256 or ES256 JWT via its JWKS endpoint.

    The token header selects the signing key, but never the allowed algorithm:
    only Supabase's supported asymmetric algorithms are accepted.  Issuer,
    audience, expiry, and subject are all required and verified.
    """
    if not _JWT_AVAILABLE or not _pyjwt:
        return None

    try:
        algorithm = _pyjwt.get_unverified_header(token).get("alg")
    except Exception as exc:
        logger.debug("[auth] asymmetric JWT header rejected: %r", exc)
        return None

    if algorithm not in {"RS256", "ES256"}:
        logger.debug("[auth] asymmetric JWT rejected: unsupported alg=%r", algorithm)
        return None

    try:
        jwks_url = f"{project_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        issuer = f"{project_url.rstrip('/')}/auth/v1"
        client = _jwks_clients.get(jwks_url)
        if client is None:
            client = _pyjwt.PyJWKClient(
                jwks_url,
                cache_keys=True,
                lifespan=int(_JWKS_TTL_S),
            )
            _jwks_clients[jwks_url] = client
        signing_key = await asyncio.to_thread(client.get_signing_key_from_jwt, token)
        payload: Dict = _pyjwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience=audience,
            issuer=issuer,
            options={"verify_exp": True, "require": ["sub", "exp", "aud", "iss"]},
        )
        return payload
    except Exception as exc:
        logger.debug("[auth] asymmetric JWT verification failed: %r", exc)
        return None


async def _verify_token(token: str) -> Optional[Dict]:
    """Use legacy HS256 when configured, otherwise Supabase JWKS verification.

    Returns the verified payload dict or None.
    """
    from app.config import settings as _settings

    # HS256 path: prefer when JWT secret is configured
    if _settings.supabase_jwt_secret:
        return _verify_jwt_hs256(
            token,
            _settings.supabase_jwt_secret,
            _settings.supabase_audience,
        )

    # Current Supabase projects use an asymmetric signing key (normally ES256).
    if _settings.supabase_project_url:
        return await _verify_jwt_asymmetric(
            token,
            _settings.supabase_project_url,
            _settings.supabase_audience,
        )

    logger.warning(
        "[auth] AUTH_ENABLED=true but neither supabase_jwt_secret nor "
        "supabase_project_url is configured — all requests unauthenticated"
    )
    return None


async def _resolve_identity(request: Request) -> Tuple[Optional[str], Optional[str], bool]:
    """Return (user_id, auth_subject, is_authenticated) for the request.

    Bypass mode (AUTH_ENABLED=false):
        → (SYSTEM_DEFAULT_USER_ID, None, False) always — no token inspection.

    Enforcement mode (AUTH_ENABLED=true):
        Valid JWT  → (sub, sub, True)
        No token   → (None, None, False)
        Bad token  → (None, None, False)
    """
    from app.config import settings as _settings

    if not _settings.auth_enabled:
        return _settings.auth_bypass_user_id, None, False

    # Enforcement path — only reached when AUTH_ENABLED=true
    token = _extract_bearer_token(request)
    if token is None:
        return None, None, False

    payload = await _verify_token(token)
    if payload is None:
        return None, None, False

    sub = payload.get("sub")
    if not sub:
        return None, None, False

    # Preserve only the verified claims for first-login provisioning.  This is
    # internal request state and is never returned directly to clients.
    request.state.auth_claims = payload
    return sub, sub, True


async def _resolve_local_user_id(request: Request) -> Optional[str]:
    """Provision or resolve the local owner for verified JWT claims.

    The local ID can differ from the Supabase subject when an older local
    account is linked by email. Protected routes must therefore use the local
    ID returned here rather than assuming ``sub == users.id``.
    """
    claims = getattr(request.state, "auth_claims", None)
    if not isinstance(claims, dict):
        return None

    from app.db.connection import get_session
    from app.services.supabase_auth_service import resolve_user_from_jwt

    async with get_session() as session:
        if session is None:
            return None
        user = await resolve_user_from_jwt(session, claims)
        if user is None:
            return None
        await session.commit()
        return str(user.id)


# ---------------------------------------------------------------------------
# Middleware class
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that stamps user identity onto request.state.

    Never raises. Resolution failures retain the bypass identity only while
    auth is disabled; enforcement mode always fails closed.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.auth_claims = None
        try:
            user_id, auth_subject, is_authenticated = await _resolve_identity(request)
            if is_authenticated:
                user_id = await _resolve_local_user_id(request)
                if user_id is None:
                    auth_subject = None
                    is_authenticated = False
        except Exception as exc:
            logger.warning("[auth] _resolve_identity raised (non-fatal): %r", exc)
            from app.config import settings as _s
            user_id = _s.auth_bypass_user_id if not _s.auth_enabled else None
            auth_subject = None
            is_authenticated = False

        request.state.user_id = user_id
        request.state.auth_subject = auth_subject
        request.state.is_authenticated = is_authenticated

        # Identity-aware limits run here, after JWT resolution and before route
        # work.  The outer edge guard independently limits every IP, including
        # unauthenticated callers.  The shared bypass identity is deliberately
        # not treated as a real user bucket in local development.
        from app.config import settings as _s
        if _s.rate_limit_enabled:
            from app.dependencies.auth import SYSTEM_DEFAULT_USER_ID
            from app.security.rate_limit import (
                client_ip, is_exempt, is_expensive, log_denial, rate_limiter,
            )

            if not is_exempt(request):
                checks = []
                if is_authenticated and user_id and user_id != SYSTEM_DEFAULT_USER_ID:
                    checks.append((
                        f"user:{user_id}",
                        _s.rate_limit_per_user_per_min,
                        "global_user",
                    ))
                if is_expensive(request):
                    ip = client_ip(request, _s.rate_limit_trusted_proxy_hops)
                    checks.append((
                        f"expensive:ip:{ip}",
                        _s.rate_limit_expensive_per_ip_per_min,
                        "expensive_ip",
                    ))
                    if is_authenticated and user_id and user_id != SYSTEM_DEFAULT_USER_ID:
                        checks.append((
                            f"expensive:user:{user_id}",
                            _s.rate_limit_expensive_per_user_per_min,
                            "expensive_user",
                        ))

                for key, limit, scope in checks:
                    allowed, retry_after = rate_limiter.check(
                        key, limit, _s.rate_limit_window_s
                    )
                    if not allowed:
                        log_denial(
                            scope=scope, request=request, retry_after=retry_after
                        )
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Rate limit exceeded. Please slow down."},
                            headers={"Retry-After": str(retry_after)},
                        )

        return await call_next(request)
