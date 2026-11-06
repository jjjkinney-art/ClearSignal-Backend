"""Invented SEC responses for the socket-denied ordinary rehearsal backend.

NOT real filings, facts or directory data. Public tickers, CIKs and registrant
names are used only so identity checks run; every figure, filing row, document
sentence and accession is invented. Nothing here is research evidence.

The backend sits beneath the ordinary gate's ScopedBackend exactly where a
native proxy connection would: it answers one CONNECT per exchange, then serves
one HTTP/1.1 response through HTTPX/httpcore/h11. It opens no socket or DNS.
"""
import json
import re

import httpcore

# Registrant names as SEC lists them; identity only, not evidence.
REGISTRANTS = {
    'NPK': (80172, 'NATIONAL PRESTO INDUSTRIES INC'),
    'GOOGL': (1652044, 'Alphabet Inc.'),
    'INGR': (1046257, 'Ingredion Inc'),
    'NNBR': (918541, 'NN INC'),
    'AMZN': (1018724, 'AMAZON COM INC'),
    'MAN': (871763, 'ManpowerGroup Inc.'),
    # Run-3 cohort (identity only; every figure below remains invented).
    'SCCO': (1001838, 'SOUTHERN COPPER CORP/'),
    'BX': (1393818, 'Blackstone Inc.'),
    'LNC': (59558, 'LINCOLN NATIONAL CORP'),
    'LVS': (1300514, 'LAS VEGAS SANDS CORP'),
    'USCB': (1901637, 'USCB FINANCIAL HOLDINGS, INC.'),
    'BWMX': (1788257, 'BETTERWARE DE MEXICO, S.A.P.I. DE C.V'),
}
_UNRELATED = [(9900001, 'INVA', 'Invented Unrelated Registrant A'),
              (9900002, 'INVB', 'Invented Unrelated Registrant B')]
SYNTHETIC_FAULTS = frozenset({'connect_failure', 'read_failure', 'redirect', 'oversize', 'stall', 'slow'})


def _ticker(cik):
    return next(t for t, (number, _) in REGISTRANTS.items() if number == cik)


def directory():
    rows = [(cik, ticker, name) for ticker, (cik, name) in REGISTRANTS.items()] + _UNRELATED
    return {str(i): {'cik_str': cik, 'ticker': ticker, 'title': name}
            for i, (cik, ticker, name) in enumerate(rows)}


def _filings(cik):
    """Multi-row recent filings, newest first, with realistic irregularities."""
    t = _ticker(cik).lower()
    own = f'{cik:010d}'
    agent = '0000950170'  # A filer agent's accession prefix differs from the issuer CIK.
    rows = [
        ('10-Q', '2026-08-04', '2026-06-30', f'{agent}-26-071203', f'{t}-20260630.htm', ''),
        ('8-K', '2026-07-30', '2026-07-30', f'{own}-26-000041', f'{t}-ex991_20260730.htm', '2.02,9.01'),
        ('4', '2026-06-02', '2026-05-29', f'{own}-26-000037', 'xslF345X05/wk-form4_1748900000.xml', ''),
        ('10-Q', '2026-05-05', '2026-03-31', f'{agent}-26-048811', f'{t}-20260331.htm', ''),
        ('DEF 14A', '2026-03-27', '2026-05-14', f'{agent}-26-031177', f'{t}-def14a_2026.htm', ''),
        ('10-K', '2026-02-24', '2025-12-31', f'{agent}-26-019334', f'{t}-20251231.htm', ''),
        # A supported form whose filename is not fetchable stays excluded.
        ('8-K', '2026-02-10', '2026-02-10', f'{own}-26-000009', 'not a fetchable name', '5.02'),
        ('SC 13G/A', '2026-02-06', '', f'{agent}-26-012001', f'{t}-sc13ga.htm', ''),
        ('10-Q', '2025-11-04', '2025-09-30', f'{agent}-25-140022', f'{t}-20250930.htm', ''),
        ('10-K', '2025-02-25', '2024-12-31', f'{agent}-25-018875', f'{t}-20241231.htm', ''),
    ]
    keys = ('form', 'filingDate', 'reportDate', 'accessionNumber', 'primaryDocument', 'items')
    recent = {key: [row[i] for row in rows] for i, key in enumerate(keys)}
    recent['primaryDocDescription'] = [row[0] for row in rows]
    return recent


def submissions(cik):
    ticker = _ticker(cik)
    return {'cik': f'{cik:010d}', 'entityType': 'operating', 'name': REGISTRANTS[ticker][1],
            'tickers': [ticker], 'exchanges': ['Invented'],
            'filings': {'recent': _filings(cik), 'files': []}}


def companyfacts(cik):
    """Invented annual and quarterly us-gaap facts bound to the invented filings."""
    ticker = _ticker(cik)
    recent = _filings(cik)
    accession = {(form, period): accn for form, period, accn in
                 zip(recent['form'], recent['reportDate'], recent['accessionNumber'])}
    filed = {accn: date for accn, date in zip(recent['accessionNumber'], recent['filingDate'])}
    scale = 1_000_000 * (1 + sum(map(ord, ticker)) % 7)
    concepts = {
        'Revenues': (900, 1000, 1080), 'CostOfRevenue': (540, 590, 630),
        'OperatingIncomeLoss': (95, 120, 131), 'NetIncomeLoss': (70, 88, 97),
        'NetCashProvidedByUsedInOperatingActivities': (110, 126, 140),
        'PaymentsToAcquirePropertyPlantAndEquipment': (35, 41, 44),
    }
    balance = {'Assets': (2100, 2240, 2330), 'Liabilities': (1050, 1090, 1120),
               'StockholdersEquity': (1050, 1150, 1210)}
    facts = {}
    for name, values in {**concepts, **balance}.items():
        rows = []
        for year, value in zip((2023, 2024, 2025), values):
            end = f'{year}-12-31'
            own = accession.get(('10-K', end))
            # 2023 appears only as a comparative in the FY2024 10-K.
            accn = own or accession[('10-K', '2024-12-31')]
            row = {'end': end, 'val': value * scale, 'accn': accn, 'fy': year if own else 2024,
                   'fp': 'FY', 'form': '10-K', 'filed': filed[accn]}
            if name in concepts:
                row['start'] = f'{year}-01-01'
            rows.append(row)
        # Each 10-Q reports its quarter and, as a comparative under the same
        # accession, the same quarter of the prior year.
        for period, factor in (('2026-03-31', 0.26), ('2026-06-30', 0.27)):
            accn = accession[('10-Q', period)]
            for year, scaled in ((2026, factor), (2025, factor * 0.93)):
                end = f'{year}' + period[4:]
                row = {'end': end, 'val': int(values[-1] * scale * scaled), 'accn': accn,
                       'fy': 2026, 'fp': 'Q1' if period.endswith('03-31') else 'Q2', 'form': '10-Q',
                       'filed': filed[accn]}
                if name in concepts:
                    row['start'] = f'{year}-' + ('01-01' if period.endswith('03-31') else '04-01')
                rows.append(row)
        facts[name] = {'label': name, 'description': 'Invented rehearsal value', 'units': {'USD': rows}}
    return {'cik': cik, 'entityName': REGISTRANTS[ticker][1], 'facts': {'us-gaap': facts}}


def filing_document(cik, name):
    ticker = _ticker(cik)
    registrant = REGISTRANTS[ticker][1]
    quarterly = re.search(r'-2026(0331|0630)\.htm$|-20250930\.htm$', name) is not None
    title = 'Quarterly Report (Form 10-Q)' if quarterly else 'Annual Report (Form 10-K)'
    risk_heading = 'Part II. Item 1A. Risk Factors' if quarterly else 'Item 1A. Risk Factors'
    business = '' if quarterly else (
        '<h2>Item 1. Business</h2>'
        f'<p>{registrant} designs, manufactures and sells products to customers through its operating segments. '
        'This invented rehearsal filing text exists only to exercise parsing and supplies no real evidence.</p>')
    return f'''<html><head><title>{registrant} {title} (invented rehearsal text)</title></head><body>
<h1>{registrant}</h1><p>{title}. Invented rehearsal document; not an SEC filing.</p>
{business}
<h2>{risk_heading}</h2>
<p>Customer demand for our products may decline, which could adversely affect our revenue and operating results.</p>
<p>Increases in energy, labor and raw material costs could adversely affect our margins.</p>
<p>Disruption at a significant facility could interrupt production and adversely affect our results.</p>
<h2>Item 7. Management's Discussion and Analysis</h2>
<p>Revenue and operating income changed during the period for invented rehearsal reasons only.</p>
<h2>Item 8. Financial Statements</h2><p>Invented placeholder.</p>
</body></html>'''.encode('utf-8')


def respond(path):
    """(status, media type, body) for one GET path, or a 404."""
    match = re.fullmatch(r'/submissions/CIK([0-9]{10})\.json', path)
    if match and int(match[1]) in {c for c, _ in REGISTRANTS.values()}:
        return 200, 'application/json', json.dumps(submissions(int(match[1]))).encode()
    match = re.fullmatch(r'/api/xbrl/companyfacts/CIK([0-9]{10})\.json', path)
    if match and int(match[1]) in {c for c, _ in REGISTRANTS.values()}:
        return 200, 'application/json', json.dumps(companyfacts(int(match[1]))).encode()
    if path == '/files/company_tickers.json':
        return 200, 'application/json', json.dumps(directory()).encode()
    match = re.fullmatch(r'/Archives/edgar/data/([0-9]+)/([0-9]{18})/([^/]+)', path)
    if match and int(match[1]) in {c for c, _ in REGISTRANTS.values()}:
        listed = {(accn.replace('-', ''), doc) for accn, doc in
                  zip(_filings(int(match[1]))['accessionNumber'], _filings(int(match[1]))['primaryDocument'])}
        if (match[2], match[3]) in listed:
            return 200, 'text/html', filing_document(int(match[1]), match[3])
    return 404, 'text/html', b'<html>Invented not found</html>'


class _Tunnel:
    def __init__(self, backend):
        self.backend, self.request, self.response, self.offset = backend, bytearray(), None, 0

    def write(self, buffer, timeout=None):
        self.request.extend(buffer)

    def read(self, max_bytes, timeout=None):
        if self.response is None:
            head = bytes(self.request).split(b'\r\n\r\n', 1)[0].decode('ascii')
            method, path, _ = head.split('\r\n')[0].split(' ')
            self.backend.requests.append((method, path))
            if self.backend.take_fault(path, 'stall'):
                import threading
                threading.Event().wait()  # never set: a hung peer
            # A slow but live peer: the complete response arrives in 512-byte
            # reads one second apart (finite, unlike a stall).
            self.slow = self.backend.take_fault(path, 'slow')
            fault = self.backend.take_fault(path, 'read_failure')
            status, media, body = respond(path) if method == 'GET' else (405, 'text/plain', b'')
            extra = b''
            if self.backend.take_fault(path, 'redirect'):
                status, extra = 302, b'Location: https://www.sec.gov/invented-elsewhere\r\n'
            if self.backend.take_fault(path, 'oversize'):
                body = body + b' ' * (16 * 1024 * 1024 + 1 - len(body))
            reason = {200: b'OK', 302: b'Found', 404: b'Not Found', 405: b'Method Not Allowed'}[status]
            self.response = (b'HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                             b'Connection: close\r\n' % (status, reason, media.encode(), len(body))
                             + extra + b'\r\n' + body)
            if fault:
                # Headers and part of the body arrive, then the read fails.
                self.response = self.response[:len(self.response) // 2]
                self.fail_at_end = True
        if self.offset >= len(self.response) and getattr(self, 'fail_at_end', False):
            raise httpcore.ReadError('invented read failure')
        if getattr(self, 'slow', False):
            import time
            time.sleep(1.0)
            max_bytes = min(max_bytes, 512)
        chunk = self.response[self.offset:self.offset + max_bytes]
        self.offset += len(chunk)
        return chunk

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self

    def get_extra_info(self, info):
        return None

    def close(self):
        pass


class _Proxy:
    """Answers the CONNECT the scoped stream validates, then the TLS hand-off."""
    def __init__(self, backend):
        self.tunnel, self.remaining = _Tunnel(backend), b'HTTP/1.1 200 Connection established\r\n\r\n'

    def write(self, buffer, timeout=None):
        pass

    def read(self, max_bytes, timeout=None):
        chunk, self.remaining = self.remaining[:max_bytes], self.remaining[max_bytes:]
        return chunk

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self.tunnel

    def get_extra_info(self, info):
        return None

    def close(self):
        pass


class OrdinarySyntheticSEC:
    """Synthetic network backend with at most one injected fault.

    ``fault`` is (kind, selector, occurrence). For read_failure, redirect,
    oversize and stall the selector is a regex matched against the request
    path and the fault fires on its ``occurrence``-th match. For
    connect_failure (no path is visible before CONNECT) the selector is
    ignored and the fault fires on the ``occurrence``-th connection.
    A stall blocks that exchange's thread indefinitely, like a hung peer; a
    slow fault delivers the complete response in 512-byte reads one second apart.
    """
    def __init__(self, fault=None):
        if fault is not None and (type(fault) is not tuple or len(fault) != 3
                                  or fault[0] not in SYNTHETIC_FAULTS
                                  or type(fault[1]) is not str or type(fault[2]) is not int or fault[2] < 1):
            raise ValueError('unknown synthetic fault')
        self.fault, self.fired, self.requests, self.connects, self.matches = fault, False, [], 0, 0

    def take_fault(self, path, kind):
        if self.fault is None or self.fired or self.fault[0] != kind or not re.search(self.fault[1], path):
            return False
        self.matches += 1
        if self.matches != self.fault[2]:
            return False
        self.fired = True
        return True

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (host, port) != ('proxy', 8080):
            raise AssertionError('unexpected proxy destination')
        self.connects += 1
        if (self.fault is not None and self.fault[0] == 'connect_failure' and not self.fired
                and self.connects == self.fault[2]):
            self.fired = True
            raise httpcore.ConnectError('invented proxy connection failure')
        return _Proxy(self)

    def connect_unix_socket(self, *args, **kwargs):
        raise AssertionError('Unix sockets prohibited')
