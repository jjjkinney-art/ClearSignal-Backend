"""Internal fake socket backend. Invented protocol bytes, never DNS or sockets."""
import json

import httpcore

from validation.pilot_fixtures import model_fixture, sec_fixture


class SyntheticStream:
    def __init__(self, owner):
        self.owner = owner
        self.request = bytearray()
        self.response = None

    def write(self, buffer, timeout=None):
        self.request.extend(buffer)

    def read(self, max_bytes, timeout=None):
        owner = self.owner
        if owner.once({'wire_read_failure'}):
            raise httpcore.ReadError('invented read failure')
        if self.response is None:
            head, body = bytes(self.request).split(b'\r\n\r\n', 1)
            first = head.split(b'\r\n')[0]
            method, target, _ = first.decode().split(' ')
            if method == 'POST':
                data = model_fixture(owner.stage.get(), owner.case['identity'])
                data['choices'][0]['message'].update(refusal=None, annotations=[])
                media, content = 'application/json', json.dumps(data).encode()
            else:
                route = ('sec/directory' if target.endswith('company_tickers.json') else
                         'sec/submissions' if '/submissions/' in target else
                         'sec/facts' if '/companyfacts/' in target else 'sec/document')
                media, content = sec_fixture(route, owner.case['identity'], owner.identities)
                if route == 'sec/directory':
                    data = json.loads(content)
                    data['999'] = {'ticker': 'OTHER', 'cik_str': 123456, 'title': 'Invented unrelated issuer'}
                    content = json.dumps(data).encode()
                elif route == 'sec/submissions':
                    data = json.loads(content)
                    # Accession submitter can legitimately differ from issuer CIK.
                    data['filings']['recent']['accessionNumber'] = ['0000950170-26-012345']
                    data['filings']['recent']['primaryDocument'] = ['issuer-20251231.htm']
                    content = json.dumps(data).encode()
            status = b'200 OK'
            extra = b''
            if owner.once({'wire_redirect'}):
                status, extra = b'302 Found', b'Location: https://unreviewed.invalid/\r\n'
            self.response = (b'HTTP/1.1 ' + status + b'\r\nContent-Type: ' + media.encode()
                             + b'\r\nContent-Length: ' + str(len(content)).encode()
                             + b'\r\nConnection: close\r\n' + extra + b'\r\n' + content)
        result, self.response = self.response[:max_bytes], self.response[max_bytes:]
        return result

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self

    def get_extra_info(self, info):
        return None

    def close(self):
        pass


class SyntheticNetworkBackend:
    def __init__(self, owner):
        self.owner = owner

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self.owner.once({'wire_connect_failure'}):
            raise httpcore.ConnectError('invented connection failure')
        return SyntheticStream(self.owner)

    def connect_unix_socket(self, *args, **kwargs):
        raise AssertionError('Unix sockets prohibited')
