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
  cryptographically (HS256 with the Supabase JWT secret, or RS256 via JWKS
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
import time
from typing import Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
# JWKS cache (simple in-memory, 1-hour TTL)
# ---------------------------------------------------------------------------
_jwks_cache: Optional[Dict] = None
_jwks_fetched_at: float = 0.0
_JWKS_TTL_S: float = 3600.0


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


async def _fetch_jwks(project_url: str) -> Optional[Dict]:
    """Fetch Supabase JWKS from the well-known endpoint (cached 1h)."""
    global _jwks_cache, _jwks_fetched_at

    now = time.monotonic()
    if _jwks_cache is not None and (now - _jwks_fetched_at) < _JWKS_TTL_S:
        return _jwks_cache

    jwks_url = f"{project_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            data = resp.json()
            _jwks_cache = data
            _jwks_fetched_at = now
            logger.info("[auth] JWKS refreshed from %s", jwks_url)
            return data
    except Exception as exc:
        logger.warning("[auth] JWKS fetch failed from %s: %r", jwks_url, exc)
        return _jwks_cache  # return stale cache rather than failing closed


async def _verify_jwt_rs256(token: str, project_url: str, audience: str) -> Optional[Dict]:
    """Verify an RS256 JWT via the Supabase JWKS endpoint."""
    if not _JWT_AVAILABLE or not _pyjwt:
        return None

    jwks_data = await _fetch_jwks(project_url)
    if not jwks_data:
        return None

    try:
        # Use PyJWT's JWKS client to find the matching key by 'kid'
        jwks_client = _pyjwt.PyJWKClient.__new__(_pyjwt.PyJWKClient)  # type: ignore[attr-defined]
    except AttributeError:
        # Older PyJWT versions without PyJWKClient — fall through to HS256
        return None

    try:
        from jwt import PyJWKClient as _PyJWKClient  # type: ignore[attr-defined]

        jwks_url = f"{project_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        client = _PyJWKClient(jwks_url, cache_keys=True, lifespan=int(_JWKS_TTL_S))
        signing_key = client.get_signing_key_from_jwt(token)
        payload: Dict = _pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            options={"verify_exp": True},
        )
        return payload
    except Exception as exc:
        logger.debug("[auth] RS256 verification failed: %r", exc)
        return None


async def _verify_token(token: str) -> Optional[Dict]:
    """Try HS256 first (Supabase default), then RS256 (JWKS-based).

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

    # RS256 path: use JWKS when project URL is set but no secret
    if _settings.supabase_project_url:
        return await _verify_jwt_rs256(
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

    return sub, sub, True


# ---------------------------------------------------------------------------
# Middleware class
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that stamps user identity onto request.state.

    Never raises.  If resolution fails for any reason, falls back to the
    bypass identity so the request always reaches the route handler.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            user_id, auth_subject, is_authenticated = await _resolve_identity(request)
        except Exception as exc:
            logger.warning("[auth] _resolve_identity raised (non-fatal): %r", exc)
            from app.config import settings as _s
            user_id = _s.auth_bypass_user_id
            auth_subject = None
            is_authenticated = False

        request.state.user_id = user_id
        request.state.auth_subject = auth_subject
        request.state.is_authenticated = is_authenticated

        return await call_next(request)
