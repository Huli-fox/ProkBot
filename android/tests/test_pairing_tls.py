"""Real local TLS handshakes; set PROKBOT_TEST_OPENSSL if OpenSSL is not on PATH."""
import http.server
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_cache

OPENSSL = os.environ.get('PROKBOT_TEST_OPENSSL') or shutil.which('openssl')
TOKEN = 'test_device_token_' + 'x' * 32


class PairingHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.received.append((self.path, body))
        if self.server.redirect:
            self.send_response(302)
            self.send_header('Location', '/unexpected')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        raw = json.dumps({'gatewayUrl': self.server.origin, 'token': TOKEN,
                          'deviceId': 'test-device'}).encode()
        self.send_response(201)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.server.received.append((self.path, None))
        self.send_error(500)


@unittest.skipUnless(OPENSSL, 'Set PROKBOT_TEST_OPENSSL or install OpenSSL for TLS handshake tests')
class PairingTlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='prokbot-tls-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.ca = str(cls.directory / 'ca.pem')
        (cls.directory / 'request.cnf').write_text('[req]\ndistinguished_name=dn\n[dn]\n')

        def openssl(*args):
            subprocess.run([OPENSSL, *args], cwd=cls.directory, capture_output=True,
                           check=True, timeout=30)

        openssl('req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256',
                '-days', '1', '-subj', '/CN=ProkBot ephemeral test CA',
                '-config', 'request.cnf', '-addext', 'basicConstraints=critical,CA:TRUE',
                '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
                '-keyout', 'ca-key.pem', '-out', 'ca.pem')
        cls.servers = {}
        for number, (label, san) in enumerate((('valid', 'IP:127.0.0.1'),
                                              ('wrong-address', 'DNS:localhost')), 1):
            openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-sha256',
                    '-subj', '/CN=ProkBot ephemeral test server', '-config', 'request.cnf',
                    '-keyout', label + '-key.pem', '-out', label + '.csr')
            extensions = cls.directory / (label + '.ext')
            extensions.write_text('basicConstraints=critical,CA:FALSE\n'
                                  'keyUsage=critical,digitalSignature,keyEncipherment\n'
                                  'extendedKeyUsage=serverAuth\nsubjectAltName=' + san + '\n')
            openssl('x509', '-req', '-in', label + '.csr', '-CA', 'ca.pem',
                    '-CAkey', 'ca-key.pem', '-set_serial', str(number), '-days', '1',
                    '-sha256', '-extfile', extensions.name, '-out', label + '.pem')
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), PairingHandler)
            cls.addClassCleanup(server.server_close)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cls.directory / (label + '.pem'),
                                    cls.directory / (label + '-key.pem'))
            server.socket = context.wrap_socket(server.socket, server_side=True)
            server.origin = 'https://127.0.0.1:' + str(server.server_port)
            server.redirect = False
            server.received = []
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            cls.addClassCleanup(worker.join, 5)
            cls.addClassCleanup(server.shutdown)
            cls.servers[label] = server

    def setUp(self):
        for server in self.servers.values():
            server.received.clear()
            server.redirect = False

    def test_custom_ca_pairs_over_real_https(self):
        server = self.servers['valid']
        result = root_cache.pair(server.origin, 'ABCD23', 'Android test', ca_cert=self.ca)
        self.assertEqual(result, {'origin': server.origin, 'token': TOKEN, 'deviceId': 'test-device'})
        self.assertEqual(server.received, [('/connect/pair', {
            'pairingKey': 'ABCD23', 'deviceName': 'Android test', 'platform': 'android'})])

    def test_ca_is_required_and_does_not_change_default_trust(self):
        server = self.servers['valid']
        root_cache.pair(server.origin, 'ABCD23', 'Android test', ca_cert=self.ca)
        server.received.clear()
        with self.assertRaises(urllib.error.URLError) as caught:
            root_cache.pair(server.origin, 'ABCD23', 'Android test')
        self.assertIsInstance(caught.exception.reason, ssl.SSLCertVerificationError)
        self.assertEqual(server.received, [])

    def test_custom_ca_does_not_disable_address_validation(self):
        server = self.servers['wrong-address']
        with self.assertRaises(urllib.error.URLError) as caught:
            root_cache.pair(server.origin, 'ABCD23', 'Android test', ca_cert=self.ca)
        self.assertIsInstance(caught.exception.reason, ssl.SSLCertVerificationError)
        self.assertEqual(server.received, [])

    def test_custom_ca_does_not_allow_redirects(self):
        server = self.servers['valid']
        server.redirect = True
        with self.assertRaisesRegex(ValueError, 'HTTP 302'):
            root_cache.pair(server.origin, 'ABCD23', 'Android test', ca_cert=self.ca)
        self.assertEqual([entry[0] for entry in server.received], ['/connect/pair'])


if __name__ == '__main__':
    unittest.main()
