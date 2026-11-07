"""Loopback CONNECT proxy, or direct TLS 'SEC', for the ordinary live code path.

Proxy mode listens on 127.0.0.1:8080, answers CONNECT for www.sec.gov and
data.sec.gov, then terminates TLS itself. Direct mode listens on
127.0.0.1:8443 and speaks TLS from the first byte, recording the SNI host.
Either way the leaf certificate is issued by a per-run test CA and the
invented responses of validation._ordinary_synthetic_sec are served. It never
opens an outbound connection. Test infrastructure only.
"""
import datetime
import json
import re
import socketserver
import ssl
import threading
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from validation._ordinary_synthetic_sec import respond

SEC_HOSTS = ('www.sec.gov', 'data.sec.gov')
OVERSIZE_TOTAL = 64 * 1024 * 1024
PARTIAL_MARKER = b'<p>INVENTED-PARTIAL-OVERSIZED-FILING-TEXT</p>'
OVERSIZE_FRAMING = {'oversize_declared': b'Content-Length: %d\r\n' % OVERSIZE_TOTAL,
                    'oversize_chunked': b'Transfer-Encoding: chunked\r\n',
                    'oversize_close': b'Connection: close\r\n'}


def inline_quarterly_filing(cik):
    """An invented quarterly filing whose inline facts compare two periods."""
    def context(key, year):
        return (f'<xbrli:context id="{key}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{cik:010d}'
                f'</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{year}-04-01</xbrli:startDate>'
                f'<xbrli:endDate>{year}-06-30</xbrli:endDate></xbrli:period></xbrli:context>')

    def fact(concept, key, value):
        return (f'<ix:nonFraction id="{concept}-{key}" name="us-gaap:{concept}" contextRef="{key}" unitRef="usd" '
                f'decimals="-3" format="ixt:num-dot-decimal" scale="3">{value}</ix:nonFraction>')
    facts = ''.join(fact(concept, 'current', current) + fact(concept, 'prior', prior)
                    for concept, current, prior in (('Revenues', '1,100', '1,000'), ('OperatingIncomeLoss', '210', '190'),
                                                    ('NetIncomeLoss', '160', '150')))
    return (f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:xbrli="http://www.xbrl.org/2003/instance" '
            'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:us-gaap="http://fasb.org/us-gaap/2026" '
            'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
            'xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12">'
            f'<head/><body><ix:header><ix:resources>{context("current", 2026)}{context("prior", 2025)}'
            '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:resources></ix:header>'
            f'<p>Invented rehearsal quarterly report.</p>{facts}</body></html>').encode()


def _authority(name):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(hours=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    return key, cert


def _leaf(ca_key, ca_cert):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, SEC_HOSTS[0])]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(hours=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in SEC_HOSTS]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


class LoopbackSEC:
    """Context manager; ``ca_path`` is the CA the worker must pin.

    With ``untrusted=True`` the served leaf is issued by a different CA than
    the one written to ``ca_path``, so certificate verification must fail.
    """
    def __init__(self, directory, *, untrusted=False, direct=False, fault=None, ifrs_only_cik=None, inline_filing=True):
        # ifrs_only_cik: that issuer's company facts are valid but hold no us-gaap, so they
        # support no comparison, and its latest filing carries the only comparable facts.
        # That filing is then the difference between an answer and none.
        self.ifrs_only_cik, self.inline_filing = ifrs_only_cik, inline_filing
        # (kind, path regex, nth match): 'late' completes after 13 s with bytes arriving
        # inside the read timeout, 'silent' sends nothing for 13 s, 'crawl' sends one byte
        # a second, 'close' hangs up without answering.
        self.fault, self.fault_matches = fault, 0
        ca_key, ca_cert = _authority('Ordinary loopback test CA')
        issuer = _authority('Unpinned loopback CA') if untrusted else (ca_key, ca_cert)
        leaf_key, leaf_cert = _leaf(*issuer)
        self.ca_path = (directory / 'loopback-ca.pem').resolve()
        self.ca_path.write_bytes(_pem(ca_cert))
        chain = directory / 'loopback-leaf.pem'
        chain.write_bytes(_pem(leaf_cert) + leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(chain)
        self.direct = direct
        # Per-connection SNI: the name the client asked TLS to verify.
        self.context.sni_callback = lambda sock, name, context: setattr(sock, 'sni_name', name)
        self.connects, self.requests, self.handshake_failures = [], [], 0
        self.oversize = []  # what each oversized response managed to send before the client hung up
        self.lock = threading.Lock()

    def __enter__(self):
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                owner._handle(self.request)

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 8443 if self.direct else 8080), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @staticmethod
    def _head(stream):
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = stream.recv(4096)
            if not chunk:
                return None
            data += chunk
            if len(data) > 16384:
                return None
        return data.split(b'\r\n\r\n', 1)[0].decode('latin-1')

    def _handle(self, connection):
        if self.direct:
            return self._serve(connection, None)
        head = self._head(connection)
        match = re.fullmatch(r'CONNECT ((?:www|data)\.sec\.gov):443 HTTP/1\.1\r\n(.*)', head or '', re.S)
        with self.lock:
            self.connects.append(head)
        if not match:
            connection.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
            return
        connection.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
        self._serve(connection, match[1])

    def _take_fault(self, path):
        if self.fault is None or not re.search(self.fault[1], path):
            return None
        with self.lock:
            self.fault_matches += 1
            return self.fault[0] if self.fault_matches == self.fault[2] else None

    def _send_oversize(self, tls, kind, media):
        """Far more than the limit, for as long as the client keeps the connection.

        Only 'oversize_close' asks for the connection to close afterwards, so ending
        the other two early is the client's own doing.
        """
        framing = OVERSIZE_FRAMING[kind]
        head = b'HTTP/1.1 200 OK\r\nContent-Type: %s\r\n%s\r\n' % (media.encode(), framing)
        block = (PARTIAL_MARKER * (64 * 1024 // len(PARTIAL_MARKER) + 1))[:64 * 1024]
        if kind == 'oversize_chunked':
            block = b'%x\r\n%s\r\n' % (len(block), block)
        sent, hung_up = 0, False
        try:
            tls.sendall(head)
            while sent < OVERSIZE_TOTAL:
                tls.sendall(block)
                sent += len(block)
        except OSError:
            hung_up = True
        with self.lock:
            self.oversize.append({'kind': kind, 'sent': sent, 'client_hung_up': hung_up})

    def _serve(self, connection, tunnel):
        try:
            tls = self.context.wrap_socket(connection, server_side=True)
        except (ssl.SSLError, OSError):
            with self.lock:
                self.handshake_failures += 1
            return
        with tls:
            request = self._head(tls)
            if request is None:
                return
            line, *fields = request.split('\r\n')
            method, path, _ = line.split(' ')
            headers = {k.lower(): v.strip() for k, v in (f.split(':', 1) for f in fields)}
            with self.lock:
                self.requests.append({'tunnel': tunnel or getattr(tls, 'sni_name', None),
                                      'host': headers.get('host'), 'method': method,
                                      'path': path, 'user_agent': headers.get('user-agent')})
            status, media, body = respond(path) if method == 'GET' else (405, 'text/plain', b'')
            if self.ifrs_only_cik is not None and path == f'/api/xbrl/companyfacts/CIK{self.ifrs_only_cik:010d}.json':
                facts = json.loads(body)
                facts['facts'] = {'ifrs-full': {'Revenue': {'label': 'Invented rehearsal value', 'units': {}}}}
                body = json.dumps(facts).encode()
            if (self.ifrs_only_cik is not None and self.inline_filing and media == 'text/html'
                    and re.search(rf'/edgar/data/{self.ifrs_only_cik}/[0-9]+/[a-z]+-20260630\.htm$', path)):
                body = inline_quarterly_filing(self.ifrs_only_cik)
            reason = {200: b'OK', 404: b'Not Found', 405: b'Method Not Allowed'}[status]
            kind = self._take_fault(path)
            if kind == 'close':
                return
            if kind == 'silent':
                time.sleep(13.0)
            if kind in OVERSIZE_FRAMING:
                self._send_oversize(tls, kind, media)
                return
            payload = (b'HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                       b'Connection: close\r\n\r\n' % (status, reason, media.encode(), len(body)) + body)
            if kind == 'late':
                try:
                    head, tail = payload[:-1], payload[-1:]
                    tls.sendall(head[:1])
                    time.sleep(6.5)
                    tls.sendall(head[1:])
                    time.sleep(6.5)
                    tls.sendall(tail)
                except OSError:
                    pass
                return
            if kind == 'crawl':
                try:
                    for index in range(len(payload)):
                        tls.sendall(payload[index:index + 1])
                        time.sleep(1.0)
                except OSError:
                    pass  # The client closed its abandoned exchange.
                return
            tls.sendall(payload)
