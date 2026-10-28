"""Offline simulated-attempt accounting. Never grants native transport authority.

No reopen/resume API and no provider integration. Claims count permanently even
on failure. Durable halts prohibit new claims; late settlements are recorded as
late, never as publishable answers. Retention and physical fencing remain separate.
"""
import os
import hashlib
import math
import re
from pathlib import Path
from copy import deepcopy
import sqlite3
import time
from threading import RLock
from uuid import uuid4

from .ordinary_pilot_contract import quota_contract


class AccountingError(ValueError):
    pass


class OfflineAccounting:
    def __init__(self, path, *, clock=time.monotonic):
        self.path, self.clock = str(Path(path).absolute()), clock
        self.started = clock()
        self._policy = quota_contract()
        self._locally_sealed = False
        self._seal_lock = RLock()
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        stat = os.fstat(fd)
        self._file_identity = (stat.st_dev, stat.st_ino)
        os.close(fd)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE state (halt TEXT NOT NULL);
                INSERT INTO state VALUES ('');
                CREATE TABLE cleanup_failures (code TEXT NOT NULL);
                CREATE TABLE fixture_dispatches (attempt_id TEXT PRIMARY KEY, dispatched_at REAL NOT NULL);
                CREATE TABLE bodies (attempt_id TEXT PRIMARY KEY, sha256 TEXT, body BLOB NOT NULL);
                CREATE TABLE fixture_receipts (attempt_id TEXT PRIMARY KEY, url TEXT NOT NULL,
                    media_type TEXT NOT NULL, http_status INTEGER NOT NULL);
                CREATE TABLE attempts (id TEXT PRIMARY KEY, case_id TEXT, stage TEXT,
                    route TEXT, outcome TEXT NOT NULL DEFAULT 'pending', request_sha256 TEXT);
            ''')

    def _check_identity(self):
        try:
            stat = os.stat(self.path, follow_symlinks=False)
        except OSError:
            self.seal_local()
            raise AccountingError('fixture ledger unavailable; no reset') from None
        if (stat.st_dev, stat.st_ino) != self._file_identity:
            self.seal_local()
            raise AccountingError('fixture ledger replaced; no reset')

    def _connect(self):
        """Open only the original file; never recreate a missing ledger."""
        self._check_identity()
        return sqlite3.connect(Path(self.path).as_uri() + '?mode=rw', uri=True, timeout=10)

    @property
    def policy(self):
        return deepcopy(self._policy)

    def seal_local(self):
        """Refuse further work even when durable cleanup storage is unavailable."""
        with self._seal_lock:
            self._locally_sealed = True

    def _case_reason(self, db, case, now):
        """Called inside each operation's write transaction, not a precheck."""
        if not getattr(self, '_lifecycle_required', False):
            return ''  # isolated component rehearsals without a run lifecycle
        row = db.execute("SELECT started FROM case_lifecycle WHERE case_id=? AND status='running'", (case,)).fetchone()
        if not row:
            return 'case_not_active'
        if not math.isfinite(now) or now < row[0] or now < self.started:
            return 'clock_drift'
        if now - self.started >= self._policy['wall_seconds']:
            return 'deadline'
        if now - row[0] >= (30 if case.endswith(':core_thesis') else 20):
            return 'case_deadline'
        return ''

    def claim(self, case, stage, route, *, request_sha256=None):
        """Record a simulated attempt atomically; returned IDs are not capabilities."""
        with self._seal_lock:
            return self._claim_locked(case, stage, route, request_sha256=request_sha256)

    def _claim_locked(self, case, stage, route, *, request_sha256=None):
        if self._locally_sealed:
            raise AccountingError('locally sealed')
        if request_sha256 is not None and (type(request_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', request_sha256)):
            raise AccountingError('invalid fixture request binding')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            reason = db.execute('SELECT halt FROM state').fetchone()[0]
            reason = reason or self._case_reason(db, case, self.clock())
            limits = self._policy['per_case'].get(case, {})
            stage_cap = self._policy['per_stage'].get(case, {}).get(stage, {}).get(route, 0)
            attempts = db.execute('SELECT case_id,stage,route,outcome FROM attempts').fetchall()
            if not reason:
                if self.clock() - self.started >= self._policy['wall_seconds']:
                    reason = 'deadline'
                elif not stage_cap or not limits.get(route, 0):
                    reason = 'scope'
                elif any(c != case and outcome == 'pending' for c, s, r, outcome in attempts):
                    reason = 'concurrent_case'
                elif sum(o == 'pending' for c, s, r, o in attempts) >= self._policy['concurrent_sec']:
                    reason = 'concurrency'
                elif (len(attempts) >= self._policy['sec_gets']
                      or sum(c == case for c, s, r, o in attempts) >= limits['sec']
                      or sum(c == case and r == route for c, s, r, o in attempts) >= limits[route]
                      or sum(c == case and s == stage and r == route for c, s, r, o in attempts) >= stage_cap):
                    reason = 'quota'
            if reason:
                db.execute('UPDATE state SET halt=?', (reason,))
            else:
                attempt = uuid4().hex
                db.execute('INSERT INTO attempts(id,case_id,stage,route,request_sha256) VALUES (?,?,?,?,?)',
                           (attempt, case, stage, route, request_sha256))
        if reason:
            raise AccountingError(reason)
        return attempt

    def claim_fixture_dispatch(self, attempt, *, case=None, route=None, request_sha256=None):
        """One-shot accounting at the fake connection boundary; not a live grant.

        Rate excess halts rather than sleeping/retrying. Failed connections stay
        consumed. A native executor must use its own approved request gate.
        """
        with self._seal_lock:
            return self._dispatch_locked(attempt, case=case, route=route, request_sha256=request_sha256)

    def _dispatch_locked(self, attempt, *, case=None, route=None, request_sha256=None):
        if self._locally_sealed:
            raise AccountingError('locally sealed')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            reason = db.execute('SELECT halt FROM state').fetchone()[0]
            now = self.clock()
            pending = db.execute('SELECT outcome,case_id,route,request_sha256 FROM attempts WHERE id=?', (attempt,)).fetchone()
            if pending:
                reason = reason or self._case_reason(db, pending[1], now)
            duplicate = db.execute('SELECT 1 FROM fixture_dispatches WHERE attempt_id=?', (attempt,)).fetchone()
            latest, = db.execute('SELECT MAX(dispatched_at) FROM fixture_dispatches').fetchone()
            recent, = db.execute('SELECT COUNT(*) FROM fixture_dispatches WHERE dispatched_at>?', (now-1,)).fetchone()
            if not reason:
                if not math.isfinite(now) or now < self.started or (latest is not None and now < latest):
                    reason = 'clock_drift'
                elif now - self.started >= self._policy['wall_seconds']:
                    reason = 'deadline'
                elif self._locally_sealed:
                    reason = 'locally_sealed'
                elif not pending or pending[0] != 'pending' or duplicate:
                    reason = 'unclaimed_or_consumed_dispatch'
                elif pending[3] is not None and (case, route, request_sha256) != (pending[1], pending[2], pending[3]):
                    reason = 'fixture_binding_mismatch'
                elif pending[3] is None and any(v is not None for v in (case, route, request_sha256)):
                    reason = 'fixture_binding_missing'
                elif recent >= 10:
                    reason = 'dispatch_rate'
            if reason:
                db.execute('UPDATE state SET halt=?', (reason,))
            else:
                db.execute('INSERT INTO fixture_dispatches VALUES (?,?)', (attempt, now))
        if reason:
            raise AccountingError(reason)

    def settle(self, attempt, *, succeeded):
        # A seal cannot return while a settlement is still committing; once
        # it returns, successful late results cannot commit as successes.
        with self._seal_lock:
            return self._settle_locked(attempt, succeeded=succeeded)

    def _settle_locked(self, attempt, *, succeeded):
        if type(succeeded) is not bool:
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN 'invalid_outcome' ELSE halt END")
            raise AccountingError('invalid outcome')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute('SELECT outcome,case_id FROM attempts WHERE id=?', (attempt,)).fetchone()
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            now = self.clock()
            case_reason = self._case_reason(db, pending[1], now) if pending else ''
            expired = now - self.started >= self._policy['wall_seconds'] or bool(case_reason) or (self._locally_sealed and succeeded)
            if not pending or pending[0] != 'pending':
                reason = halt or 'invalid_settlement'
                db.execute('UPDATE state SET halt=?', (reason,))
                invalid = True
            else:
                invalid = False
                reason = halt or case_reason or ('locally_sealed' if self._locally_sealed and succeeded else
                                                   'deadline' if expired else '' if succeeded else 'attempt_failure')
                db.execute('UPDATE state SET halt=?', (reason,))
                outcome = 'late' if halt or expired else 'success' if succeeded else 'failure'
                db.execute('UPDATE attempts SET outcome=? WHERE id=?', (outcome, attempt))
        if invalid:
            raise AccountingError('invalid settlement')

    def retain_fixture_body(self, attempt, body, *, forbidden_values):
        """Store complete simulated bytes atomically, before simulated settlement.

        This is not source admission or a native-response handler. Transport URL,
        media, provenance and runtime-secret binding must still be enforced by
        the future executor. No caller-controlled receipt fields are accepted.
        """
        with self._seal_lock:
            return self._retain_body_locked(attempt, body, forbidden_values=forbidden_values)

    def _retain_body_locked(self, attempt, body, *, forbidden_values):
        if self._locally_sealed:
            raise AccountingError('locally sealed')
        from .pilot_policy import reject_runtime_values
        from .capture_budget import BudgetError
        reason = ''
        if (type(body) is not bytes or type(forbidden_values) is not tuple
                or not forbidden_values
                or any(type(v) is not str or not v for v in forbidden_values)):
            reason = 'retention_input'
        elif len(body) > self._policy['body_max_bytes']:
            reason = 'body_size'
        else:
            try:
                text = body.decode('utf-8', errors='strict')
                reject_runtime_values(text, forbidden_values, raw=body)
            except (BudgetError, UnicodeError, RecursionError):
                reason = 'body_screening'
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            pending = db.execute('SELECT outcome,case_id FROM attempts WHERE id=?', (attempt,)).fetchone()
            total = db.execute('SELECT COALESCE(SUM(length(body)),0) FROM bodies').fetchone()[0]
            duplicate = db.execute('SELECT 1 FROM bodies WHERE attempt_id=?', (attempt,)).fetchone()
            reason = halt or reason
            if pending:
                reason = reason or self._case_reason(db, pending[1], self.clock())
            if not reason:
                if self.clock() - self.started >= self._policy['wall_seconds']:
                    reason = 'deadline'
                elif not pending or pending[0] != 'pending' or duplicate:
                    reason = 'retention_attempt'
                elif total + len(body) > self._policy['aggregate_raw_body_max_bytes']:
                    reason = 'aggregate_body_size'
            if reason:
                db.execute('UPDATE state SET halt=?', (reason,))
            else:
                sha = hashlib.sha256(body).hexdigest()
                db.execute('INSERT INTO bodies VALUES (?,?,?)', (attempt, sha, body))
        if reason:
            raise AccountingError(reason)
        return {'attempt_id': attempt, 'body_sha256': sha, 'body_bytes': len(body),
                'admitted_evidence': False, 'execution_authorized': False}

    def record_cleanup_failure(self, code):
        """Record safe codes only; never replace the first durable halt reason."""
        if code not in {'transport_close', 'settlement'}:
            raise AccountingError('invalid cleanup code')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO cleanup_failures VALUES (?)', (code,))
            db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN 'cleanup_failure' ELSE halt END")

    def summary(self):
        with self._connect() as db:
            rows = db.execute('SELECT outcome,COUNT(*) FROM attempts GROUP BY outcome').fetchall()
            return {'halt': db.execute('SELECT halt FROM state').fetchone()[0],
                    'outcomes': dict(rows), 'execution_authorized': False,
                    'fixture_dispatch_count': db.execute('SELECT COUNT(*) FROM fixture_dispatches').fetchone()[0],
                    'cleanup_failures': [r[0] for r in db.execute('SELECT code FROM cleanup_failures ORDER BY rowid')]}
