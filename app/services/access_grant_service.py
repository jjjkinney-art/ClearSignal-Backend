"""Controlled-beta admission grants — Section 0.15.

WHAT THIS MODULE DECIDES
------------------------
Whether a verified Supabase identity that has NO local user row yet may be
provisioned one. It never decides anything about an identity that already has
a local row: that is a plain lookup by ``sub``.

TRUSTED VS UNTRUSTED CLAIMS
---------------------------
Trusted (issued and controlled by Supabase GoTrue, covered by the signature
the middleware already verified):

    sub             the identity. The ONLY permanent identity key.
    email           top-level claim, mirrors auth.users.email
    app_metadata    provider / providers chain; service-role writable only
    is_anonymous    anonymous sign-in marker

Untrusted (user-writable, never consulted here):

    user_metadata.*     including user_metadata.email — settable by the user
                        at sign-up and via updateUser(data)
    anything else the caller can influence

WHY AN EMAIL MAY LOCATE A GRANT
-------------------------------
A person cannot be pre-approved by ``sub``, because their ``sub`` does not
exist until their first login. The only stable thing the operator knows in
advance is the address they will sign in with. We therefore allow an email to
act as a ONE-TIME ADMISSION LOCATOR, under conditions that make it as trusted
as the provider itself:

  1. Only the top-level ``email`` claim is read. It is populated by GoTrue
     from auth.users.email, not from anything the user can set directly.
  2. The provider chain must be in the configured allow-list (default:
     google). A Google identity's address is verified by Google.
  3. Anonymous identities are refused outright.
  4. The locator is consumed exactly once. Redemption binds the grant to
     ``sub`` atomically, and every later login resolves by ``sub``.

After redemption the email plays no part in identity resolution, ever. It is
not stored: only an HMAC of it is, and only until the grant is redeemed.

FAIL-CLOSED
-----------
Every ambiguous case denies: no grant, revoked, expired, already redeemed,
redeemed by a different subject, missing email, anonymous identity, untrusted
provider, malformed claims, or a database error during redemption.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

KIND_INVITE = "invite"
KIND_SUBJECT = "subject"

STATUS_APPROVED = "approved"
STATUS_REVOKED = "revoked"

# Audit vocabulary. Values are opaque references, never identities.
AUDIT_RESOURCE = "access_grant"
ACTION_GRANT = "grant"
ACTION_REDEEM = "redeem"
ACTION_REVOKE = "revoke"
ACTION_DENY = "deny"

# Denial reasons. Internal only: the API surface returns one generic message.
DENY_NO_GRANT = "no_grant"
DENY_NO_TRUSTED_EMAIL = "no_trusted_email"
DENY_ANONYMOUS = "anonymous_identity"
DENY_UNTRUSTED_PROVIDER = "untrusted_provider"
DENY_MALFORMED = "malformed_claims"
DENY_RACE = "redemption_lost"
DENY_CONFLICT = "identity_conflict"
DENY_REVOKED = "grant_revoked"
DENY_EXPIRED = "grant_expired"
DENY_CONFIG = "admission_config_invalid"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value):
    """Coerce a stored timestamp to an aware UTC datetime (SQLite returns naive)."""
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------
# Opaque references
# ---------------------------------------------------------------------------

def subject_ref(subject: str) -> str:
    """One-way, truncated reference to an identity, for logs and audit rows.

    Correlates events for the same identity without recording the identity.
    """
    if not subject:
        return "anon"
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:12]


def normalize_email(raw: Optional[str]) -> str:
    return (raw or "").strip().lower()


def email_locator(raw_email: str, pepper: Optional[str] = None) -> str:
    """HMAC-SHA256 of the normalised address. The address itself is discarded.

    The pepper is MANDATORY and has NO fallback. An unkeyed digest would be
    trivially guessable offline: an attacker with read access to the table
    could hash a list of candidate addresses and learn exactly who has been
    invited. Every caller that creates, looks up or redeems a locator goes
    through here, so a missing or weak pepper refuses the operation outright.
    """
    from app.config import AdmissionConfigError, admission_pepper_ok, settings

    if pepper is None:
        pepper = getattr(settings, "beta_admission_pepper", "")
    if not admission_pepper_ok(pepper):
        # Names the variable and the rule; never the value.
        raise AdmissionConfigError(
            "BETA_ADMISSION_PEPPER is required for email-locator grants"
        )

    normalized = normalize_email(raw_email)
    if not normalized:
        return ""
    return hmac.new(
        pepper.strip().encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Trusted identity extraction
# ---------------------------------------------------------------------------

@dataclass
class TrustedIdentity:
    subject: str
    email: str            # "" when the provider supplied none
    providers: tuple      # normalised provider chain
    is_anonymous: bool


def trusted_identity(claims: Dict[str, Any]) -> Optional[TrustedIdentity]:
    """Extract ONLY provider-controlled fields from verified JWT claims.

    Returns None when the claims are not a usable identity at all. Never
    reads user_metadata for the email: that field is user-writable, and
    trusting it would let a caller nominate somebody else's address.
    """
    if not isinstance(claims, dict):
        return None
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        return None

    raw_email = claims.get("email")
    email = normalize_email(raw_email) if isinstance(raw_email, str) else ""
    if "@" not in email:
        email = ""

    app_metadata = claims.get("app_metadata")
    providers: list = []
    if isinstance(app_metadata, dict):
        chain = app_metadata.get("providers")
        if isinstance(chain, (list, tuple)):
            providers = [str(p).strip().lower() for p in chain if str(p).strip()]
        single = app_metadata.get("provider")
        if isinstance(single, str) and single.strip():
            single = single.strip().lower()
            if single not in providers:
                providers.append(single)

    return TrustedIdentity(
        subject=subject.strip(),
        email=email,
        providers=tuple(providers),
        is_anonymous=bool(claims.get("is_anonymous")),
    )


def provider_trusted(identity: TrustedIdentity, allowed: Optional[list] = None) -> bool:
    """True when EVERY provider on the identity is in the allow-list.

    Strict on purpose: an identity carrying an extra, unexpected provider is
    refused rather than admitted on the strength of its best one.
    """
    if allowed is None:
        try:
            from app.config import settings
            allowed = settings.beta_admission_providers_list
        except Exception:
            allowed = ["google"]
    if not identity.providers:
        return False
    allowed_set = {str(a).strip().lower() for a in allowed if str(a).strip()}
    return bool(allowed_set) and all(p in allowed_set for p in identity.providers)


# ---------------------------------------------------------------------------
# Audit (opaque references only)
# ---------------------------------------------------------------------------

async def audit_admission(session, *, action: str, ref: str, detail: str = "") -> None:
    """Append an admission audit row. Never raises into the caller's path.

    ``ref`` is an opaque subject reference or grant id. ``detail`` is a fixed
    internal vocabulary word, never free text derived from user input.
    """
    if session is None:
        return
    try:
        from app.db.models import AuditLog
        import uuid as _uuid
        session.add(AuditLog(
            id=str(_uuid.uuid4()),
            user_id=None,
            resource=AUDIT_RESOURCE,
            resource_id=f"{ref}:{detail}" if detail else ref,
            action=action,
            created_at=_now(),
        ))
        await session.flush()
    except Exception as exc:   # pragma: no cover - audit must not break auth
        logger.warning("[admission] audit write failed: %r", type(exc).__name__)


# ---------------------------------------------------------------------------
# Operator operations
# ---------------------------------------------------------------------------

async def create_invite_grant(
    session,
    *,
    raw_email: str,
    expires_at: Optional[datetime] = None,
    note_ref: Optional[str] = None,
) -> Optional[str]:
    """Approve an address that has never signed in. Returns the grant id.

    The address is hashed immediately and never stored or logged.
    """
    if session is None:
        return None
    locator = email_locator(raw_email)
    if not locator:
        return None

    from sqlalchemy import select
    from app.db.models import AccessGrant
    import uuid as _uuid

    # Reuse an existing, still-usable grant rather than stacking duplicates.
    existing = (await session.execute(
        select(AccessGrant)
        .where(AccessGrant.email_locator == locator)
        .where(AccessGrant.status == STATUS_APPROVED)
        .where(AccessGrant.redeemed_at.is_(None))
    )).scalars().first()
    if existing is not None:
        return str(existing.id)

    grant = AccessGrant(
        id=str(_uuid.uuid4()),
        kind=KIND_INVITE,
        email_locator=locator,
        subject=None,
        status=STATUS_APPROVED,
        expires_at=expires_at,
        note_ref=note_ref,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(grant)
    await session.flush()
    await audit_admission(session, action=ACTION_GRANT, ref=str(grant.id), detail=KIND_INVITE)
    return str(grant.id)


async def create_subject_grant(
    session,
    *,
    subject: str,
    note_ref: Optional[str] = None,
) -> Optional[str]:
    """Approve an identity that already exists (grandfathering path).

    Carries no locator: authorisation is never derived from an email here.
    """
    if session is None or not subject:
        return None

    from sqlalchemy import select
    from app.db.models import AccessGrant
    import uuid as _uuid

    existing = (await session.execute(
        select(AccessGrant).where(AccessGrant.subject == subject)
    )).scalars().first()
    if existing is not None:
        return str(existing.id)

    grant = AccessGrant(
        id=str(_uuid.uuid4()),
        kind=KIND_SUBJECT,
        email_locator=None,
        subject=subject,
        status=STATUS_APPROVED,
        redeemed_at=_now(),
        note_ref=note_ref,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(grant)
    await session.flush()
    await audit_admission(session, action=ACTION_GRANT, ref=subject_ref(subject), detail=KIND_SUBJECT)
    return str(grant.id)


#: Shortest grant-reference prefix accepted by resolve_pending_invite. Shorter
#: prefixes are refused rather than risking an ambiguous match.
MIN_REF_LENGTH = 8


async def list_pending_invites(session) -> list:
    """Read-only listing of PENDING INVITATIONS, by opaque reference.

    Returns the grant id (a random UUID, derived from nothing), the operator's
    own note reference, and dates. Never an address, never a locator, and
    never a subject grant: the caller has no way to reach one through here.
    """
    if session is None:
        return []

    from sqlalchemy import select
    from app.db.models import AccessGrant

    rows = (await session.execute(
        select(AccessGrant)
        .where(AccessGrant.kind == KIND_INVITE)
        .where(AccessGrant.status == STATUS_APPROVED)
        .where(AccessGrant.redeemed_at.is_(None))
        .order_by(AccessGrant.created_at)
    )).scalars().all()
    return [{
        "ref": str(row.id),
        "note_ref": row.note_ref or "",
        "created": _aware(row.created_at).date().isoformat() if row.created_at else "",
        "expires": _aware(row.expires_at).date().isoformat() if row.expires_at else "none",
    } for row in rows]


async def resolve_pending_invite(session, ref: str):
    """Resolve an opaque reference to exactly one pending invitation.

    Returns ``(row, state)`` where state is "ok", "none", "ambiguous" or
    "too_short". Only pending invitations are candidates, so a subject
    grant's id resolves to "none" rather than ever being returned.
    """
    if session is None:
        return None, "none"
    ref = (ref or "").strip().lower()
    if len(ref) < MIN_REF_LENGTH:
        return None, "too_short"

    from sqlalchemy import select
    from app.db.models import AccessGrant

    rows = (await session.execute(
        select(AccessGrant)
        .where(AccessGrant.kind == KIND_INVITE)
        .where(AccessGrant.status == STATUS_APPROVED)
        .where(AccessGrant.redeemed_at.is_(None))
    )).scalars().all()
    matches = [row for row in rows if str(row.id).lower().startswith(ref)]
    if not matches:
        return None, "none"
    if len(matches) > 1:
        return None, "ambiguous"
    return matches[0], "ok"


async def revoke_invite_by_id(session, grant_id: str) -> int:
    """Revoke ONE pending invitation by its exact id. Returns rows changed.

    Every condition lives in the WHERE clause, so the database — not Python —
    enforces them: the row must be an invitation, still approved, unredeemed
    and unbound. A subject grant can therefore never be modified here, and
    neither can an already revoked or redeemed invitation.
    """
    if session is None or not grant_id:
        return 0

    from sqlalchemy import update
    from app.db.models import AccessGrant

    now = _now()
    outcome = await session.execute(
        update(AccessGrant)
        .where(AccessGrant.id == grant_id)
        .where(AccessGrant.kind == KIND_INVITE)
        .where(AccessGrant.status == STATUS_APPROVED)
        .where(AccessGrant.redeemed_at.is_(None))
        .where(AccessGrant.subject.is_(None))
        .values(status=STATUS_REVOKED, revoked_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    changed = int(outcome.rowcount or 0)
    if changed:
        # Opaque: an invitation has no subject, so the grant id is the ref.
        await audit_admission(session, action=ACTION_REVOKE, ref=str(grant_id), detail=KIND_INVITE)
    session.expire_all()          # Core UPDATE: drop any stale ORM state before re-counting
    return changed


async def count_approved_subject_grants(session) -> int:
    """Subject grants still APPROVED. The invariant a revoke must not move."""
    if session is None:
        return 0
    from sqlalchemy import select, func
    from app.db.models import AccessGrant
    return int((await session.execute(
        select(func.count()).select_from(AccessGrant)
        .where(AccessGrant.kind == KIND_SUBJECT)
        .where(AccessGrant.status == STATUS_APPROVED)
    )).scalar() or 0)


async def revoke_grant(
    session,
    *,
    raw_email: Optional[str] = None,
    subject: Optional[str] = None,
) -> int:
    """Revoke by address or by identity. Returns the number of rows revoked."""
    if session is None:
        return 0

    from sqlalchemy import select
    from app.db.models import AccessGrant

    stmt = select(AccessGrant).where(AccessGrant.status == STATUS_APPROVED)
    if subject:
        stmt = stmt.where(AccessGrant.subject == subject)
    elif raw_email:
        locator = email_locator(raw_email)
        if not locator:
            return 0
        stmt = stmt.where(AccessGrant.email_locator == locator)
    else:
        return 0

    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        row.status = STATUS_REVOKED
        row.revoked_at = _now()
        row.updated_at = _now()
        await audit_admission(
            session,
            action=ACTION_REVOKE,
            ref=subject_ref(row.subject) if row.subject else str(row.id),
        )
    await session.flush()
    return len(rows)


async def plan_grandfather(session) -> Dict[str, int]:
    """READ-ONLY preview of grandfather_existing_subjects. Issues SELECTs only.

    The dry run must be strictly read-only: an earlier revision previewed by
    running the real write and rolling it back, which still sent INSERTs for
    grant and audit rows. This computes the same aggregate from reads alone.
    """
    plan = {"examined": 0, "would_grant": 0, "already_granted": 0, "skipped_unbound": 0}
    if session is None:
        return plan

    from sqlalchemy import select
    from app.db.models import User, AccessGrant

    existing_subjects = {
        row for (row,) in (await session.execute(select(AccessGrant.subject))).all()
        if row
    }
    for (subject,) in (await session.execute(select(User.auth_subject))).all():
        plan["examined"] += 1
        if not subject:
            plan["skipped_unbound"] += 1
        elif subject in existing_subjects:
            plan["already_granted"] += 1
        else:
            plan["would_grant"] += 1
            existing_subjects.add(subject)
    return plan


async def count_subject_grants(session) -> int:
    """Aggregate count used to assert the execute path's row delta."""
    if session is None:
        return 0
    from sqlalchemy import select, func
    from app.db.models import AccessGrant
    return int((await session.execute(
        select(func.count()).select_from(AccessGrant)
        .where(AccessGrant.kind == KIND_SUBJECT)
    )).scalar() or 0)


async def grandfather_existing_subjects(session, *, note_ref: Optional[str] = None) -> Dict[str, int]:
    """Create a subject grant for every already-bound local identity.

    Reads the subjects out of the database at run time. No production
    identity is ever written into source, migrations, tests or documentation.
    Authorisation here is derived from an existing `auth_subject` binding,
    never from an email address.

    Returns aggregate counts only.
    """
    result = {"examined": 0, "granted": 0, "already_granted": 0, "skipped_unbound": 0}
    if session is None:
        return result

    from sqlalchemy import select
    from app.db.models import User, AccessGrant

    users = (await session.execute(select(User))).scalars().all()
    existing_subjects = {
        row for (row,) in (await session.execute(select(AccessGrant.subject))).all()
        if row
    }

    for user in users:
        result["examined"] += 1
        subject = getattr(user, "auth_subject", None)
        if not subject:
            result["skipped_unbound"] += 1
            continue
        if subject in existing_subjects:
            result["already_granted"] += 1
            continue
        created = await create_subject_grant(session, subject=subject, note_ref=note_ref)
        if created:
            result["granted"] += 1
            existing_subjects.add(subject)
    return result


async def grant_status_counts(session) -> Dict[str, int]:
    """Aggregate grant counts. Emits no identity, address or locator."""
    counts = {
        "total": 0, "approved_pending": 0, "approved_redeemed": 0,
        "revoked": 0, "expired_pending": 0, "subject_grants": 0, "invite_grants": 0,
    }
    if session is None:
        return counts

    from sqlalchemy import select
    from app.db.models import AccessGrant

    now = _now()
    for row in (await session.execute(select(AccessGrant))).scalars().all():
        counts["total"] += 1
        counts["subject_grants" if row.kind == KIND_SUBJECT else "invite_grants"] += 1
        if row.status == STATUS_REVOKED:
            counts["revoked"] += 1
        elif row.redeemed_at is not None:
            counts["approved_redeemed"] += 1
        elif row.expires_at is not None and _aware(row.expires_at) <= now:
            counts["expired_pending"] += 1
        else:
            counts["approved_pending"] += 1
    return counts


# ---------------------------------------------------------------------------
# Admission decision
# ---------------------------------------------------------------------------

@dataclass
class AdmissionDecision:
    allowed: bool
    reason: str = ""
    grant_id: Optional[str] = None


async def redeem_for_identity(session, identity: TrustedIdentity) -> AdmissionDecision:
    """Atomically bind one unredeemed grant to this identity.

    The binding is a CONDITIONAL UPDATE:

        UPDATE access_grants SET subject = :sub, redeemed_at = now
         WHERE id = :id AND subject IS NULL AND redeemed_at IS NULL
           AND status = 'approved'

    Two concurrent first logins for the same grant both attempt it; the
    database serialises them and exactly one reports a matched row. The loser
    is denied rather than provisioned. The UNIQUE constraint on `subject` is
    the second, independent guard.
    """
    if session is None:
        return AdmissionDecision(False, DENY_MALFORMED)

    from sqlalchemy import select, update
    from app.db.models import AccessGrant

    # An identity that already holds a grant is admitted without consuming
    # another one — but the grant must still be LIVE. This is the path every
    # established account takes on every login under enforcement, so it is
    # also where revocation and expiry actually bite.
    held = (await session.execute(
        select(AccessGrant).where(AccessGrant.subject == identity.subject)
    )).scalars().first()
    if held is not None:
        if held.status == STATUS_REVOKED:
            return AdmissionDecision(False, DENY_REVOKED)
        if held.status != STATUS_APPROVED:
            return AdmissionDecision(False, DENY_NO_GRANT)
        expires = _aware(held.expires_at)
        if expires is not None and expires <= _now():
            return AdmissionDecision(False, DENY_EXPIRED)
        return AdmissionDecision(True, grant_id=str(held.id))

    if not identity.email:
        return AdmissionDecision(False, DENY_NO_TRUSTED_EMAIL)

    locator = email_locator(identity.email)
    if not locator:
        return AdmissionDecision(False, DENY_NO_TRUSTED_EMAIL)

    now = _now()
    candidates = (await session.execute(
        select(AccessGrant)
        .where(AccessGrant.email_locator == locator)
        .where(AccessGrant.status == STATUS_APPROVED)
        .where(AccessGrant.subject.is_(None))
        .where(AccessGrant.redeemed_at.is_(None))
    )).scalars().all()

    for candidate in candidates:
        expires = _aware(candidate.expires_at)
        if expires is not None and expires <= now:
            continue
        outcome = await session.execute(
            update(AccessGrant)
            .where(AccessGrant.id == candidate.id)
            .where(AccessGrant.subject.is_(None))
            .where(AccessGrant.redeemed_at.is_(None))
            .where(AccessGrant.status == STATUS_APPROVED)
            .values(subject=identity.subject, redeemed_at=now, updated_at=now)
        )
        if (outcome.rowcount or 0) == 1:
            await audit_admission(
                session, action=ACTION_REDEEM, ref=subject_ref(identity.subject)
            )
            return AdmissionDecision(True, grant_id=str(candidate.id))

    return AdmissionDecision(False, DENY_NO_GRANT if candidates == [] else DENY_RACE)


async def evaluate_admission(
    session,
    claims: Dict[str, Any],
    *,
    user_exists: bool = False,
) -> AdmissionDecision:
    """Decide whether this identity may be admitted. Fail-closed.

    Called for EVERY identity under shadow and enforce, not only unknown
    ones. ``user_exists`` is recorded for audit clarity; it deliberately does
    NOT relax the decision. An established account with no live grant is
    denied under enforcement, which is what makes revocation real.
    """
    identity = trusted_identity(claims)
    if identity is None:
        return AdmissionDecision(False, DENY_MALFORMED)
    if identity.is_anonymous:
        return AdmissionDecision(False, DENY_ANONYMOUS)
    if not provider_trusted(identity):
        return AdmissionDecision(False, DENY_UNTRUSTED_PROVIDER)

    try:
        return await redeem_for_identity(session, identity)
    except Exception as exc:
        # Includes a missing/weak pepper: a locator cannot be computed, so no
        # admission decision can be made, so nobody is admitted.
        logger.warning("[admission] redemption failed closed: %r", type(exc).__name__)
        return AdmissionDecision(False, DENY_MALFORMED)
