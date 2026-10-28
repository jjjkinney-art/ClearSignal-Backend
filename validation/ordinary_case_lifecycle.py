"""Offline case state machine; no execution or network authority.

Used with a new rehearsal ledger. Accounting operations enforce the attached
lifecycle inside their write transactions. No native executor is supplied.
"""
import sqlite3
from .ordinary_pilot_accounting import AccountingError
from .ordinary_pilot_contract import CASES


class OfflineCaseLifecycle:
    def __init__(self, book):
        self.book = book
        book._lifecycle_required = True
        with book._connect() as db:
            db.execute('CREATE TABLE case_lifecycle (position INTEGER PRIMARY KEY, '
                       'case_id TEXT UNIQUE, status TEXT, started REAL)')
            db.executemany('INSERT INTO case_lifecycle VALUES (?,?,?,NULL)',
                           [(i, c, 'scheduled') for i, c in enumerate(CASES)])

    def begin(self, case):
        if self.book._locally_sealed:
            raise AccountingError('locally sealed')
        reason = ''
        with self.book._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            active = db.execute("SELECT 1 FROM case_lifecycle WHERE status='running'").fetchone()
            next_case = db.execute("SELECT case_id FROM case_lifecycle WHERE status='scheduled' ORDER BY position LIMIT 1").fetchone()
            if halt or active or not next_case or next_case[0] != case:
                reason = halt or 'case_order'
            elif self.book.clock() - self.book.started >= 480:
                reason = 'deadline'
            if reason:
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN ? ELSE halt END", (reason,))
            else:
                db.execute("UPDATE case_lifecycle SET status='running',started=? WHERE case_id=?",
                           (self.book.clock(), case))
        if reason:
            self.book.seal_local()
            raise AccountingError(reason)

    def finish(self, case, *, status):
        if type(status) is not str or status not in {'complete', 'partial_gap', 'error'}:
            with self.book._connect() as db:
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN 'invalid_case_outcome' ELSE halt END")
            self.book.seal_local()
            raise AccountingError('invalid case outcome')
        reason = ''
        with self.book._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,started FROM case_lifecycle WHERE case_id=?', (case,)).fetchone()
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            if not row or row[0] != 'running':
                reason = halt or 'case_not_running'
            else:
                now = self.book.clock()
                pending = db.execute("SELECT COUNT(*) FROM attempts WHERE case_id=? AND outcome='pending'", (case,)).fetchone()[0]
                failed = db.execute("SELECT COUNT(*) FROM attempts WHERE case_id=? AND outcome!='success'", (case,)).fetchone()[0]
                limit = 30 if case.endswith(':core_thesis') else 20
                reason = halt
                if not reason and now < row[1]:
                    reason = 'clock_drift'
                if not reason and (now - self.book.started >= 480 or now - row[1] >= limit):
                    reason = 'case_deadline'
                if not reason and (pending or failed):
                    reason = 'unresolved_or_failed_attempt'
                if not reason and status == 'error':
                    reason = 'case_error'
                db.execute('UPDATE case_lifecycle SET status=? WHERE case_id=?',
                           ('halted' if reason else status, case))
            if reason:
                db.execute("UPDATE state SET halt=CASE WHEN halt='' THEN ? ELSE halt END", (reason,))
        if reason:
            self.book.seal_local()
            raise AccountingError(reason)

    def finalize(self):
        """Produce all twelve denominator rows; never convert gaps into passes."""
        self.book.seal_local()
        with self.book._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            halt = db.execute('SELECT halt FROM state').fetchone()[0]
            unfinished = db.execute("SELECT COUNT(*) FROM case_lifecycle WHERE status IN ('running','scheduled')").fetchone()[0]
            if unfinished and not halt:
                halt = 'incomplete_run'
                db.execute('UPDATE state SET halt=?', (halt,))
            db.execute("UPDATE case_lifecycle SET status='halted' WHERE status='running'")
            db.execute("UPDATE case_lifecycle SET status='not_run_after_halt' WHERE status='scheduled'")
            rows = [{'case_id': c, 'status': s} for c, s in db.execute('SELECT case_id,status FROM case_lifecycle ORDER BY position')]
        return {'cases': rows, 'denominator': 12, 'halt': halt,
                'execution_authorized': False, 'quality_pass_rate': None, 'launch_ready': False}
