"""Fresh-only native accounting component; no launcher or network setup.

Requires the separately matching ordinary profile. Operator approval provenance,
invoice verification, isolated runtime setup, and the parent deadline protocol
remain the future launcher's responsibility. Fixture ledgers cannot be adapted.
"""
from pathlib import Path
import hashlib
import time
from uuid import uuid4

from validation.capture_budget import AttemptLedger, BudgetError, digest
from validation.ordinary_native_policy import PURPOSE
from validation.ordinary_pilot_contract import CASES, quota_contract
from validation.pilot_approved import ExchangeGate


class OrdinaryNativeLedger(AttemptLedger):
    def __init__(self, path, policy, *, create=False):
        if create is not True or type(policy) is not dict or policy.get('purpose') != PURPOSE:
            raise BudgetError('fresh separately approved ordinary ledger required')
        path = Path(path).absolute()
        if path != path.resolve() or str(path.parent) != policy.get('approval', {}).get('output_dir') or path.name != 'ledger.sqlite':
            raise BudgetError('ordinary ledger path differs from approval')
        # Validate everything before consuming the exact fresh output directory.
        from validation.capture_budget import validate_policy
        validate_policy(policy)
        path.parent.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.started_ns = time.monotonic_ns()
        super().__init__(path, policy, create=True)
        path.chmod(0o600)
        with self.transaction() as db:
            db.execute('CREATE TABLE ordinary_case_times (case_run TEXT PRIMARY KEY, started_ns INTEGER NOT NULL)')
            db.execute('CREATE TABLE ordinary_wire_entries (attempt_id TEXT PRIMARY KEY, entered_ns INTEGER NOT NULL)')
            db.execute('CREATE TABLE ordinary_responses (attempt_id TEXT PRIMARY KEY, url TEXT NOT NULL, '
                       'http_status INTEGER NOT NULL, media_type TEXT NOT NULL, sha256 TEXT NOT NULL, body BLOB NOT NULL)')

    def begin_case(self, case_id):
        run_id = str(uuid4())
        with self.transaction() as db:
            self.active(db)
            consumed, = db.execute('SELECT COUNT(*) FROM cases').fetchone()
            if consumed >= len(CASES) or case_id != CASES[consumed] or db.execute("SELECT 1 FROM cases WHERE status='active'").fetchone():
                raise BudgetError('fixed ordinary case order required')
            db.execute("INSERT INTO cases VALUES (?,?,'active')", (run_id, case_id))
            db.execute('INSERT INTO ordinary_case_times VALUES (?,?)', (run_id, time.monotonic_ns()))
        return run_id

    def claim_wire_entry(self, attempt_id, *, case_run, route, request_sha256):
        """Commit once immediately before HTTPX entry; failed I/O stays consumed.

        The separate native intent is necessary but insufficient. This second
        claim enforces rate and concurrency at the owned transport entry point,
        rather than when a reservation or exchange context was created.
        """
        reason = None
        with self.transaction() as db:
            self.active(db)
            now = time.monotonic_ns()
            row = db.execute('SELECT case_run,route,request_sha256,status FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            case = db.execute("SELECT c.case_id,t.started_ns FROM cases c JOIN ordinary_case_times t ON t.case_run=c.id WHERE c.id=? AND c.status='active'", (case_run,)).fetchone()
            duplicate = db.execute('SELECT 1 FROM ordinary_wire_entries WHERE attempt_id=?', (attempt_id,)).fetchone()
            intent = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_dispatches'").fetchone()
            intent = intent and db.execute('SELECT 1 FROM native_dispatches WHERE attempt_id=?', (attempt_id,)).fetchone()
            latest, = db.execute('SELECT MAX(entered_ns) FROM ordinary_wire_entries').fetchone()
            recent, = db.execute('SELECT COUNT(*) FROM ordinary_wire_entries WHERE entered_ns>?', (now-1_000_000_000,)).fetchone()
            inflight, = db.execute("SELECT COUNT(*) FROM ordinary_wire_entries w JOIN attempts a ON a.id=w.attempt_id WHERE a.status='claimed'").fetchone()
            if row != (case_run, route, request_sha256, 'claimed') or not case or duplicate or not intent or not route.startswith('sec/'):
                reason = 'invalid_request'
            elif now < self.started_ns or now < case[1] or (latest is not None and now < latest):
                reason = 'configuration_drift'
            elif now-self.started_ns >= 480_000_000_000 or now-case[1] >= (30 if case[0].endswith(':core_thesis') else 20)*1_000_000_000:
                reason = 'stage_timeout'
            elif recent >= 10 or inflight >= 4:
                reason = 'invalid_request'
            if reason:
                db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (reason,))
            else:
                db.execute('INSERT INTO ordinary_wire_entries VALUES (?,?)', (attempt_id, now))
        if reason:
            raise BudgetError('ordinary wire entry refused')

    def settle(self, *args, **kwargs):
        raise BudgetError('ordinary success requires atomic complete_response retention')

    def complete_response(self, attempt_id, *, url, media_type, body, forbidden_values):
        """Retain complete successful OwnedHTTPTransport bytes before settlement.

        Status 200 and identity encoding are transport return invariants. This
        receipt binds request bytes; it does not authenticate SEC origin or admit
        the body's contents as company evidence. Failures remain consumed.
        """
        from validation.pilot_policy import reject_runtime_values
        limits = quota_contract()
        if (type(body) is not bytes or len(body) > limits['body_max_bytes']
                or type(url) is not str or type(media_type) is not str
                or type(forbidden_values) is not tuple or not forbidden_values
                or any(type(value) is not str or not value for value in forbidden_values)):
            self.halt('invalid_response')
            raise BudgetError('ordinary response retention refused')
        try:
            reject_runtime_values({'url': url, 'media_type': media_type,
                                   'content': body.decode('utf-8', errors='strict')},
                                  forbidden_values, raw=body)
        except (BudgetError, UnicodeError, RecursionError):
            self.halt('invalid_response')
            raise BudgetError('ordinary response retention refused') from None
        reason = None
        with self.transaction() as db:
            self.active(db)
            row = db.execute('SELECT a.route,a.request_sha256,a.status,s.stage,c.case_id,t.started_ns '
                'FROM attempts a JOIN stage_reservations s ON s.attempt_id=a.id '
                'JOIN cases c ON c.id=a.case_run JOIN ordinary_case_times t ON t.case_run=c.id '
                "WHERE a.id=? AND c.status='active'", (attempt_id,)).fetchone()
            entered = db.execute('SELECT 1 FROM ordinary_wire_entries WHERE attempt_id=?', (attempt_id,)).fetchone()
            total, = db.execute('SELECT COALESCE(SUM(length(body)),0) FROM ordinary_responses').fetchone()
            now = time.monotonic_ns()
            if (not row or row[2] != 'claimed' or not entered
                    or row[1] != digest({'method': 'GET', 'url': url, 'route': row[0], 'stage': row[3]})
                    or media_type not in ({'text/html', 'text/plain'} if row[0] == 'sec/document' else {'application/json'})
                    or total + len(body) > limits['aggregate_raw_body_max_bytes']):
                reason = 'invalid_response'
            elif now < self.started_ns or now < row[5]:
                reason = 'configuration_drift'
            elif now-self.started_ns >= 480_000_000_000 or now-row[5] >= (30 if row[4].endswith(':core_thesis') else 20)*1_000_000_000:
                reason = 'stage_timeout'
            if reason:
                db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (reason,))
            else:
                db.execute('INSERT INTO ordinary_responses VALUES (?,?,200,?,?,?)',
                           (attempt_id, url, media_type, hashlib.sha256(body).hexdigest(), body))
                db.execute("UPDATE attempts SET status='settled',actual=0 WHERE id=?", (attempt_id,))
        if reason:
            raise BudgetError('ordinary response retention refused')


class OrdinaryNativeGate(ExchangeGate):
    def __init__(self, owner):
        if type(owner.ledger) is not OrdinaryNativeLedger or owner.monitoring is not True:
            raise BudgetError('ordinary gate requires its fresh native ledger')
        super().__init__(owner)

    def record_dispatch(self):
        state = self.require()
        with self.lock:
            if self.closed or state['dispatched'] or not state['validated']:
                raise BudgetError('ordinary wire entry sealed or consumed')
            self.owner.ledger.claim_wire_entry(state['attempt'], case_run=state['case_run'],
                route=state['route'], request_sha256=state['fingerprint'])
            state['dispatched'] = True
            self.dispatched += 1
