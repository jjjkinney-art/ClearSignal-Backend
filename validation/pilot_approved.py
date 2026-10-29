"""Approval-gated frozen pilot. No credential lookup or approval generation.

Configuration is a separately reviewed NON-SECRET substitution contract. This
module cannot verify a human's identity: the supplied approval file must come
from the authorized operator after the separate spending decision.
"""
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
import ssl
import stat
import json
from pathlib import Path
import re
import socket
from threading import Lock, get_ident
from urllib.parse import urlsplit

from validation.capture_budget import BudgetError, digest

PURPOSE = 'approved_six_case_pilot'
MONITORING_PURPOSE = 'approved_source_monitoring_pilot'
FRESHNESS_PURPOSE = 'approved_monitoring_freshness_pilot'
HOSTS = {'api.openai.com', 'www.sec.gov', 'data.sec.gov'}
PROXY = 'http://proxy:8080'
PROXY_SELECTORS = ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')
CA_SELECTORS = ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE')


def validate_execution(config):
    keys = {'documentation_reference', 'verification_reference', 'substitution',
            'bearer_source', 'sec_contact_source', 'proxy', 'proxy_selectors',
            'ca_selectors', 'ca_identity', 'contains_no_credentials'}
    if (type(config) is not dict or set(config) != keys
            or config['substitution'] != 'explicit_environment_proxy'
            or config['proxy'] != PROXY or config['proxy_selectors'] != list(PROXY_SELECTORS)
            or config['ca_selectors'] != list(CA_SELECTORS)
            or config['bearer_source'] != 'OPENAI_API_KEY'
            or config['sec_contact_source'] != 'SEC_USER_AGENT'
            or config['contains_no_credentials'] is not True):
        raise BudgetError('reviewed explicit proxy configuration required')
    for key in ('documentation_reference', 'verification_reference'):
        value = config[key]
        if type(value) is not str or not value.strip() or len(value) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise BudgetError('invalid non-secret execution configuration')
    identity = config['ca_identity']
    if (type(identity) is not dict or set(identity) != {'path', 'sha256'}
            or type(identity['path']) is not str or not Path(identity['path']).is_absolute()
            or type(identity['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', identity['sha256'])):
        raise BudgetError('reviewed CA source identity required')


def runtime_values():
    # Called only after matching approval, never by preparation. These values
    # must not enter manifests, policies, hashes, diagnostics or result files.
    key, contact = os.environ.get('OPENAI_API_KEY'), os.environ.get('SEC_USER_AGENT')
    if any(type(v) is not str or not v or any(ord(c) < 32 or ord(c) > 126 for c in v)
           for v in (key, contact)) or not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', contact):
        raise BudgetError('runtime placeholder/contact unavailable')
    return {'bearer_placeholder': key, 'sec_contact': contact}


def verify_network_configuration(config, *, tls=False):
    validate_execution(config)
    try:
        for name in PROXY_SELECTORS:
            value = urlsplit(os.environ[name])
            if (value.scheme != 'http' or value.hostname != 'proxy' or value.port != 8080
                    or value.username is not None or value.password is not None
                    or value.query or value.fragment or value.path not in ('', '/')
                    or value.netloc != 'proxy:8080'):
                raise ValueError()
        path = Path(config['ca_identity']['path'])
        if path.resolve() != path or any(Path(os.environ[name]).resolve() != path for name in CA_SELECTORS):
            raise ValueError()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError()
            bundle = stream.read(2 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        if (len(bundle) > 2 * 1024 * 1024
                or any(getattr(before, name) != getattr(after, name) for name in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
                or hashlib.sha256(bundle).hexdigest() != config['ca_identity']['sha256']):
            raise ValueError()
        if tls:
            return ssl.create_default_context(cadata=bundle.decode('ascii'))
    except Exception:
        raise BudgetError('reviewed proxy or CA configuration changed') from None


def manifest_for(binding, execution, output_dir, *, monitoring=False, freshness=False):
    manifest = {'schema_version': 1, 'purpose': PURPOSE, 'code_binding': binding,
            'execution_configuration': execution, 'approval_status': 'pending',
            'output_dir': str(Path(output_dir).resolve()),
            'model_attempts': 24, 'sec_gets': 30, 'ledger_allowance_usd': '0.52',
            'illustrative_model_allocation_usd': '0.5105664',
            'invoice_ceiling_established': False}
    if monitoring:
        manifest.update(purpose=MONITORING_PURPOSE, model_attempts=0, sec_gets=33,
                        illustrative_model_allocation_usd='0', variant='source_monitoring')
    if freshness:
        if not monitoring:
            raise BudgetError('freshness requires source monitoring')
        from validation.pilot_freshness import stage_quotas
        from validation.pilot_preflight import preflight
        manifest.update(purpose=FRESHNESS_PURPOSE, sec_gets=39, variant='source_monitoring_freshness',
                        stage_quotas=stage_quotas([c['case_id'] for c in preflight()['cases']]),
                        filing_fallback_enabled=True)
    return manifest


def validate_approval(approval, binding, execution, *, monitoring=False, freshness=False):
    keys = {'reference', 'run_id', 'manifest_sha256', 'execution_allowed', 'spending_authorized', 'output_dir'}
    if (type(approval) is not dict or set(approval) != keys
            or approval['execution_allowed'] is not True or approval['spending_authorized'] is not True
            or type(approval['output_dir']) is not str
            or approval['output_dir'] != str(Path(approval['output_dir']).resolve())
            or approval['manifest_sha256'] != digest(manifest_for(binding, execution, approval['output_dir'], monitoring=monitoring, freshness=freshness))
            or not all(type(approval[k]) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', approval[k])
                       for k in ('reference', 'run_id'))
            or approval['reference'] in {'NO_SPENDING_AUTHORITY', 'pending'}):
        raise BudgetError('separate matching execution and spending approval required')


class ExchangeGate:
    """Thread-local grant for one immutable, durably claimed exchange."""
    def __init__(self, owner):
        if owner.ledger.policy.get('purpose') == 'approved_ordinary_twelve_case_pilot':
            from validation.ordinary_native_ledger import OrdinaryNativeGate
            if type(self) is not OrdinaryNativeGate:
                raise BudgetError('ordinary profile requires its wire-entry gate')
        self.owner = owner
        self.current = ContextVar('owned_claimed_network_exchange', default=None)
        self.closed = False
        self.lock = Lock()
        self.dispatched = 0
        self.grants = {}
        self.issued = set()
        self.resolve = socket.getaddrinfo

    def issue(self, attempt, fingerprint, route, case_run, stage):
        with self.lock:
            if self.closed or attempt in self.issued:
                raise BudgetError('grant already issued or gate sealed')
            grant = object()
            self.issued.add(attempt)
            self.grants[grant] = (attempt, fingerprint, route, case_run, stage)
            return grant

    @contextmanager
    def exchange(self, url, grant=None, fingerprint=None):
        host = urlsplit(url).hostname
        with self.lock:
            entry = self.grants.pop(grant, None)
            hosts = HOSTS - {'api.openai.com'} if self.owner.monitoring else HOSTS
            if (self.closed or host not in hosts or self.current.get() is not None
                    or entry is None or entry[1] != fingerprint):
                raise BudgetError('unclaimed, consumed or mismatched network grant')
            attempt, _, route, case_run, stage = entry
            self.owner.ledger.claim_native_dispatch(attempt, case_run=case_run, route=route,
                                                    request_sha256=fingerprint)
            self.owner.active()
            verify_network_configuration(self.owner.ledger.policy['execution_configuration'])
        state = {'url': url, 'host': host, 'addresses': set(), 'dispatched': False,
                 'attempt': attempt, 'case_run': case_run,
                 'validated': False, 'fingerprint': fingerprint, 'route': route,
                 'stage': stage, 'active': True, 'thread': get_ident()}
        token = self.current.set(state)
        try:
            yield
        finally:
            state['active'] = False
            self.current.reset(token)

    def require(self, url=None):
        state = self.current.get()
        if (self.closed or state is None or not state['active'] or state['thread'] != get_ident()
                or (url is not None and state['url'] != url)):
            raise BudgetError('network outside owned claimed exchange')
        self.owner.active()
        return state

    def validate_request(self, method, url, body):
        if type(method) is not str or type(url) is not str or type(body) is not bytes:
            raise BudgetError('immutable wire values required')
        state = self.require(url)
        if state['route'].startswith('model/'):
            fingerprint = digest({'method': method, 'url': url,
                                  'body_sha256': hashlib.sha256(body).hexdigest(), 'stage': state['stage']})
        else:
            if method != 'GET' or body != b'':
                raise BudgetError('unclaimed SEC payload')
            fingerprint = digest({'method': method, 'url': url, 'route': state['route'], 'stage': state['stage']})
        if fingerprint != state['fingerprint']:
            raise BudgetError('immutable claimed request changed')
        state['validated'] = True

    def dns(self, host, port, *args, **kwargs):
        state = self.require()
        if host != 'proxy' or port != 8080:
            raise BudgetError('DNS target is outside claimed exchange')
        answers = self.resolve(host, port, *args, **kwargs)
        if not answers or any(row[0] not in {socket.AF_INET, socket.AF_INET6} or row[4][1] != 8080 for row in answers):
            raise BudgetError('invalid configured proxy address')
        state['addresses'].update(row[4][0] for row in answers)
        return answers

    def audit(self, event, args):
        state = self.require()
        if not state['dispatched']:
            raise BudgetError('socket operation before native dispatch')
        if event == 'socket.getaddrinfo':
            if args[0] != 'proxy' or args[1] != 8080:
                raise BudgetError('unclaimed DNS')
        elif event == 'socket.__new__':
            if args[1] not in {socket.AF_INET, socket.AF_INET6} or args[2] != socket.SOCK_STREAM:
                raise BudgetError('unreviewed socket')
        elif event == 'socket.connect':
            if args[1][0] not in state['addresses'] or args[1][1] != 8080:
                raise BudgetError('unclaimed connection')
        else:
            raise BudgetError('unreviewed socket operation')

    def record_dispatch(self):
        state = self.require()
        with self.lock:
            if self.closed or state['dispatched'] or not state['validated']:
                raise BudgetError("dispatch is sealed or already consumed")
            state['dispatched'] = True
            self.dispatched += 1

    def seal(self):
        with self.lock:
            self.closed = True


class ScopedStream:
    def __init__(self, stream, gate, *, tunneled=False):
        self.stream, self.gate = stream, gate
        self.tunneled = tunneled
        self.connect_head = bytearray()
        self.connect_sent = False

    def read(self, max_bytes, timeout=None):
        self.gate.require()
        return self.stream.read(max_bytes, timeout)

    def write(self, buffer, timeout=None):
        state = self.gate.require()
        if not self.tunneled:
            if not buffer:
                return
            if self.connect_sent:
                raise BudgetError('cleartext data after CONNECT refused')
            self.connect_head.extend(buffer)
            if len(self.connect_head) > 8192:
                raise BudgetError('oversized CONNECT')
            if b'\r\n\r\n' not in self.connect_head:
                return
            target = (state['host'] + ':443').encode('ascii')
            expected = b'CONNECT ' + target + b' HTTP/1.1\r\nHost: ' + target + b'\r\nAccept: */*\r\n\r\n'
            if bytes(self.connect_head) != expected:
                raise BudgetError('unreviewed CONNECT target or headers')
            self.connect_sent = True
            return self.stream.write(bytes(self.connect_head), timeout)
        return self.stream.write(buffer, timeout)

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        state = self.gate.require()
        if (not self.connect_sent or self.tunneled or ssl_context is not self.gate.tls_context
                or server_hostname != state['host'] or not ssl_context.check_hostname
                or ssl_context.verify_mode != 2):
            raise BudgetError('TLS verification is required')
        return ScopedStream(self.stream.start_tls(ssl_context, server_hostname, timeout), self.gate, tunneled=True)

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)

    def close(self):
        self.stream.close()


class ScopedBackend:
    def __init__(self, backend, gate):
        self.backend, self.gate = backend, gate

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        state = self.gate.require()
        if host != 'proxy' or port != 8080 or local_address is not None:
            raise BudgetError('unclaimed native connection')
        return ScopedStream(self.backend.connect_tcp(host, port, timeout, local_address, socket_options), self.gate)

    def connect_unix_socket(self, *args, **kwargs):
        raise BudgetError('Unix transport is not approved')

    def sleep(self, seconds):
        raise BudgetError('transport retries are not approved')


from validation.pilot_boundary import PilotBoundary
from validation.pilot_live import LiveAdapterBoundary, OwnedHTTPTransport


class ApprovedBoundary(LiveAdapterBoundary):
    def __init__(self, ledger):
        if ledger.policy.get('purpose') not in {PURPOSE, MONITORING_PURPOSE, FRESHNESS_PURPOSE}:
            raise BudgetError('approved schema2 policy required')
        PilotBoundary.__init__(self, ledger, 'approved')
        execution = ledger.policy['execution_configuration']
        self.runtime = runtime_values()
        self.execution_hash = digest(execution)
        self.contact = self.runtime['sec_contact']
        self.gate = ExchangeGate(self)
        self.wire = OwnedHTTPTransport(gate=self.gate, execution=execution, runtime=self.runtime)
        self.wire._wire._pool._network_backend = ScopedBackend(self.wire._wire._pool._network_backend, self.gate)
        self.documents = {}
        self.document_filings = {}
        self.grants = ContextVar('claimed_dispatch_snapshot', default=None)

    def active(self):
        super().active()
        if (digest(self.ledger.policy['execution_configuration']) != self.execution_hash
                or runtime_values() != self.runtime):
            self.refuse('configuration_drift')

    def claim(self, route, fingerprint, inputs, outputs):
        attempt = super().claim(route, fingerprint, inputs, outputs)
        grant = self.gate.issue(attempt, fingerprint, route, self.case_run, self.stage.get())
        self.grants.set((grant, fingerprint))
        return attempt

    @contextmanager
    def dispatch(self, url, fingerprint):
        grant = self.grants.get()
        self.grants.set(None)  # No retry or transfer even if scope setup fails.
        if grant is None or grant[1] != fingerprint:
            self.refuse('invalid_request')
        with self.gate.exchange(url, grant[0], fingerprint):
            yield

    def validate_request_values(self, raw, payload):
        from validation.pilot_policy import reject_runtime_values
        reject_runtime_values(payload, tuple(self.runtime.values()), raw=raw)

    def model_exchange(self, snapshot, stage):
        import hashlib
        fingerprint = digest({'method': snapshot.method, 'url': snapshot.url,
                              'body_sha256': hashlib.sha256(snapshot.body).hexdigest(), 'stage': stage})
        with self.dispatch(snapshot.url, fingerprint):
            return super().model_exchange(snapshot, stage)

    def sec_content(self, route, url):
        fingerprint = digest({'method': 'GET', 'url': url, 'route': route, 'stage': self.stage.get()})
        with self.dispatch(url, fingerprint):
            return super().sec_content(route, url)

    def close(self):
        # Keep all bridges installed through process exit, including while
        # abandoned threads unwind. Never restore ordinary requests/urllib.
        self.gate.seal()
        self.drain()
        for pool in self.pools:
            pool.shutdown(wait=False)
        self.http.close()
        self.wire.close()


def main(argv=None, *, monitoring=False, freshness=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--execution-config', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        from validation.pilot_rehearsal import prepare_policy, run_rehearsal
        binding = prepare_policy()['code_binding']
        if args.prepare:
            if args.approval or args.output_dir is None:
                raise BudgetError('preparation cannot execute')
            execution = json.loads(args.execution_config.read_text()) if args.execution_config else None
            if execution is not None:
                validate_execution(execution)
            with args.manifest.open('x') as stream:
                json.dump(manifest_for(binding, execution, args.output_dir, monitoring=monitoring, freshness=freshness), stream, indent=2, sort_keys=True)
            return 0
        if args.approval is None or args.output_dir is None or args.execution_config is not None:
            raise BudgetError('manifest, separate approval and fresh output directory required')
        manifest = json.loads(args.manifest.read_text())
        approval = json.loads(args.approval.read_text())
        execution = manifest['execution_configuration']
        validate_execution(execution)
        if manifest != manifest_for(binding, execution, args.output_dir, monitoring=monitoring, freshness=freshness):
            raise BudgetError('manifest or source binding changed')
        validate_approval(approval, binding, execution, monitoring=monitoring, freshness=freshness)
        if approval['output_dir'] != manifest['output_dir']:
            raise BudgetError('approval output directory mismatch')
        result = run_rehearsal(args.output_dir, scenario='approved', mode='approved_freshness' if freshness else 'approved_source_monitoring' if monitoring else 'approved',
                               approval=approval, execution=execution)
    except Exception:
        parser.exit(2, 'Approved pilot refused; matching approval and verified configuration required.\n')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
