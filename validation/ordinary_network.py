"""Reviewed network configurations for the ordinary pilot, including direct TLS.

``direct_tls`` connects straight to the claimed SEC host on port 443, with no
application proxy: no proxy variable may be set (none is overwritten), and TLS
is verified against a CA bundle pinned by canonical path and SHA-256, with
hostname checking. It says nothing about intermediaries below the process,
such as a VPN; a TLS interceptor whose CA is not in the pinned bundle fails
verification. The historical explicit-proxy configuration is delegated
unchanged to validation.pilot_approved.
"""
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import socket
import ssl
import stat

from validation import pilot_approved
from validation.capture_budget import BudgetError

DIRECT = 'direct_tls'
SEC_PORT = 443
PROXY_ENVIRONMENT = ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy')
CA_SELECTORS = ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE')
_REFERENCE = re.compile(r'[ -~]{1,512}')


def is_direct(config):
    return type(config) is dict and config.get('substitution') == DIRECT


def validate_ordinary_execution(config):
    """Exactly one reviewed shape: the historical proxy, or direct TLS."""
    if not is_direct(config):
        pilot_approved.validate_execution(config)
        return
    keys = {'documentation_reference', 'verification_reference', 'substitution', 'proxy',
            'sec_contact_source', 'ca_selectors', 'ca_identity', 'contains_no_credentials'}
    identity = config.get('ca_identity')
    if (set(config) != keys or config['proxy'] is not None
            or config['sec_contact_source'] != 'SEC_USER_AGENT'
            or config['ca_selectors'] != list(CA_SELECTORS)
            or config['contains_no_credentials'] is not True
            or any(type(config[k]) is not str or not config[k].strip() or not _REFERENCE.fullmatch(config[k])
                   for k in ('documentation_reference', 'verification_reference'))
            or type(identity) is not dict or set(identity) != {'path', 'sha256'}
            or type(identity['path']) is not str or not Path(identity['path']).is_absolute()
            or type(identity['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', identity['sha256'])):
        raise BudgetError('reviewed direct TLS configuration required')


def verify_ordinary_network(config, *, tls=False):
    """The running process matches the reviewed configuration; optionally its context."""
    if not is_direct(config):
        # Looked up at call time, exactly as ExchangeGate.exchange does.
        return pilot_approved.verify_network_configuration(config, tls=tls)
    validate_ordinary_execution(config)
    try:
        if any(os.environ.get(name) for name in PROXY_ENVIRONMENT):
            raise ValueError()  # direct mode never overrides an inherited proxy
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
            context = ssl.create_default_context(cadata=bundle.decode('ascii'))
            if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
                raise ValueError()
            return context
    except Exception:
        raise BudgetError('reviewed direct network or CA configuration changed') from None


def public_address(address):
    """The approved rule: only globally routable resolver answers."""
    return ipaddress.ip_address(address).is_global


def admit_resolution(claimed_host, host, port, answers, allow_address):
    """Resolver answers for the claimed SEC host only, as (address, port) endpoints."""
    if host != claimed_host or port != SEC_PORT or not answers:
        raise BudgetError('DNS target is outside the claimed exchange')
    endpoints = set()
    for row in answers:
        if (row[0] not in {socket.AF_INET, socket.AF_INET6} or row[1] not in {0, socket.SOCK_STREAM}
                or not allow_address(row[4][0])):
            raise BudgetError('resolver answer refused')
        endpoints.add((row[4][0], row[4][1]))
    return endpoints


class DirectScopedStream:
    """No byte before TLS; TLS only to the claimed host with the pinned context."""
    def __init__(self, stream, gate, host, *, tls=False):
        self.stream, self.gate, self.host, self.tls = stream, gate, host, tls

    def _require(self):
        state = self.gate.require()
        if state['host'] != self.host:
            raise BudgetError('connection reused for another host')
        return state

    def read(self, max_bytes, timeout=None):
        self._require()
        if not self.tls:
            raise BudgetError('read before TLS')
        return self.stream.read(max_bytes, timeout)

    def write(self, buffer, timeout=None):
        self._require()
        if not self.tls:
            raise BudgetError('cleartext write refused')
        return self.stream.write(buffer, timeout)

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self._require()
        if (self.tls or ssl_context is not self.gate.tls_context or server_hostname != self.host
                or not ssl_context.check_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED):
            raise BudgetError('TLS verification is required')
        return DirectScopedStream(self.stream.start_tls(ssl_context, server_hostname, timeout),
                                  self.gate, self.host, tls=True)

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)

    def close(self):
        self.stream.close()


class DirectScopedBackend:
    def __init__(self, backend, gate):
        self.backend, self.gate = backend, gate

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        state = self.gate.require()
        if host != state['host'] or port != SEC_PORT or local_address is not None:
            raise BudgetError('unclaimed direct connection')
        return DirectScopedStream(self.backend.connect_tcp(host, port, timeout, local_address, socket_options),
                                  self.gate, host)

    def connect_unix_socket(self, *args, **kwargs):
        raise BudgetError('Unix transport is not approved')

    def sleep(self, seconds):
        raise BudgetError('transport retries are not approved')
