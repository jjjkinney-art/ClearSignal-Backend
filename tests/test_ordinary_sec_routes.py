import hashlib
import json
import sqlite3
import pytest
from validation.ordinary_pilot_accounting import OfflineAccounting, AccountingError
from validation.ordinary_pilot_contract import ISSUERS
from validation.ordinary_wire_rehearsal import rehearse_sec

STAGE = 'evidence.thesis_disclosures'


@pytest.mark.parametrize('ticker', ISSUERS)
@pytest.mark.parametrize('stage', [STAGE, 'evidence.filing_metrics'])
def test_directory_submissions_document_sequence(tmp_path, ticker, stage):
    book = OfflineAccounting(tmp_path / 'offline.db')
    case = ticker + ':core_thesis'
    receipts = [rehearse_sec(book, case, stage=stage, route=route)['receipt']
                for route in ('sec/directory', 'sec/submissions', 'sec/document')]
    assert all(r['body_bytes'] > 0 for r in receipts)
    assert receipts[-1]['url'].endswith('/000095017026012345/issuer-20251231.htm')
    assert book.summary()['outcomes'] == {'success': 3}


@pytest.mark.parametrize('source_case,source_stage', [
    ('NPK:core_thesis', 'evidence.sec'), ('GOOGL:core_thesis', STAGE)])
def test_unrelated_submission_does_not_authorize_document(tmp_path, source_case, source_stage):
    book = OfflineAccounting(tmp_path / 'offline.db')
    rehearse_sec(book, source_case, stage=source_stage, route='sec/submissions')
    with pytest.raises(AccountingError, match='same-case same-stage'):
        rehearse_sec(book, 'NPK:core_thesis', stage=STAGE, route='sec/document')
    assert book.summary()['halt'] == 'attempt_failure'


@pytest.mark.parametrize('mutation', ['hash', 'issuer', 'path'])
def test_corrupted_or_unsafe_submission_refused(tmp_path, mutation):
    book = OfflineAccounting(tmp_path / 'offline.db')
    case = 'NPK:core_thesis'
    rehearse_sec(book, case, stage=STAGE, route='sec/submissions')
    with sqlite3.connect(book.path) as db:
        raw, = db.execute('SELECT body FROM bodies').fetchone()
        data = json.loads(raw)
        if mutation == 'issuer':
            data['cik'] = '0001652044'
        else:
            data['filings']['recent']['primaryDocument'] = ['../../other.htm']
        body = json.dumps(data).encode()
        digest = 'wrong' if mutation == 'hash' else hashlib.sha256(body).hexdigest()
        db.execute('UPDATE bodies SET body=?,sha256=?', (body, digest))
    with pytest.raises(AccountingError):
        rehearse_sec(book, case, stage=STAGE, route='sec/document')
    assert book.summary()['outcomes'] == {'failure': 1, 'success': 1}


def test_threshold_document_route_stays_forbidden(tmp_path):
    book = OfflineAccounting(tmp_path / 'offline.db')
    with pytest.raises(AccountingError, match='scope'):
        rehearse_sec(book, 'NPK:decision_threshold', stage=STAGE, route='sec/document')
    assert book.summary()['outcomes'] == {}
