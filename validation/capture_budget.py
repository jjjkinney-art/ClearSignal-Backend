"""Offline attempt-accounting foundation, NOT an executable provider budget cap.

The offline fixture transport reserves and claims each simulated attempt.
No production/capture runner imports this module. No network or app imports.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
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
    if not isinstance(policy, dict) or policy.get('schema_version') != 1:
        raise BudgetError('unsupported policy')
    for key in ('pilot_id', 'approval_reference', 'configuration_version', 'pricing_review_reference'):
        if not isinstance(policy.get(key), str) or not policy[key].strip():
            raise BudgetError(f'{key} is required')
    budget = money(policy.get('budget_usd'), round_up=False)
    if budget <= 0 or count(policy.get('maximum_attempts')) < 1:
        raise BudgetError('positive budget and maximum_attempts required')
    cases = policy.get('approved_case_ids')
    if (not isinstance(cases, list) or not 1 <= len(cases) <= 6
            or any(not isinstance(c, str) or c.count(':') != 1 for c in cases)
            or len(set(cases)) != len(cases)):
        raise BudgetError('one to six distinct approved cases required')
    validate_cases(cases)
    if policy.get('setup_sha256') != setup_binding():
        raise BudgetError('setup binding absent or changed')
    rates = policy.get('prices')
    if not isinstance(rates, dict) or not rates:
        raise BudgetError('explicit reviewed prices required')
    for route, price in rates.items():
        if not isinstance(route, str) or not route or not isinstance(price, dict):
            raise BudgetError('invalid priced route')
        if price.get('currency') != 'USD' or price.get('all_incremental_charges_accounted') is not True:
            raise BudgetError('unknown currency or provider charges')
        if set(price) != {'currency', 'all_incremental_charges_accounted', 'request_usd', 'input_token_usd', 'output_token_usd', 'maximum_input_tokens', 'maximum_output_tokens'}:
            raise BudgetError('unsupported charge categories')
        count(price.get('maximum_input_tokens'))
        count(price.get('maximum_output_tokens'))
        for key in ('request_usd', 'input_token_usd', 'output_token_usd'):
            money(price[key])
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
        with self.transaction() as db:
            if create:
                db.execute(f'PRAGMA user_version={LEDGER_SCHEMA_VERSION}')
                db.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT NOT NULL, halted TEXT)')
                db.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, case_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, case_run TEXT NOT NULL, route TEXT NOT NULL, reserve INTEGER NOT NULL, input_bound INTEGER NOT NULL, output_bound INTEGER NOT NULL, status TEXT NOT NULL, actual INTEGER, request_sha256 TEXT)')
            else:
                # No implicit migrations or resets, including prior accounting-only ledgers.
                if db.execute('PRAGMA user_version').fetchone()[0] != LEDGER_SCHEMA_VERSION:
                    raise BudgetError('unsupported ledger schema; explicit review required')
                db.execute('SELECT id,case_id,status FROM cases LIMIT 0')
                db.execute('SELECT id,case_run,route,reserve,input_bound,output_bound,status,actual,request_sha256 FROM attempts LIMIT 0')
            row = db.execute('SELECT hash FROM policy WHERE id=1').fetchone()
            if row is None and not create:
                raise BudgetError('existing ledger has no policy; refusing budget reset')
            if row is None:
                db.execute('INSERT INTO policy VALUES (1,?,NULL)', (self.policy_hash,))
            elif row[0] != self.policy_hash:
                raise BudgetError('ledger policy/configuration mismatch; cannot reset budget')

    @property
    def policy(self):
        # Return a copy: callers cannot mutate prices after the ledger is bound.
        return json.loads(self._policy)

    @contextmanager
    def transaction(self):
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

    def reserve(self, case_run, route, *, input_bound, output_bound, request_sha256=None):
        if request_sha256 is not None and (type(request_sha256) is not str
                or len(request_sha256) != 64
                or any(c not in '0123456789abcdef' for c in request_sha256)):
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
                if spent + cost > self.budget or attempts >= self.policy['maximum_attempts']:
                    raise BudgetError('reservation exceeds pilot cost/attempt limit')
            except BudgetError as exc:
                failure = str(exc)
                db.execute('UPDATE policy SET halted=? WHERE id=1', (failure,))
            else:
                db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,'pending',NULL,?)",
                           (attempt_id, case_run, route, cost, input_bound, output_bound, request_sha256))
        if failure:
            raise BudgetError(failure)
        return attempt_id  # Bound dispatch must additionally claim this reservation.

    def claim_dispatch(self, attempt_id, *, case_run, route, request_sha256,
                       input_bound, output_bound):
        """Commit a one-shot claim before dispatch; ambiguous claims cannot replay."""
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
            db.execute("UPDATE attempts SET status='claimed' WHERE id=?", (attempt_id,))

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
                db.execute('UPDATE policy SET halted=? WHERE id=1', (failure,))
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
        return dict(policy_sha256=self.policy_hash, budget_nanousd=self.budget,
                    reserved_nanousd=reserved, known_actual_nanousd=actual,
                    attempts=total, unresolved_attempts=pending, halted=halted,
                    executable_provider_adapter=False, hard_usd_cap_established=False)


def preflight(policy, case_id):
    """Produce one fresh, offline-only artifact without consuming a ledger case."""
    validate_policy(policy)
    if case_id not in policy['approved_case_ids']:
        raise BudgetError('case not explicitly approved')
    return dict(artifact_id=str(uuid4()), case_id=case_id,
                policy_sha256=digest(policy), setup_sha256=setup_binding(),
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
