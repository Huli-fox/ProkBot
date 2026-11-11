import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_cache as cache


class ReadOnlyDevice:
    def __init__(self, *, supported=True, corrupt_backup=False):
        self.supported = supported
        self.files = {
            cache.BACKUP: b'original-catalogue',
            cache.DIRECTORY + '/connection.json': b'must-not-read-this-token',
            cache.MARKER: json.dumps({
                'baseSha256': cache.hermes.BASE_SHA256,
                'originalDatabaseSha256': hashlib.sha256(b'original-catalogue').hexdigest(),
                'updateId': str(cache.expo_cache.UPDATE_ID), 'recipe': cache.hermes.RECIPE,
            }).encode(),
        }
        if corrupt_backup:
            self.files[cache.BACKUP] = b'corrupt'

    def package_info(self):
        return {'versionName': '1.19.1' if self.supported else '2.0.0',
                'versionCode': 3050 if self.supported else 9999,
                'baseSha256': cache.hermes.BASE_SHA256 if self.supported else '0' * 64,
                'uid': '10430', 'apk': '/data/app/test/base.apk'}

    def exists(self, path):
        return path in self.files

    def read(self, path):
        if path.endswith('connection.json'):
            raise AssertionError('Diagnostics must not read the credential')
        return self.files[path]

    def pid(self):
        return None


class DiagnoseTests(unittest.TestCase):
    def test_unknown_version_can_be_diagnosed_without_mutation_or_token_reads(self):
        device = ReadOnlyDevice(supported=False)
        before = device.files.copy()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cache.diagnose(device)
        report = json.loads(output.getvalue())
        self.assertFalse(report['supported'])
        self.assertTrue(report['backupValid'])
        self.assertTrue(report['credentialAvailable'])
        self.assertEqual(report['recovery'], 'manual-review-required')
        self.assertFalse(report['changed'])
        self.assertEqual(device.files, before)
        self.assertNotIn('must-not-read-this-token', output.getvalue())

    def test_corrupt_backup_is_reported(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cache.diagnose(ReadOnlyDevice(corrupt_backup=True))
        self.assertFalse(json.loads(output.getvalue())['backupValid'])

    def test_restore_refuses_changed_version_before_any_write(self):
        device = cache.Device('unused-in-test')
        with patch.object(device, 'package_info', return_value=ReadOnlyDevice(supported=False).package_info()), \
                patch.object(device, 'stop', side_effect=AssertionError('Must not stop an unknown app')), \
                patch.object(device, 'write', side_effect=AssertionError('Must not change unknown data')):
            with self.assertRaisesRegex(ValueError, 'run diagnose'):
                cache.restore(device)


if __name__ == '__main__':
    unittest.main()
