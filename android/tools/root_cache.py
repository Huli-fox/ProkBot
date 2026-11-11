#!/usr/bin/env python3
"""Experimental root + adb installer for the pinned official Grok Bot Android app.

Run --help. LSPosed must be disabled for Grok Bot. No APK replacement, global
network changes, real account credential reads, or automatic reboot.
"""
import argparse
import base64
import getpass
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import sqlite3
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

import expo_cache
import hermes

PACKAGE = 'ai.x.grok.bot'
APP = '/data/user/0/' + PACKAGE
DATABASE = APP + '/databases/updates.db'
DIRECTORY = APP + '/no_backup/prokbot-root-cache'
BACKUP = DIRECTORY + '/original.db'
MARKER = DIRECTORY + '/install.json'
BUNDLE = APP + '/files/.expo-internal/' + expo_cache.FILENAME
PROBE_TOKEN = 'PROKBOT_ASSESSMENT_ONLY_NOT_A_REAL_TOKEN_0000'


class Device:
    def __init__(self, executable, serial=None):
        self.prefix = [executable] + (['-s', serial] if serial else [])

    def adb(self, *args, data=None, timeout=90):
        result = subprocess.run([*self.prefix, *args], input=data, capture_output=True, timeout=timeout)
        if result.returncode:
            # Never echo shell input, downloaded responses, or credentials in exceptions.
            raise RuntimeError('adb operation failed; check device authorization/root and retry')
        return result.stdout

    def root(self, command, data=None):
        return self.adb('shell', '-T', 'su -c ' + shlex.quote(command), data=data)

    def exists(self, path):
        return self.root('if [ -f ' + shlex.quote(path) + ' ]; then echo yes; fi').strip() == b'yes'

    def read(self, path):
        # su/PTY on this device changes binary newlines. Transfer base64 to preserve every byte.
        encoded = self.root('base64 ' + shlex.quote(path))
        return base64.b64decode(re.sub(rb'\s+', b'', encoded), validate=True)

    def write(self, path, data, uid):
        """The payload travels over stdin, not a command line or public /data/local/tmp file."""
        path_q = shlex.quote(path)
        self.root(f'umask 077; base64 -d > {path_q}', data=base64.b64encode(data) + b'\n')
        self.root(f'chown {uid}:{uid} {path_q} && chmod 600 {path_q} && restorecon {path_q}')
        actual = self.root('sha256sum ' + path_q).split()[0].decode()
        if actual != hashlib.sha256(data).hexdigest():
            raise RuntimeError('Device file checksum mismatch')

    def stop(self):
        self.adb('shell', 'am', 'force-stop', PACKAGE)
        if self.pid():
            raise RuntimeError('Application did not stop')

    def pid(self):
        value = self.root('pidof ' + PACKAGE + ' || true').strip().decode()
        return value if value.isdigit() else None

    def launch(self):
        self.adb('shell', 'am', 'start', '-n', PACKAGE + '/.MainActivity')

    def package_info(self):
        """Read installation details even after an unsupported APK update."""
        if self.root('id -u').strip() != b'0':
            raise RuntimeError('Root authorization is required')
        info = self.adb('shell', 'dumpsys', 'package', PACKAGE).decode(errors='replace')
        version = re.search(r'versionName=([^\r\n]+)', info)
        code = re.search(r'versionCode=(\d+)\s', info)
        paths = self.adb('shell', 'pm', 'path', PACKAGE).decode().splitlines()
        apk = next((line.removeprefix('package:').strip() for line in paths if line.strip().endswith('/base.apk')), None)
        if not apk or not apk.startswith('/data/app/'):
            raise ValueError('Unexpected installed APK path')
        digest = self.root('sha256sum ' + shlex.quote(apk)).split()[0].decode()
        uid = self.root('stat -c %u ' + APP).strip().decode()
        if not uid.isdigit() or int(uid) < 10000:
            raise ValueError('Unexpected application owner')
        return {'versionName': version.group(1).strip() if version else None,
                'versionCode': int(code.group(1)) if code else None,
                'baseSha256': digest, 'apk': apk, 'uid': uid}

    def inspect(self, *, read_apk=False):
        info = self.package_info()
        if info['versionName'] != '1.19.1' or info['versionCode'] != 3050:
            raise ValueError('Only Grok Bot 1.19.1 (3050) is supported; run diagnose before recovery')
        if info['baseSha256'] != hermes.BASE_SHA256:
            raise ValueError('Installed base APK does not match the pinned recipe; run diagnose before recovery')
        pid = self.pid()
        if pid:
            maps = self.root('cat /proc/' + pid + '/maps').lower()
            if b'lspd' in maps or b'lsposed' in maps or b'frida' in maps:
                raise ValueError('Disable LSPosed/Frida for Grok Bot, then stop and reopen the app first')
        data = None
        if read_apk:
            with zipfile.ZipFile(io.BytesIO(self.read(info['apk']))) as archive:
                data = archive.read('assets/index.android.bundle')
            hermes.validate(data)
        return info['uid'], data


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def pair(address, key, name, *, ca_cert=None):
    address = hermes.origin(address)
    key = re.sub(r'[\s-]', '', key).upper()
    if not re.fullmatch('[A-Z2-9]{6}', key):
        raise ValueError('Pairing code must contain six characters')
    if not 1 <= len(name.strip()) <= 80:
        raise ValueError('Device name must contain 1-80 characters')
    body = json.dumps(dict(pairingKey=key, deviceName=name.strip(), platform='android')).encode()
    request = urllib.request.Request(address + '/connect/pair', body, {'Content-Type': 'application/json'}, method='POST')
    # A private CA applies to this connection only; hostname and certificate checks remain mandatory.
    context = ssl.create_default_context(cafile=ca_cert)
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=context))
    try:
        # Redirects cannot forward a one-time code.
        with opener.open(request, timeout=15) as response:
            if response.status != 201:
                raise ValueError('Unexpected pairing response')
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('Pairing response too large')
            result = json.loads(raw)
    except urllib.error.HTTPError as error:
        raise ValueError(f'Host pairing failed with HTTP {error.code}; confirm Android support and a fresh pairing code') from None
    if hermes.origin(result['gatewayUrl']) != address:
        raise ValueError('Host returned a different origin; check GROKBOT_PUBLIC_URL before pairing')
    if not re.fullmatch('[A-Za-z0-9_-]{32,256}', result.get('token', '')):
        raise ValueError('Host returned an invalid device token')
    return {'origin': address, 'token': result['token'], 'deviceId': result['deviceId']}


def snapshot(device, directory, *, installed=False):
    path = directory / 'source.db'
    path.write_bytes(device.read(DATABASE))
    for suffix in ('-wal', '-shm'):
        if device.exists(DATABASE + suffix):
            path.with_name(path.name + suffix).write_bytes(device.read(DATABASE + suffix))
    connection = sqlite3.connect(path)
    try:
        expo_cache.validate(connection, installed=installed)
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        connection.execute('PRAGMA journal_mode=DELETE')
    finally:
        connection.close()
    return path


def launch_patched(device):
    # Expo occasionally selects the embedded bundle on the first launch. A single
    # normal cold restart is enough to retry selection without clearing app data.
    for _ in range(2):
        device.launch()
        for _ in range(10):
            time.sleep(1)
            pid = device.pid()
            if pid and expo_cache.FILENAME.encode() in device.root('cat /proc/' + pid + '/maps'):
                return pid
        device.stop()
    raise RuntimeError('The patched cache was not loaded; inspect the Expo catalogue and device logs')


def restore(device):
    uid, _ = device.inspect()
    if not device.exists(BACKUP) or not device.exists(MARKER):
        raise ValueError('No installer backup found; nothing was changed')
    marker = json.loads(device.read(MARKER))
    original = device.read(BACKUP)
    if hashlib.sha256(original).hexdigest() != marker['originalDatabaseSha256']:
        raise ValueError('Backup checksum mismatch; refusing to restore')
    device.stop()
    device.write(DATABASE + '.prokbot-restore', original, uid)
    device.root(f'rm -f {DATABASE}-wal {DATABASE}-shm && mv {DATABASE}.prokbot-restore {DATABASE}')
    device.root(f'rm -f {BUNDLE} {BUNDLE}.tmp {DIRECTORY}/connection.json {MARKER} {BACKUP}')
    device.launch()
    time.sleep(4)
    if not device.pid():
        raise RuntimeError('Database restored; app startup still needs inspection')
    print(json.dumps({'restored': True, 'pid': int(device.pid()), 'rebootRequired': False}))


def install(device, args):
    uid, original = device.inspect(read_apk=True)
    if device.exists(MARKER) or device.exists(BACKUP):
        raise ValueError('An installation/backup already exists; use restore before replacing it')
    device.stop()
    with tempfile.TemporaryDirectory(prefix='prokbot-expo-') as name:
        directory = Path(name)
        try:
            source = snapshot(device, directory)
            # Validate bytecode generation before consuming the pairing code.
            address = hermes.origin(args.host, probe=args.command == 'probe')
            hermes.patch(original, address, PROBE_TOKEN, probe=args.command == 'probe')
        except Exception:
            device.launch()
            raise
        original_db = source.read_bytes()
        marker = {'baseSha256': hermes.BASE_SHA256, 'originalDatabaseSha256': hashlib.sha256(original_db).hexdigest(),
                  'updateId': str(expo_cache.UPDATE_ID), 'experimental': True, 'realHostTested': False,
                  'recipe': hermes.RECIPE}
        device.root('mkdir -p ' + DIRECTORY + ' && chmod 700 ' + DIRECTORY)
        device.write(BACKUP, original_db, uid)
        device.write(MARKER, json.dumps(marker).encode(), uid)
        mutation_started = False
        try:
            credentials = ({'origin': address, 'token': PROBE_TOKEN, 'deviceId': 'local-probe'}
                if args.command == 'probe' else pair(address, getpass.getpass('Host six-character pairing code: '), args.name,
                                                    ca_cert=args.ca_cert))
            # Preserve an issued token on the device before any subsequent generation/write can fail.
            device.write(DIRECTORY + '/connection.json', json.dumps(credentials).encode(), uid)
            patched = hermes.patch(original, credentials['origin'], credentials['token'], probe=args.command == 'probe')
            destination = directory / 'patched.db'
            expo_cache.add_update(source, destination, patched)
            device.write(BUNDLE + '.tmp', patched, uid)
            device.write(DATABASE + '.prokbot-new', destination.read_bytes(), uid)
            mutation_started = True
            device.root(f'mv {BUNDLE}.tmp {BUNDLE} && rm -f {DATABASE}-wal {DATABASE}-shm && mv {DATABASE}.prokbot-new {DATABASE}')
            pid = launch_patched(device)
            print(json.dumps({'installed': True, 'pid': int(pid), 'patchedBundleMapped': True,
                              'origin': address, 'probeOnly': args.command == 'probe',
                              'warning': 'Official OTA can supersede this cache; this installer does not verify chat'}))
        except Exception:
            if not mutation_started:
                device.launch()
            # Keep the verified backup, marker, and any issued credential available for explicit restore.
            print('Installation incomplete. A verified backup is on the phone; run the restore command.')
            raise


def refresh(device):
    """Upgrade a known cache recipe using its existing private device credential."""
    uid, original = device.inspect(read_apk=True)
    if not all(device.exists(path) for path in (BACKUP, MARKER, BUNDLE, DIRECTORY + '/connection.json')):
        raise ValueError('No complete installation found; inspect the device before refreshing')
    old_marker = device.read(MARKER)
    marker = json.loads(old_marker)
    if (marker.get('baseSha256') != hermes.BASE_SHA256 or marker.get('updateId') != str(expo_cache.UPDATE_ID)
            or hashlib.sha256(device.read(BACKUP)).hexdigest() != marker.get('originalDatabaseSha256')):
        raise ValueError('Installation backup or marker mismatch; refusing to refresh')
    credentials = json.loads(device.read(DIRECTORY + '/connection.json'))
    probe = credentials['deviceId'] == 'local-probe'
    patched = hermes.patch(original, credentials['origin'], credentials['token'], probe=probe)
    previous = device.read(BUNDLE)
    if previous != patched and previous != hermes.patch(
            original, credentials['origin'], credentials['token'], probe=probe, gateway_send=False):
        raise ValueError('Installed bundle does not match a known recipe; refusing to overwrite it')
    device.stop()
    with tempfile.TemporaryDirectory(prefix='prokbot-expo-refresh-') as name:
        directory = Path(name)
        mutation_started = False
        try:
            source = snapshot(device, directory, installed=True)
            destination = directory / 'refreshed.db'
            expo_cache.refresh_update(source, destination, previous, patched)
            marker['recipe'] = hermes.RECIPE
            device.write(BUNDLE + '.tmp', patched, uid)
            device.write(DATABASE + '.prokbot-new', destination.read_bytes(), uid)
            mutation_started = True
            device.root(f'mv {BUNDLE}.tmp {BUNDLE} && rm -f {DATABASE}-wal {DATABASE}-shm && mv {DATABASE}.prokbot-new {DATABASE}')
            device.write(MARKER, json.dumps(marker).encode(), uid)
            pid = launch_patched(device)
        except Exception:
            if mutation_started:
                device.stop()
                device.write(BUNDLE + '.tmp', previous, uid)
                device.write(DATABASE + '.prokbot-new', source.read_bytes(), uid)
                device.root(f'mv {BUNDLE}.tmp {BUNDLE} && rm -f {DATABASE}-wal {DATABASE}-shm && mv {DATABASE}.prokbot-new {DATABASE}')
                device.write(MARKER, old_marker, uid)
            device.launch()
            raise
    print(json.dumps({'refreshed': True, 'recipe': hermes.RECIPE, 'pid': int(pid),
                      'patchedBundleMapped': True, 'existingPairingPreserved': True,
                      'originalBackupPreserved': True, 'rebootRequired': False}))


def status(device):
    device.inspect()
    pid = device.pid()
    mapped = bool(pid and expo_cache.FILENAME.encode() in device.root('cat /proc/' + pid + '/maps'))
    print(json.dumps({'running': bool(pid), 'patchedBundleMapped': mapped, 'backupAvailable': device.exists(BACKUP)}))


def diagnose(device):
    """Report compatibility and recovery evidence without reading the device token."""
    info = device.package_info()
    supported = (info['versionName'] == '1.19.1' and info['versionCode'] == 3050
                 and info['baseSha256'] == hermes.BASE_SHA256)
    marker_exists, backup_exists = device.exists(MARKER), device.exists(BACKUP)
    marker, backup_valid = {}, False
    if marker_exists and backup_exists:
        try:
            marker = json.loads(device.read(MARKER))
            backup_valid = (marker.get('baseSha256') == hermes.BASE_SHA256
                            and marker.get('updateId') == str(expo_cache.UPDATE_ID)
                            and hashlib.sha256(device.read(BACKUP)).hexdigest() == marker.get('originalDatabaseSha256'))
        except (ValueError, AttributeError):
            marker = {}
    pid = device.pid()
    report = {key: info[key] for key in ('versionName', 'versionCode', 'baseSha256')}
    recipe = marker.get('recipe')
    report.update(supported=supported, running=bool(pid),
                  patchedBundleMapped=bool(pid and expo_cache.FILENAME.encode() in device.root('cat /proc/' + pid + '/maps')),
                  markerAvailable=marker_exists, backupAvailable=backup_exists, backupValid=backup_valid,
                  credentialAvailable=device.exists(DIRECTORY + '/connection.json'),
                  recipe=recipe if recipe == hermes.RECIPE else 'legacy-or-unknown',
                  recovery='same-version-only' if supported else 'manual-review-required',
                  changed=False)
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial')
    commands = parser.add_subparsers(dest='command', required=True)
    connect = commands.add_parser('connect', help='Pair with HTTPS Host and install into the private Expo cache')
    connect.add_argument('--host', required=True)
    connect.add_argument('--name', default='Android phone')
    connect.add_argument('--ca-cert', help='PEM CA certificate for pairing only; does not change phone/system trust')
    probe = commands.add_parser('probe', help='Install a dummy-token bundle; HTTPS can test TLS without pairing')
    probe.add_argument('--host', default='http://127.0.0.1:18081',
                       help='HTTPS origin to test; the default loopback HTTP probe is denied by Android')
    commands.add_parser('status', help='Check whether the exact installed cache is mapped into the running app')
    commands.add_parser('diagnose', help='Read compatibility and backup status, including after an unsupported APK update')
    commands.add_parser('refresh', help='Update a known cache recipe while keeping the existing pairing and original backup')
    commands.add_parser('restore', help='Restore the saved Expo catalogue and remove this tool\'s local credential/bundle')
    args = parser.parse_args()
    device = Device(args.adb, args.serial)
    try:
        if args.command in ('connect', 'probe'):
            install(device, args)
        elif args.command == 'restore':
            restore(device)
        elif args.command == 'refresh':
            refresh(device)
        elif args.command == 'diagnose':
            diagnose(device)
        else:
            status(device)
    except (ValueError, RuntimeError, subprocess.SubprocessError, OSError, KeyError, sqlite3.Error) as error:
        # Exception text from a Host/transport may contain credentials; print only known validation messages.
        if isinstance(error, (ValueError, RuntimeError)):
            parser.exit(1, str(error) + '\n')
        parser.exit(1, type(error).__name__ + ': operation failed; no credential was printed\n')


if __name__ == '__main__':
    main()
