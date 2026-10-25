"""Offline simulated-attempt accounting. Never grants native transport authority.

No reopen/resume API and no provider integration. Claims count permanently even
on failure. Durable halts prohibit new claims; late settlements are recorded as
late, never as publishable answers. Retention and physical fencing remain separate.
"""
import os
import hashlib
from copy import deepcopy
import sqlite3
import time
from uuid import uuid4

from .ordinary_pilot_contract import quota_contract


class AccountingError(ValueError):
    pass


class OfflineAccounting:
    def __init__(self, path, *, clock=time.monotonic):
        self.path, self.clock = str(path), clock
        self.started = clock()
        self._policy = quota_contract()
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE state (halt TEXT NOT NULL);
                INSERT INTO state VALUES ('');
                CREATE TABLE bodies (attempt_id TEXT PRIMARY KEY, sha256 TEXT, body BLOB NOT NULL);
                CREATE TABLE attempts (id TEXT PRIMARY KEY, case_id TEXT, stage TEXT,
                    route TEXT, outcome TEXT NOT NULL DEFAULT 'pending');
            ''')

    @property
    def policy(self):
        return deepcopy(self._policy)

    def claim(self, case, stage, route):
        """Record a simulated attempt atomically; returned IDs are not capabilities."""
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            reason = db.execute('SELECT halt FROM state').fetchone()[0]
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
                db.execute('INSERT INTO attempts(id,case_id,stage,route) VALUES (?,?,?,?)',
                           (attempt, case, stage, route))
        if reason:
            raise AccountingError(reason)
        return attempt

    def settle(self, attempt, *, succeeded):
        if type(succeeded) is not bool:
            with sqlite3.connect(self.path, timeout=10) as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN 'invalid_outcome' ELSE halt END")
            raise AccountingError('invalid outcome')
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute('SELECT outcome FROM attempts WHERE id=?', (attempt,)).fetchone()
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            expired = self.clock() - self.started >= self._policy['wall_seconds']
            if not pending or pending[0] != 'pending':
                reason = halt or 'invalid_settlement'
                db.execute('UPDATE state SET halt=?', (reason,))
                invalid = True
            else:
                invalid = False
                reason = halt or ('deadline' if expired else '' if succeeded else 'attempt_failure')
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
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            pending = db.execute('SELECT outcome FROM attempts WHERE id=?', (attempt,)).fetchone()
            total = db.execute('SELECT COALESCE(SUM(length(body)),0) FROM bodies').fetchone()[0]
            duplicate = db.execute('SELECT 1 FROM bodies WHERE attempt_id=?', (attempt,)).fetchone()
            reason = halt or reason
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

    def summary(self):
        with sqlite3.connect(self.path) as db:
            rows = db.execute('SELECT outcome,COUNT(*) FROM attempts GROUP BY outcome').fetchall()
            return {'halt': db.execute('SELECT halt FROM state').fetchone()[0],
                    'outcomes': dict(rows), 'execution_authorized': False}
