"""Loopback CONNECT proxy, or direct TLS 'SEC', for the ordinary live code path.

Proxy mode listens on 127.0.0.1:8080, answers CONNECT for www.sec.gov and
data.sec.gov, then terminates TLS itself. Direct mode listens on
127.0.0.1:8443 and speaks TLS from the first byte, recording the SNI host.
Either way the leaf certificate is issued by a per-run test CA and the
invented responses of validation._ordinary_synthetic_sec are served. It never
opens an outbound connection. Test infrastructure only.
"""
import datetime
import re
import socketserver
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from validation._ordinary_synthetic_sec import respond

SEC_HOSTS = ('www.sec.gov', 'data.sec.gov')


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
    def __init__(self, directory, *, untrusted=False, direct=False):
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
            reason = {200: b'OK', 404: b'Not Found', 405: b'Method Not Allowed'}[status]
            tls.sendall(b'HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                        b'Connection: close\r\n\r\n' % (status, reason, media.encode(), len(body)) + body)
