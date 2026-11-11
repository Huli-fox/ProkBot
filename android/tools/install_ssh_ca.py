#!/usr/bin/env python3
"""Install the prepared, certificate-only Android 11 Magisk module; never reboot.

Requires the user's authorization to add system trust. No application data is
changed. The certificate becomes available after the user manually reboots.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import zipfile

from root_cache import Device

MODULE_ID = 'prokbot_ssh_ca'
STAGED = '/data/adb/modules_update/' + MODULE_ID
ACTIVE = '/data/adb/modules/' + MODULE_ID
UPLOAD = '/data/adb/prokbot-ssh-ca-install.zip'


def install(device, directory):
    directory = directory.resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['moduleId'] == MODULE_ID
    cert_name = manifest['certificateName']
    if not re.fullmatch('[0-9a-f]{8}\.0', cert_name):
        raise ValueError('Invalid Android CA filename')
    module = (directory / (MODULE_ID + '.zip')).read_bytes()
    if hashlib.sha256(module).hexdigest() != manifest['moduleSha256']:
        raise ValueError('Module checksum mismatch')
    with zipfile.ZipFile(directory / (MODULE_ID + '.zip')) as archive:
        certificate = 'system/etc/security/cacerts/' + cert_name
        if sorted(archive.namelist()) != sorted(['module.prop', 'customize.sh', certificate]):
            raise ValueError('Module contains unexpected files')
        if any(b'PRIVATE KEY' in archive.read(name) for name in archive.namelist()):
            raise ValueError('Private key must not be installed on the phone')
        if hashlib.sha256(archive.read(certificate)).hexdigest() != manifest['caPemSha256']:
            raise ValueError('Module CA checksum mismatch')
    if device.root('id -u').strip() != b'0':
        raise ValueError('Root authorization is required')
    if device.adb('shell', 'getprop', 'ro.build.version.sdk').strip() != b'30':
        raise ValueError('This installation supports Android 11 only')
    for path in (STAGED, ACTIVE, UPLOAD, '/system/etc/security/cacerts/' + cert_name):
        found = device.root('if [ -e ' + shlex.quote(path) + ' ]; then echo exists; fi').strip()
        if found:
            raise ValueError('An installation path already exists; inspect before replacing it')
    boot_id = device.root('cat /proc/sys/kernel/random/boot_id').strip().decode()
    device.write(UPLOAD, module, '0')
    # The native Magisk installer stages a module for the next boot. It does not reboot.
    log = device.root('magisk --install-module ' + shlex.quote(UPLOAD) + ' 2>&1').decode(errors='replace')
    (directory / 'phone-install.log').write_text(log, encoding='utf-8')
    staged_cert = STAGED + '/' + certificate
    if hashlib.sha256(device.read(staged_cert)).hexdigest() != manifest['caPemSha256']:
        raise RuntimeError('Staged CA verification failed; inspect Magisk before rebooting')
    staged_files = device.root('find ' + STAGED + ' -type f').decode().split()
    expected = {STAGED + '/module.prop', staged_cert}
    if set(staged_files) != expected:
        raise RuntimeError('Unexpected installed module files; inspect Magisk before rebooting')
    if not device.exists(ACTIVE + '/update'):
        raise RuntimeError('Magisk did not mark the module for the next boot')
    if device.exists('/system/etc/security/cacerts/' + cert_name):
        raise RuntimeError('CA unexpectedly already active; inspect the mount state')
    if device.root('cat /proc/sys/kernel/random/boot_id').strip().decode() != boot_id:
        raise RuntimeError('Phone rebooted during installation; inspect its current state')
    device.root('rm -f ' + shlex.quote(UPLOAD))
    report = {
        'installedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'moduleId': MODULE_ID, 'certificateName': cert_name,
        'caFingerprint': manifest['caFingerprint'],
        'moduleSha256': manifest['moduleSha256'],
        'stagedCaSha256': manifest['caPemSha256'],
        'stagedFiles': sorted(staged_files), 'privateKeysInstalled': False,
        'beforeBootId': boot_id, 'manualRebootRequired': True, 'rebootIssued': False,
        'systemCertificateActive': False, 'phoneTlsVerified': False, 'phoneLiveChatTested': False,
    }
    (directory / 'phone-install.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    print('STOP: certificate staged. Ask the user to reboot manually before continuing phone work.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial')
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    install(Device(args.adb, args.serial), args.directory)


if __name__ == '__main__':
    main()
