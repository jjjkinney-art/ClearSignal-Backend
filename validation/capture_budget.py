"""Attempt accounting for offline rehearsals and exact reviewed capture profiles.

This module grants no authority by itself and establishes no invoice ceiling.
Native dispatch requires a fixed approved profile; import performs no network I/O.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4


PILOT_CASES = frozenset(f'{ticker}:{question}' for ticker in ('ASML', 'ACHC', 'NPK')
                        for question in ('core_thesis', 'decision_threshold'))
LEDGER_SCHEMA_VERSION = 2
SETUP_FILES = ('issuer_registry.v2.json', 'company_quality_manifest.v2.json',
               'company_quality_manifest.v2.metadata.json')


def setup_binding():
    """Bind the exact local setup bytes; this does not authenticate their sources."""
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SETUP_FILES}


def validate_cases(cases):
    root = Path(__file__).resolve().parent
    registry, manifest, metadata = [json.loads((root / name).read_text()) for name in SETUP_FILES]
    issuers = {item['ticker']: item for item in registry['issuers']}
    available = {f"{c['issuer_id']}:{c['question_id']}" for c in manifest['cases']}
    for case in cases:
        ticker = case.split(':')[0]
        if (case not in PILOT_CASES or case not in available
                or ticker not in metadata['development_issuers']
                or ticker in metadata['reserved_holdouts']
                or issuers.get(ticker, {}).get('reserved_holdout') is not False):
            raise BudgetError('case outside bounded development pilot or reserved holdout')


class BudgetError(ValueError):
    pass


class RateLimitDelay(BudgetError):
    """A pending claim must wait outside the SQLite transaction."""
    def __init__(self, seconds):
        super().__init__('SEC claim rate limit; retry this unclaimed reservation later')
        self.seconds = seconds


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def money(value, *, round_up=True):
    """Convert USD exactly, independent of the ambient Decimal context.

    Charges round UP; approved budgets round DOWN. Integer coefficient/exponent
    arithmetic avoids Decimal multiplication silently rounding before conversion.
    Limit input length and avoid constructing enormous powers from exponents.
    """
    if not isinstance(value, str) or len(value) > 512:
        raise BudgetError('USD values must be bounded decimal strings')
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError
        sign, digits, exponent = number.as_tuple()
        coefficient = int(''.join(str(digit) for digit in digits))
        if sign and coefficient:
            raise ValueError
        shift = exponent + 9
        if not coefficient:
            result = 0
        elif shift >= 0:
            if len(str(coefficient)) + shift > 19:
                raise ValueError
            result = coefficient * 10**shift
        else:
            places = -shift
            if places >= len(digits):
                quotient, remainder = 0, coefficient
            else:
                quotient, remainder = divmod(coefficient, 10**places)
            result = quotient + int(round_up and remainder != 0)
        if result > 2**63 - 1:
            raise ValueError
        return result
    except (InvalidOperation, ValueError, OverflowError):
        raise BudgetError('USD value must be finite, nonnegative and representable') from None


def count(value):
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise BudgetError('unit count must be a bounded nonnegative integer')
    return value


def validate_policy(policy):
    if not isinstance(policy, dict) or type(policy.get('schema_version')) is not int or policy['schema_version'] not in (1, 2):
        raise BudgetError('unsupported policy')
    rehearsal = policy['schema_version'] == 2
    ordinary = rehearsal and policy.get('purpose') == 'approved_ordinary_twelve_case_pilot'
    if rehearsal:
        from validation.pilot_policy import policy_for
        try:
            purpose = policy['purpose']
            modes = {'offline_six_case_rehearsal': 'offline',
                     'disabled_live_adapter_validation': 'live_adapter_validation',
                     'disabled_source_monitoring_validation': 'source_monitoring',
                     'approved_six_case_pilot': 'approved',
                     'approved_source_monitoring_pilot': 'approved_source_monitoring',
                     'disabled_monitoring_freshness_validation': 'freshness',
                     'approved_monitoring_freshness_pilot': 'approved_freshness'}
            mode = modes.get(purpose)
            if ordinary:
                from validation.ordinary_native_policy import policy_for as ordinary_policy
                expected = ordinary_policy(policy['code_binding'], policy['dependencies'],
                    policy['approval'], policy['execution_configuration'], cases=policy['case_records'],
                    all_in_usd=policy['budget_usd'], retention_reference=policy['retention_reference'],
                    pricing_review_reference=policy['pricing_review_reference'])
            elif purpose == 'approved_two_source_diagnostic_capture':
                from validation.source_capture import policy_for as capture_policy
                expected = capture_policy(policy['code_binding'], policy['dependencies'],
                                          policy['approval'], policy['execution_configuration'])
            elif purpose == 'approved_eps_source_adequacy_capture':
                from validation.eps_source_capture import policy_for as eps_capture_policy
                expected = eps_capture_policy(policy['code_binding'], policy['dependencies'],
                                              policy['approval'], policy['execution_configuration'])
            elif mode is None:
                raise ValueError('unknown policy purpose')
            extra = ({'approval': policy['approval'], 'execution': policy['execution_configuration']}
                     if mode in {'approved', 'approved_source_monitoring', 'approved_freshness'} else {})
            if not ordinary and purpose not in {'approved_two_source_diagnostic_capture', 'approved_eps_source_adequacy_capture'}:
                expected = policy_for(policy['code_binding'], policy['dependencies'], mode=mode, **extra)
        except (KeyError, TypeError, ValueError):
            raise BudgetError('invalid fixed rehearsal policy') from None
        if digest(policy) != digest(expected):
            raise BudgetError('rehearsal policy is fixed; separate review required')
    for key in ('pilot_id', 'approval_reference', 'configuration_version', 'pricing_review_reference'):
        if not isinstance(policy.get(key), str) or not policy[key].strip():
            raise BudgetError(f'{key} is required')
    budget = money(policy.get('budget_usd'), round_up=False)
    if (budget < 0 if ordinary else budget <= 0) or count(policy.get('maximum_attempts')) < 1:
        raise BudgetError('positive budget and maximum_attempts required')
    cases = policy.get('approved_case_ids')
    if (not isinstance(cases, list) or not 1 <= len(cases) <= (12 if ordinary else 6)
            or any(not isinstance(c, str) or c.count(':') != 1 for c in cases)
            or len(set(cases)) != len(cases)):
        raise BudgetError('one to six distinct approved cases required')
    if ordinary:
        from validation.ordinary_pilot_contract import CASES
        from validation.ordinary_execution_contract import PACKET_CASE_PROJECTION_SHA256
        if cases != list(CASES) or policy.get('setup_sha256') != PACKET_CASE_PROJECTION_SHA256:
            raise BudgetError('exact ordinary packet binding required')
    else:
        validate_cases(cases)
    if not ordinary and policy.get('setup_sha256') != setup_binding():
        raise BudgetError('setup binding absent or changed')
    rates = policy.get('prices')
    if not isinstance(rates, dict) or not rates:
        raise BudgetError('explicit reviewed prices required')
    for route, price in rates.items():
        if not isinstance(route, str) or not route or not isinstance(price, dict):
            raise BudgetError('invalid priced route')
        if (price.get('currency') != 'USD'
                or price.get('all_incremental_charges_accounted') is not (False if rehearsal else True)):
            raise BudgetError('unknown currency or provider charges')
        if set(price) != {'currency', 'all_incremental_charges_accounted', 'request_usd', 'input_token_usd', 'output_token_usd', 'maximum_input_tokens', 'maximum_output_tokens'}:
            raise BudgetError('unsupported charge categories')
        count(price.get('maximum_input_tokens'))
        count(price.get('maximum_output_tokens'))
        for key in ('request_usd', 'input_token_usd', 'output_token_usd'):
            money(price[key])
    if rehearsal:
        quotas = policy.get('quotas', {})
        groups = quotas.get('groups', {})
        per_case = quotas.get('per_case', {})
        overall = quotas.get('overall', {})
        if (set(quotas) != {'groups', 'per_case', 'overall', 'sec_per_second'}
                or set(groups) != {'model', 'sec'} or set(overall) != set(groups)
                or set(per_case) != set(cases) or quotas['sec_per_second'] != 10
                or any(type(v) is not list or not v or len(v) != len(set(v))
                       for v in groups.values())
                or set(groups['model']) & set(groups['sec'])
                or set(groups['model'] + groups['sec']) != set(rates)):
            raise BudgetError('complete disjoint rehearsal quota groups required')
        for limits in [overall, *per_case.values()]:
            if not isinstance(limits, dict):
                raise BudgetError('invalid rehearsal quotas')
            for value in limits.values():
                count(value)
        if any(set(limits) != set(rates) | set(groups) for limits in per_case.values()):
            raise BudgetError('every case requires explicit group and route quotas')
    return budget


class AttemptLedger:
    """One immutable pilot policy; SQLite serializes reservations across callers.

    Reservations are NEVER refunded, even after cancellation/timeout/settlement.
    This intentionally conservative rule covers late work, but only for attempts
    that a cooperating transport actually routes through this ledger. Policy prices
    and input/output upper bounds are trusted reviewed inputs, not inferred here.
    """
    def __init__(self, path, policy, *, create=False):
        self._policy = json.dumps(policy, sort_keys=True, allow_nan=False)
        self.budget = validate_policy(self.policy)
        self.path = Path(path).resolve()
        if create:
            # Explicit creation cannot overwrite an existing pilot ledger.
            with self.path.open("xb"):
                pass
        elif not self.path.is_file():
            raise BudgetError("existing pilot ledger missing; refusing budget reset")
        self.policy_hash = digest(self.policy)
        self._file_identity = (self.path.stat().st_dev, self.path.stat().st_ino)
        with self.transaction() as db:
            if create:
                db.execute(f'PRAGMA user_version={LEDGER_SCHEMA_VERSION}')
                db.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT NOT NULL, halted TEXT)')
                db.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, case_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, case_run TEXT NOT NULL, route TEXT NOT NULL, reserve INTEGER NOT NULL, input_bound INTEGER NOT NULL, output_bound INTEGER NOT NULL, status TEXT NOT NULL, actual INTEGER, request_sha256 TEXT)')
                if self.policy.get('stage_quotas') is not None:
                    db.execute('CREATE TABLE stage_reservations (attempt_id TEXT PRIMARY KEY, stage TEXT NOT NULL)')
                if self.policy['schema_version'] == 2:
                    db.execute('CREATE TABLE sec_claims (attempt_id TEXT PRIMARY KEY, claimed_ns INTEGER NOT NULL)')
                    db.execute('CREATE TABLE first_transport_failure (id INTEGER PRIMARY KEY CHECK(id=1), attempt_id TEXT NOT NULL, route TEXT NOT NULL, stage TEXT NOT NULL, code TEXT NOT NULL)')
                    db.execute('CREATE TABLE first_sec_refusal (id INTEGER PRIMARY KEY CHECK(id=1), attempt_id TEXT NOT NULL, route TEXT NOT NULL, stage TEXT NOT NULL, code TEXT NOT NULL)')
            else:
                # No implicit migrations or resets, including prior accounting-only ledgers.
                if db.execute('PRAGMA user_version').fetchone()[0] != LEDGER_SCHEMA_VERSION:
                    raise BudgetError('unsupported ledger schema; explicit review required')
                db.execute('SELECT id,case_id,status FROM cases LIMIT 0')
                db.execute('SELECT id,case_run,route,reserve,input_bound,output_bound,status,actual,request_sha256 FROM attempts LIMIT 0')
                if self.policy.get('stage_quotas') is not None:
                    db.execute('SELECT attempt_id,stage FROM stage_reservations LIMIT 0')
            row = db.execute('SELECT hash FROM policy WHERE id=1').fetchone()
            if row is None and not create:
                raise BudgetError('existing ledger has no policy; refusing budget reset')
            if row is None:
                db.execute('INSERT INTO policy VALUES (1,?,NULL)', (self.policy_hash,))
            elif row[0] != self.policy_hash:
                raise BudgetError('ledger policy/configuration mismatch; cannot reset budget')
            if not create and self.policy['schema_version'] == 2:
                db.execute('SELECT attempt_id,claimed_ns FROM sec_claims LIMIT 0')
                # A fresh process/object may inspect and settle old claims, but
                # never silently resume dispatch after a crash or restart.
                db.execute("UPDATE policy SET halted=COALESCE(halted,'reopen_requires_review') WHERE id=1")

    @property
    def policy(self):
        # Return a copy: callers cannot mutate prices after the ledger is bound.
        return json.loads(self._policy)

    @contextmanager
    def transaction(self):
        if self.policy['schema_version'] == 2:
            try:
                stat = self.path.stat()
            except OSError:
                raise BudgetError('existing rehearsal ledger unavailable; no reset') from None
            if (stat.st_dev, stat.st_ino) != self._file_identity:
                raise BudgetError('rehearsal ledger file replaced; no reset')
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=10, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def active(self, db):
        row = db.execute('SELECT hash,halted FROM policy WHERE id=1').fetchone()
        if row is None or row[0] != self.policy_hash or row[1]:
            raise BudgetError('pilot halted or policy mismatched')

    def require_active(self):
        with self.transaction() as db:
            self.active(db)

    def halt(self, reason='rehearsal_failure'):
        """Persist a fixed, non-secret failure code, including before any claim."""
        if reason not in {'rehearsal_failure', 'stage_timeout', 'pool_failure',
                          'invalid_request', 'invalid_response', 'configuration_drift',
                          'offline_network_attempt', 'fixture_failure', 'identity_mismatch'}:
            raise BudgetError('unsupported halt reason')
        with self.transaction() as db:
            db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (reason,))

    def record_sec_refusal(self, attempt_id, route, stage, code):
        """Atomically attach allowlisted context only to the first durable halt."""
        codes = {
            'sec_media_type': {'sec/directory', 'sec/submissions', 'sec/facts', 'sec/document'},
            'sec_recent_array_shape': {'sec/submissions'},
            'sec_accession_syntax': {'sec/submissions'},
            'sec_document_syntax': {'sec/submissions'},
        }
        if (type(code) is not str or code not in codes or type(route) is not str
                or route not in codes[code] or type(stage) is not str
                or stage not in {'evidence.sec', 'evidence.sec_metrics',
                                 'evidence.thesis_disclosures', 'evidence.filing_metrics'}
                or type(attempt_id) is not str):
            raise BudgetError('invalid SEC refusal metadata')
        with self.transaction() as db:
            row = db.execute('SELECT route,status FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            if row != (route, 'claimed'):
                raise BudgetError('SEC refusal requires its exact claimed attempt')
            first = db.execute("UPDATE policy SET halted='invalid_response' WHERE id=1 AND halted IS NULL").rowcount
            # Legacy ledgers remain readable without migration or cause invention.
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='first_sec_refusal'").fetchone()
            if first and exists:
                db.execute('INSERT INTO first_sec_refusal VALUES (1,?,?,?,?)',
                           (attempt_id, route, stage, code))

    def record_transport_failure(self, attempt_id, route, stage, code):
        from validation.pilot_live import TRANSPORT_FAILURE_CODES
        if (type(code) is not str or code not in TRANSPORT_FAILURE_CODES
                or type(route) is not str or type(stage) is not str
                or type(attempt_id) is not str
                or not ((route in {'sec/directory', 'sec/submissions', 'sec/facts', 'sec/document'}
                         and stage in {'evidence.sec', 'evidence.sec_metrics',
                                       'evidence.thesis_disclosures', 'evidence.filing_metrics'})
                        or (stage in {'valuation', 'macro', 'risk', 'market', 'quality',
                                      'question_answerer', 'synthesis'} and route == 'model/' + stage))):
            raise BudgetError('invalid transport failure metadata')
        with self.transaction() as db:
            row = db.execute('SELECT route,status FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            if row != (route, 'claimed'):
                raise BudgetError('transport failure requires exact claimed attempt')
            first = db.execute("UPDATE policy SET halted='post_claim_failure' WHERE id=1 AND halted IS NULL").rowcount
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='first_transport_failure'").fetchone()
            if first and exists:
                db.execute('INSERT INTO first_transport_failure VALUES (1,?,?,?,?)',
                           (attempt_id, route, stage, code))

    def _check_quotas(self, db, case_run, route, *, additional):
        if self.policy['schema_version'] != 2:
            return
        quotas = self.policy['quotas']
        case = db.execute('SELECT case_id FROM cases WHERE id=?', (case_run,)).fetchone()
        if case is None or route not in self.policy['prices']:
            raise BudgetError('unknown rehearsal case or route')
        limits = quotas['per_case'][case[0]]
        route_count = db.execute('SELECT COUNT(*) FROM attempts WHERE case_run=? AND route=?',
                                 (case_run, route)).fetchone()[0]
        if route_count + additional > limits[route]:
            raise BudgetError('rehearsal stage quota exceeded; slots cannot transfer')
        group = next(name for name, routes in quotas['groups'].items() if route in routes)
        routes = quotas['groups'][group]
        marks = ','.join('?' for _ in routes)
        case_count = db.execute(f'SELECT COUNT(*) FROM attempts WHERE case_run=? AND route IN ({marks})',
                                (case_run, *routes)).fetchone()[0]
        total = db.execute(f'SELECT COUNT(*) FROM attempts WHERE route IN ({marks})', routes).fetchone()[0]
        if case_count + additional > limits[group] or total + additional > quotas['overall'][group]:
            raise BudgetError('rehearsal category quota exceeded')

    def begin_case(self, case_id):
        if case_id not in self.policy['approved_case_ids']:
            raise BudgetError('case not explicitly approved')
        run_id = str(uuid4())
        with self.transaction() as db:
            self.active(db)
            if db.execute("SELECT 1 FROM cases WHERE status='active'").fetchone():
                raise BudgetError('only one case invocation may be active')
            try:
                db.execute("INSERT INTO cases VALUES (?,?,'active')", (run_id, case_id))
            except sqlite3.IntegrityError:
                raise BudgetError('case already consumed; rerun requires explicit review') from None
        return run_id

    def priced(self, route, input_tokens, output_tokens):
        price = self.policy['prices'].get(route)
        if price is None:
            raise BudgetError('unknown provider/model/operation price')
        if count(input_tokens) > price['maximum_input_tokens'] or count(output_tokens) > price['maximum_output_tokens']:
            raise BudgetError('input/output exceeds reviewed route bound')
        return (money(price['request_usd']) + count(input_tokens) * money(price['input_token_usd'])
                + count(output_tokens) * money(price['output_token_usd']))

    def reserve(self, case_run, route, *, input_bound, output_bound, request_sha256=None, stage=None):
        if stage is not None and type(stage) is not str:
            self.halt('invalid_request')
            raise BudgetError('invalid stage binding')
        if self.policy['schema_version'] == 2:
            price = self.policy['prices'].get(route)
            if (request_sha256 is None or price is None
                    or type(input_bound) is not int or type(output_bound) is not int
                    or input_bound != price['maximum_input_tokens']
                    or output_bound != price['maximum_output_tokens']):
                self.halt('invalid_request')
                raise BudgetError('rehearsal requires the full fixed route reservation')
        if request_sha256 is not None and (type(request_sha256) is not str
                or len(request_sha256) != 64
                or any(c not in '0123456789abcdef' for c in request_sha256)):
            if self.policy['schema_version'] == 2:
                self.halt('invalid_request')
            raise BudgetError('invalid request digest')
        failure = None
        attempt_id = str(uuid4())
        with self.transaction() as db:
            self.active(db)
            if not db.execute("SELECT 1 FROM cases WHERE id=? AND status='active'", (case_run,)).fetchone():
                raise BudgetError('case is not active')
            spent, attempts = db.execute('SELECT COALESCE(SUM(reserve),0),COUNT(*) FROM attempts').fetchone()
            try:
                cost = self.priced(route, input_bound, output_bound)
                self._check_quotas(db, case_run, route, additional=1)
                if 'stage_quotas' in self.policy:
                    case_id = db.execute('SELECT case_id FROM cases WHERE id=?', (case_run,)).fetchone()[0]
                    stages = self.policy['stage_quotas'][case_id]
                    limit = stages.get(stage, {}).get(route, 0) if type(stage) is str else 0
                    used = db.execute('SELECT COUNT(*) FROM stage_reservations s JOIN attempts a '
                                      'ON a.id=s.attempt_id WHERE a.case_run=? AND a.route=? AND s.stage=?',
                                      (case_run, route, stage)).fetchone()[0]
                    if not limit or used >= limit:
                        raise BudgetError('nontransferable stage quota exceeded')
                elif stage is not None:
                    raise BudgetError('stage binding is exclusive to freshness policy')
                if spent + cost > self.budget or attempts >= self.policy['maximum_attempts']:
                    raise BudgetError('reservation exceeds pilot cost/attempt limit')
            except BudgetError as exc:
                failure = str(exc)
                db.execute('UPDATE policy SET halted=? WHERE id=1', (failure,))
            else:
                db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,'pending',NULL,?)",
                           (attempt_id, case_run, route, cost, input_bound, output_bound, request_sha256))
                if 'stage_quotas' in self.policy:
                    db.execute('INSERT INTO stage_reservations VALUES (?,?)', (attempt_id, stage))
        if failure:
            raise BudgetError(failure)
        return attempt_id  # Bound dispatch must additionally claim this reservation.

    def claim_dispatch(self, attempt_id, *, case_run, route, request_sha256,
                       input_bound, output_bound):
        """Commit a one-shot claim before dispatch; ambiguous claims cannot replay."""
        try:
            return self._claim_dispatch(attempt_id, case_run=case_run, route=route,
                                        request_sha256=request_sha256,
                                        input_bound=input_bound, output_bound=output_bound)
        except RateLimitDelay:
            raise
        except BudgetError:
            if self.policy['schema_version'] == 2:
                self.halt('invalid_request')
            raise

    def _claim_dispatch(self, attempt_id, *, case_run, route, request_sha256,
                        input_bound, output_bound):
        count(input_bound)
        count(output_bound)
        with self.transaction() as db:
            self.active(db)
            row = db.execute('SELECT case_run,route,request_sha256,input_bound,output_bound,status '
                             'FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            expected = (case_run, route, request_sha256, input_bound, output_bound, 'pending')
            if row is None or row[2] is None or tuple(row) != expected:
                raise BudgetError('dispatch binding mismatch or reservation already claimed')
            if not db.execute("SELECT 1 FROM cases WHERE id=? AND status='active'", (case_run,)).fetchone():
                raise BudgetError('case is not active')
            self._check_quotas(db, case_run, route, additional=0)
            if (self.policy['schema_version'] == 2
                    and route in self.policy['quotas']['groups']['sec']):
                now = time.monotonic_ns()
                recent = db.execute('SELECT claimed_ns FROM sec_claims WHERE claimed_ns>? ORDER BY claimed_ns',
                                    (now - 1_000_000_000,)).fetchall()
                if len(recent) >= self.policy['quotas']['sec_per_second']:
                    raise RateLimitDelay(max(0.001, (recent[0][0] + 1_000_000_000 - now) / 1_000_000_000))
                db.execute('INSERT INTO sec_claims VALUES (?,?)', (attempt_id, now))
            db.execute("UPDATE attempts SET status='claimed' WHERE id=?", (attempt_id,))

    def claim_native_dispatch(self, attempt_id, *, case_run, route, request_sha256):
        """Consume an approved claim once across gates/contexts, before native I/O."""
        if self.policy.get('purpose') == 'approved_ordinary_twelve_case_pilot':
            from validation.ordinary_native_ledger import OrdinaryNativeLedger
            if type(self) is not OrdinaryNativeLedger:
                raise BudgetError('ordinary native intent requires its fresh-only ledger')
        if self.policy.get('purpose') not in {'approved_six_case_pilot', 'approved_source_monitoring_pilot',
                                                 'approved_two_source_diagnostic_capture', 'approved_eps_source_adequacy_capture', 'approved_monitoring_freshness_pilot',
                                                 'approved_ordinary_twelve_case_pilot'}:
            raise BudgetError('native dispatch requires approved policy')
        with self.transaction() as db:
            self.active(db)
            row = db.execute('SELECT case_run,route,request_sha256,status FROM attempts WHERE id=?',
                             (attempt_id,)).fetchone()
            if row is None or tuple(row) != (case_run, route, request_sha256, 'claimed'):
                raise BudgetError('native dispatch binding mismatch')
            db.execute('CREATE TABLE IF NOT EXISTS native_dispatches (attempt_id TEXT PRIMARY KEY)')
            if db.execute('SELECT 1 FROM native_dispatches WHERE attempt_id=?', (attempt_id,)).fetchone():
                raise BudgetError('native dispatch already consumed')
            db.execute('INSERT INTO native_dispatches VALUES (?)', (attempt_id,))

    def halt_dispatch(self, attempt_id):
        """Persist a caught post-claim failure without releasing claim or reserve.

        A hard process/disk failure can still leave a claimed ambiguous attempt;
        this handles exceptions the cooperating transport can actually catch.
        """
        with self.transaction() as db:
            row = db.execute('SELECT request_sha256,status FROM attempts WHERE id=?',
                             (attempt_id,)).fetchone()
            if row is None or row[0] is None or row[1] not in ('claimed', 'unknown', 'settled'):
                raise BudgetError('post-claim failure requires a claimed bound attempt')
            db.execute("UPDATE policy SET halted=COALESCE(halted,'post_claim_failure') WHERE id=1")

    def settle(self, attempt_id, *, input_tokens=None, output_tokens=None):
        failure = None
        with self.transaction() as db:
            row = db.execute('SELECT route,input_bound,output_bound,status,reserve,request_sha256 FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            if row is None or row[3] != ('claimed' if row[5] is not None else 'pending'):
                raise BudgetError('attempt missing or already settled')
            try:
                actual = self.priced(row[0], input_tokens, output_tokens)
                if input_tokens > row[1] or output_tokens > row[2] or actual > row[4]:
                    raise BudgetError('usage exceeded reserved bound')
            except BudgetError:
                failure = 'missing_or_excess_usage'
                db.execute('UPDATE policy SET halted=COALESCE(halted,?) WHERE id=1', (failure,))
                db.execute("UPDATE attempts SET status='unknown' WHERE id=?", (attempt_id,))
            else:
                db.execute("UPDATE attempts SET status='settled',actual=? WHERE id=?", (actual, attempt_id))
        if failure:
            raise BudgetError(failure)

    def finish_case(self, case_run):
        with self.transaction() as db:
            self.active(db)
            if db.execute("SELECT 1 FROM attempts WHERE case_run=? AND status!='settled'", (case_run,)).fetchone():
                raise BudgetError('unresolved/late attempts remain reserved; case cannot finish')
            if db.execute("UPDATE cases SET status='complete' WHERE id=? AND status='active'", (case_run,)).rowcount != 1:
                raise BudgetError('case is not active')

    def summary(self):
        with self.transaction() as db:
            reserved, actual, total, pending = db.execute("SELECT COALESCE(SUM(reserve),0),COALESCE(SUM(actual),0),COUNT(*),COALESCE(SUM(status!='settled'),0) FROM attempts").fetchone()
            halted = db.execute('SELECT halted FROM policy WHERE id=1').fetchone()[0]
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='first_sec_refusal'").fetchone()
            refusal = db.execute('SELECT attempt_id,route,stage,code FROM first_sec_refusal WHERE id=1').fetchone() if exists else None
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='first_transport_failure'").fetchone()
            transport = db.execute('SELECT attempt_id,route,stage,code FROM first_transport_failure WHERE id=1').fetchone() if exists else None
        return dict(first_transport_failure=dict(zip(('attempt_id', 'route', 'stage', 'code'), transport)) if transport else None,
                    first_sec_refusal=dict(zip(('attempt_id', 'route', 'stage', 'code'), refusal)) if refusal else None,
                    policy_sha256=self.policy_hash, budget_nanousd=self.budget,
                    reserved_nanousd=reserved, known_actual_nanousd=actual,
                    attempts=total, unresolved_attempts=pending, halted=halted,
                    executable_provider_adapter=self.policy.get('purpose') in {'approved_six_case_pilot', 'approved_source_monitoring_pilot',
                                                 'approved_two_source_diagnostic_capture', 'approved_eps_source_adequacy_capture', 'approved_monitoring_freshness_pilot'},
                    hard_usd_cap_established=False)


def preflight(policy, case_id):
    """Produce one fresh, offline-only artifact without consuming a ledger case."""
    validate_policy(policy)
    if case_id not in policy['approved_case_ids']:
        raise BudgetError('case not explicitly approved')
    return dict(artifact_id=str(uuid4()), case_id=case_id,
                policy_sha256=digest(policy), setup_sha256=(policy['setup_sha256']
                    if policy.get('purpose') == 'approved_ordinary_twelve_case_pilot' else setup_binding()),
                configuration_version=policy['configuration_version'],
                execution_allowed=False, hard_usd_cap_established=False,
                blockers=['No audited provider transport integration',
                          'Credentials, pricing, charge coverage and bounds require independent verification',
                          'User spending approval is not authenticated by this offline artifact'])


def main():
    parser = argparse.ArgumentParser(description='Offline budget preflight ONLY; cannot execute capture')
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--case', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = preflight(json.loads(args.policy.read_text()), args.case)
        with args.output.open('x') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
    except (BudgetError, OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
