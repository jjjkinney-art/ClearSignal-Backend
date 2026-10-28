"""Fresh-only native accounting for the twelve-case ordinary pilot.

Requires the separately matching ordinary profile. Approver identity, invoice
terms and the live network backend are outside this module. The launcher owns
creation of the approved output directory; this ledger only accepts that exact
fresh directory and never adapts a fixture or historical ledger.
"""
import hashlib
import html
import json
import os
from pathlib import Path
import stat
import time
from uuid import uuid4

from validation.capture_budget import AttemptLedger, BudgetError, RateLimitDelay, digest
from validation.ordinary_native_policy import PURPOSE
from validation.ordinary_pilot_contract import CASES, quota_contract
from validation.pilot_approved import ExchangeGate

ANSWER_MAX_BYTES = 4 * 1024 * 1024
CASE_SECONDS = {'core_thesis': 30, 'decision_threshold': 20}
RUN_SECONDS = 480
# Fixed failure vocabulary for every failed exchange, not just the first.
EXCHANGE_FAILURE_CODES = frozenset({
    'transport', 'sec_refusal', 'identity_mismatch', 'semantic_refusal',
    'retention_refused', 'halted_before_dispatch', 'slot_timeout', 'interrupted'})


def case_seconds(case_id):
    return CASE_SECONDS[case_id.split(':')[1]]


def create_fresh_output(path):
    """Launcher-side creation of the one approved output directory.

    Creates the directory (parent must already exist) and an empty private
    ``isolated-home``. Never reuses or resumes an existing directory.
    """
    output = Path(path).absolute()
    if output.is_symlink() or output.resolve() != output or not output.parent.is_dir():
        raise BudgetError('canonical fresh output directory required')
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    (output / 'isolated-home').mkdir(mode=0o700)
    return output


def _require_fresh_output(output, *, allowed):
    """The exact state create_fresh_output leaves, plus launcher inputs."""
    try:
        info = os.lstat(output)
        home = os.lstat(output / 'isolated-home')
    except OSError:
        raise BudgetError('launcher-created fresh output required') from None
    names = {entry.name for entry in output.iterdir()}
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
            or not stat.S_ISDIR(home.st_mode) or home.st_mode & 0o077
            or any((output / 'isolated-home').iterdir())
            or 'isolated-home' not in names or names - {'isolated-home', *allowed}):
        raise BudgetError('ordinary output is not the launcher-created fresh directory')


def screen_body(body, media_type, forbidden_values):
    """Refuse runtime-only values in raw bytes and in decoded content.

    SEC filings are not guaranteed to be UTF-8, so screening never requires a
    strict decode. JSON is parsed (duplicate keys refused) and screened
    recursively, including escaped strings; text also checks HTML entities.
    """
    from validation.pilot_policy import reject_runtime_values
    if any(value.encode('utf-8') in body for value in forbidden_values):
        raise BudgetError('runtime-only value in provider data')
    if media_type == 'application/json':
        from validation.pilot_live import json_object
        reject_runtime_values(json_object(body), forbidden_values)
        return
    text = body.decode('utf-8', errors='replace')
    reject_runtime_values(text, forbidden_values)
    reject_runtime_values(html.unescape(text), forbidden_values)


class OrdinaryNativeLedger(AttemptLedger):
    LAUNCHER_INPUTS = frozenset({'request.json'})

    def __init__(self, path, policy, *, create=False):
        if create is not True or type(policy) is not dict or policy.get('purpose') != PURPOSE:
            raise BudgetError('fresh separately approved ordinary ledger required')
        path = Path(path).absolute()
        if path != path.resolve() or str(path.parent) != policy.get('approval', {}).get('output_dir') or path.name != 'ledger.sqlite':
            raise BudgetError('ordinary ledger path differs from approval')
        # Validate everything before touching the approved output directory.
        from validation.capture_budget import validate_policy
        validate_policy(policy)
        _require_fresh_output(path.parent, allowed=self.LAUNCHER_INPUTS)
        self.started_ns = time.monotonic_ns()
        super().__init__(path, policy, create=True)
        path.chmod(0o600)
        with self.transaction() as db:
            db.execute('CREATE TABLE ordinary_case_times (case_run TEXT PRIMARY KEY, started_ns INTEGER NOT NULL)')
            db.execute('CREATE TABLE ordinary_run (id INTEGER PRIMARY KEY CHECK(id=1), started_ns INTEGER NOT NULL)')
            db.execute('INSERT INTO ordinary_run VALUES (1,?)', (self.started_ns,))
            db.execute('CREATE TABLE ordinary_wire_entries (attempt_id TEXT PRIMARY KEY, entered_ns INTEGER NOT NULL)')
            db.execute('CREATE TABLE ordinary_responses (attempt_id TEXT PRIMARY KEY, url TEXT NOT NULL, '
                       'http_status INTEGER NOT NULL, media_type TEXT NOT NULL, sha256 TEXT NOT NULL, '
                       'body BLOB NOT NULL, completed_ns INTEGER NOT NULL)')
            db.execute('CREATE TABLE ordinary_exchange_failures (attempt_id TEXT PRIMARY KEY, '
                       'code TEXT NOT NULL, detail TEXT NOT NULL, recorded_ns INTEGER NOT NULL)')
            db.execute('CREATE TABLE ordinary_answers (case_run TEXT PRIMARY KEY, case_id TEXT UNIQUE NOT NULL, '
                       'sha256 TEXT NOT NULL, payload BLOB NOT NULL, recorded_ns INTEGER NOT NULL)')

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

    def _deadline_reason(self, now, case_id, case_started):
        if now < self.started_ns or now < case_started:
            return 'configuration_drift'
        if now - self.started_ns >= RUN_SECONDS * 1_000_000_000 or now - case_started >= case_seconds(case_id) * 1_000_000_000:
            return 'stage_timeout'
        return None

    def case_remaining_seconds(self, case_run):
        """Seconds left for this active case, bounded by the whole run."""
        with self.transaction() as db:
            row = db.execute("SELECT c.case_id,t.started_ns FROM cases c JOIN ordinary_case_times t "
                             "ON t.case_run=c.id WHERE c.id=? AND c.status='active'", (case_run,)).fetchone()
        if not row:
            return 0.0
        now = time.monotonic_ns()
        left = min(row[1] + case_seconds(row[0]) * 1_000_000_000, self.started_ns + RUN_SECONDS * 1_000_000_000) - now
        return max(0.0, left / 1_000_000_000)

    def claim_wire_entry(self, attempt_id, *, case_run, route, request_sha256):
        """Commit once immediately before HTTPX entry; failed I/O stays consumed.

        Rate excess returns a pacing delay (RateLimitDelay) without consuming the
        entry; the caller waits inside its case deadline. Concurrency excess,
        a mismatched/duplicate claim or an expired deadline halts the run.
        """
        reason = delay = None
        with self.transaction() as db:
            self.active(db)
            now = time.monotonic_ns()
            row = db.execute('SELECT case_run,route,request_sha256,status FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            case = db.execute("SELECT c.case_id,t.started_ns FROM cases c JOIN ordinary_case_times t ON t.case_run=c.id WHERE c.id=? AND c.status='active'", (case_run,)).fetchone()
            duplicate = db.execute('SELECT 1 FROM ordinary_wire_entries WHERE attempt_id=?', (attempt_id,)).fetchone()
            intent = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_dispatches'").fetchone()
            intent = intent and db.execute('SELECT 1 FROM native_dispatches WHERE attempt_id=?', (attempt_id,)).fetchone()
            latest, = db.execute('SELECT MAX(entered_ns) FROM ordinary_wire_entries').fetchone()
            recent = [r[0] for r in db.execute('SELECT entered_ns FROM ordinary_wire_entries WHERE entered_ns>? ORDER BY entered_ns',
                                               (now - 1_000_000_000,))]
            inflight, = db.execute("SELECT COUNT(*) FROM ordinary_wire_entries w JOIN attempts a ON a.id=w.attempt_id WHERE a.status='claimed'").fetchone()
            if row != (case_run, route, request_sha256, 'claimed') or not case or duplicate or not intent or not route.startswith('sec/'):
                reason = 'invalid_request'
            elif latest is not None and now < latest:
                reason = 'configuration_drift'
            else:
                reason = self._deadline_reason(now, case[0], case[1])
            if not reason:
                if inflight >= quota_contract()['concurrent_sec']:
                    reason = 'invalid_request'
                elif len(recent) >= self.policy['quotas']['sec_per_second']:
                    delay = max(0.001, (recent[0] + 1_000_000_000 - now) / 1_000_000_000)
            if reason:
                db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (reason,))
            elif delay is None:
                db.execute('INSERT INTO ordinary_wire_entries VALUES (?,?)', (attempt_id, now))
        if reason:
            raise BudgetError('ordinary wire entry refused')
        if delay is not None:
            raise RateLimitDelay(delay)

    def settle(self, *args, **kwargs):
        raise BudgetError('ordinary success requires atomic complete_response retention')

    def finish_case(self, case_run):
        raise BudgetError('ordinary cases finish only with a retained answer')

    def complete_response(self, attempt_id, *, url, media_type, body, forbidden_values):
        """Retain complete successful OwnedHTTPTransport bytes before settlement.

        Status 200 and identity encoding are transport return invariants. This
        receipt binds request bytes; it does not authenticate SEC origin or admit
        the body's contents as company evidence. Failures remain consumed.
        """
        limits = quota_contract()
        if (type(body) is not bytes or len(body) > limits['body_max_bytes']
                or type(url) is not str or type(media_type) is not str
                or type(forbidden_values) is not tuple or not forbidden_values
                or any(type(value) is not str or not value for value in forbidden_values)):
            self.halt('invalid_response')
            raise BudgetError('ordinary response retention refused')
        try:
            screen_body(body, media_type, forbidden_values)
        except (BudgetError, ValueError, RecursionError):
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
            else:
                reason = self._deadline_reason(now, row[4], row[5])
            if reason:
                db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (reason,))
            else:
                db.execute('INSERT INTO ordinary_responses VALUES (?,?,200,?,?,?,?)',
                           (attempt_id, url, media_type, hashlib.sha256(body).hexdigest(), body, now))
                db.execute("UPDATE attempts SET status='settled',actual=0 WHERE id=?", (attempt_id,))
        if reason:
            raise BudgetError('ordinary response retention refused')

    def record_exchange_failure(self, attempt_id, code, detail):
        """Durably record one failed exchange with a fixed, non-secret code.

        Never fabricates a response or receipt. The first durable halt reason is
        kept; this only adds a row for the attempt that actually failed.
        """
        if code not in EXCHANGE_FAILURE_CODES or type(detail) is not str or len(detail) > 64 \
                or not detail.replace('_', '').replace('/', '').isalnum():
            raise BudgetError('invalid exchange failure record')
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM attempts WHERE id=?', (attempt_id,)).fetchone():
                db.execute('INSERT OR IGNORE INTO ordinary_exchange_failures VALUES (?,?,?,?)',
                           (attempt_id, code, detail, time.monotonic_ns()))
                db.execute("UPDATE policy SET halted=COALESCE(halted,'post_claim_failure') WHERE id=1")

    def complete_case(self, case_run, payload, *, forbidden_values):
        """Retain the complete answer and finish its case in one transaction."""
        try:
            raw = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
            if (type(payload) is not dict or len(raw) > ANSWER_MAX_BYTES
                    or type(forbidden_values) is not tuple or not forbidden_values):
                raise BudgetError('invalid answer')
            from validation.pilot_policy import reject_runtime_values
            reject_runtime_values(payload, forbidden_values, raw=raw)
        except (BudgetError, TypeError, ValueError, RecursionError):
            self.halt('invalid_response')
            raise BudgetError('ordinary answer retention refused') from None
        reason = None
        with self.transaction() as db:
            self.active(db)
            case = db.execute("SELECT c.case_id,t.started_ns FROM cases c JOIN ordinary_case_times t ON t.case_run=c.id "
                              "WHERE c.id=? AND c.status='active'", (case_run,)).fetchone()
            unsettled = db.execute("SELECT 1 FROM attempts WHERE case_run=? AND status!='settled'", (case_run,)).fetchone()
            now = time.monotonic_ns()
            if not case or unsettled or payload.get('company') != case[0].split(':')[0]:
                reason = 'invalid_response'
            else:
                reason = self._deadline_reason(now, case[0], case[1])
            if reason:
                db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (reason,))
            else:
                db.execute('INSERT INTO ordinary_answers VALUES (?,?,?,?,?)',
                           (case_run, case[0], hashlib.sha256(raw).hexdigest(), raw, now))
                db.execute("UPDATE cases SET status='complete' WHERE id=?", (case_run,))
        if reason:
            raise BudgetError('ordinary answer retention refused')


class OrdinaryNativeGate(ExchangeGate):
    def __init__(self, owner):
        if type(owner.ledger) is not OrdinaryNativeLedger or owner.monitoring is not True:
            raise BudgetError('ordinary gate requires its fresh native ledger')
        super().__init__(owner)
        self.entry_pacing_waits = 0

    def record_dispatch(self):
        """Claim the durable wire entry, pacing (never retrying I/O) on rate limits.

        The pacing wait happens before any byte is sent, without the gate lock,
        and the ledger re-checks the case deadline on every attempt.
        """
        state = self.require()
        while True:
            with self.lock:
                if self.closed or state['dispatched'] or not state['validated']:
                    raise BudgetError('ordinary wire entry sealed or consumed')
                try:
                    self.owner.ledger.claim_wire_entry(state['attempt'], case_run=state['case_run'],
                        route=state['route'], request_sha256=state['fingerprint'])
                except RateLimitDelay as pacing:
                    delay = pacing.seconds
                    self.entry_pacing_waits += 1
                else:
                    state['dispatched'] = True
                    self.dispatched += 1
                    return
            release = getattr(self.owner, 'release', None)
            if release is not None:
                release.wait(min(delay, 0.05))
            else:
                time.sleep(min(delay, 0.05))
            self.require()
