#!/usr/bin/env python3
"""Prepare a private localhost CA, server certificate and Android 11 Magisk module.

Does not deploy, install, change a trust store, or reboot. Keep the output directory
private: it contains the CA private key. Only the server key goes to the server.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

MODULE_ID = 'prokbot_ssh_ca'


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, check=True, timeout=45)
    return result.stdout.decode().strip()


def protect(directory, owner_sid=None):
    if os.name == 'nt':
        identity = run('whoami', '/user', '/fo', 'csv', '/nh')
        sid = re.search(r'S-1-5-\d+(?:-\d+)+', identity)
        if not sid:
            raise RuntimeError('Unable to determine Windows account SID')
        grants = ['*' + sid.group() + ':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F']
        if owner_sid:
            grants.append('*' + owner_sid + ':(OI)(CI)F')
        run('icacls', str(directory), '/inheritance:r', '/grant:r', *grants)
    else:
        directory.chmod(0o700)


def prepare(openssl, destination, owner_sid=None):
    destination = destination.resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    protect(destination, owner_sid)
    private = destination / 'private'
    private.mkdir(mode=0o700)
    request = destination / 'request.cnf'
    request.write_text('[req]\ndistinguished_name=dn\n[dn]\n', encoding='ascii')
    date = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')

    def command(*args):
        return run(openssl, *args, cwd=destination)

    command('req', '-new', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256',
            '-days', '3650', '-subj', '/CN=ProkBot SSH Root CA ' + date,
            '-config', 'request.cnf', '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
            '-addext', 'subjectKeyIdentifier=hash',
            '-keyout', 'private/ca-key.pem', '-out', 'ca.pem')
    command('req', '-new', '-newkey', 'rsa:3072', '-nodes', '-sha256',
            '-subj', '/CN=ProkBot SSH localhost', '-config', 'request.cnf',
            '-keyout', 'private/server-key.pem', '-out', 'server.csr')
    (destination / 'server.ext').write_text(
        'basicConstraints=critical,CA:FALSE\n'
        'keyUsage=critical,digitalSignature,keyEncipherment\n'
        'extendedKeyUsage=serverAuth\n'
        'subjectAltName=IP:127.0.0.1,DNS:localhost\n'
        'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n', encoding='ascii')
    command('x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem', '-CAkey', 'private/ca-key.pem',
            '-set_serial', '0x' + os.urandom(20).hex(), '-days', '365', '-sha256',
            '-extfile', 'server.ext', '-out', 'server-chain.pem')
    for name in ('ca-key.pem', 'server-key.pem'):
        (private / name).chmod(0o600)
    command('verify', '-CAfile', 'ca.pem', '-purpose', 'sslserver', '-verify_ip', '127.0.0.1', 'server-chain.pem')
    command('verify', '-CAfile', 'ca.pem', '-purpose', 'sslserver', '-verify_hostname', 'localhost', 'server-chain.pem')
    subject_hash = command('x509', '-in', 'ca.pem', '-subject_hash_old', '-noout')
    if not re.fullmatch('[0-9a-f]{8}', subject_hash):
        raise RuntimeError('Unexpected Android certificate hash')
    certificate_name = subject_hash + '.0'
    ca = (destination / 'ca.pem').read_bytes()
    certificate_digest = hashlib.sha256(ca).hexdigest()
    module = destination / (MODULE_ID + '.zip')
    prop = ('id=' + MODULE_ID + '\nname=ProkBot SSH CA\nversion=1.0\nversionCode=1\n'
            'author=ProkBot local deployment\n'
            'description=Trust the dedicated ProkBot SSH CA on Android 11. Certificate only; no app hooks.\n')
    customize = '''#!/system/bin/sh
[ "$API" = 30 ] || abort "This certificate module is validated only for Android 11 (API 30)."
[ -d /system/etc/security/cacerts ] || abort "Expected Android system CA directory is missing."
[ ! -e /system/etc/security/cacerts/CERT_NAME ] || abort "Certificate filename already exists; inspect it before installing."
actual=$(sha256sum "$MODPATH/system/etc/security/cacerts/CERT_NAME")
[ "${actual%% *}" = "CERT_SHA" ] || abort "Certificate checksum mismatch."
set_perm_recursive "$MODPATH/system" 0 0 0755 0644
ui_print "- Adds the dedicated ProkBot CA to the system trust store."
ui_print "- No runtime hooks, background scripts or private keys."
ui_print "- A manual reboot is required. This installer does not reboot."
'''.replace('CERT_NAME', certificate_name).replace('CERT_SHA', certificate_digest)
    with zipfile.ZipFile(module, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('module.prop', prop)
        archive.writestr('customize.sh', customize)
        archive.writestr('system/etc/security/cacerts/' + certificate_name, ca)
    with zipfile.ZipFile(module) as archive:
        assert len(archive.namelist()) == 3
        assert not any(b'PRIVATE KEY' in archive.read(name) for name in archive.namelist())
    report = {
        'preparedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'moduleId': MODULE_ID, 'certificateName': certificate_name,
        'caFingerprint': command('x509', '-in', 'ca.pem', '-noout', '-fingerprint', '-sha256').split('=', 1)[1],
        'caExpires': command('x509', '-in', 'ca.pem', '-noout', '-enddate').split('=', 1)[1],
        'serverFingerprint': command('x509', '-in', 'server-chain.pem', '-noout', '-fingerprint', '-sha256').split('=', 1)[1],
        'serverExpires': command('x509', '-in', 'server-chain.pem', '-noout', '-enddate').split('=', 1)[1],
        'serverNames': ['127.0.0.1', 'localhost'],
        'caPemSha256': certificate_digest,
        'moduleSha256': hashlib.sha256(module.read_bytes()).hexdigest(),
        'privateKeysIncludedInModule': False,
        'installed': False,
    }
    (destination / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openssl', default='openssl')
    parser.add_argument('--output', required=True, type=Path, help='New private output directory; must not already exist')
    parser.add_argument('--owner-sid', help='Windows operator SID to retain access when running under a separate sandbox account')
    args = parser.parse_args()
    if args.owner_sid and (os.name != 'nt' or not re.fullmatch(r'S-1-5-\d+(?:-\d+)+', args.owner_sid)):
        parser.error('--owner-sid requires Windows and a valid account SID')
    try:
        prepare(args.openssl, args.output, args.owner_sid)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, type(error).__name__ + ': preparation failed; output was not deployed or installed\n')


if __name__ == '__main__':
    main()
