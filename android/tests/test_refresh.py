"""Failure recovery tests: never consume pairing again or replace the original backup."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_cache as cache


class MemoryDevice:
    def __init__(self):
        self.files = {
            cache.BACKUP: b'original-backup',
            cache.DATABASE: b'current-catalogue',
            cache.BUNDLE: b'old-bundle',
            cache.DIRECTORY + '/connection.json': json.dumps({
                'origin': 'https://example.test', 'token': 'test-token', 'deviceId': 'test-device',
            }).encode(),
        }
        self.files[cache.MARKER] = json.dumps({
            'baseSha256': cache.hermes.BASE_SHA256,
            'originalDatabaseSha256': hashlib.sha256(self.files[cache.BACKUP]).hexdigest(),
            'updateId': str(cache.expo_cache.UPDATE_ID),
        }).encode()
        self.running = True
        self.fail_next_database_move = False

    def inspect(self, **kwargs):
        return '10430', b'original-bytecode'

    def exists(self, path):
        return path in self.files

    def read(self, path):
        return self.files[path]

    def write(self, path, data, uid):
        self.files[path] = data

    def stop(self):
        self.running = False

    def launch(self):
        self.running = True

    def root(self, command):
        for part in command.split(' && '):
            args = shlex.split(part)
            if args[0] == 'mv':
                if args[2] == cache.DATABASE and self.fail_next_database_move:
                    self.fail_next_database_move = False
                    raise RuntimeError('Simulated interruption after bundle replacement')
                self.files[args[2]] = self.files.pop(args[1])
            elif args[:2] == ['rm', '-f']:
                for path in args[2:]:
                    self.files.pop(path, None)
            else:
                raise AssertionError('Unexpected command')


def snapshot(device, directory, **kwargs):
    source = directory / 'source.db'
    source.write_bytes(device.read(cache.DATABASE))
    return source


class RefreshTests(unittest.TestCase):
    def run_refresh(self, device, *, startup_failure=False):
        def generate(*args, gateway_send=True, **kwargs):
            return b'new-bundle' if gateway_send else b'old-bundle'

        def update(source, destination, *args):
            destination.write_bytes(b'new-catalogue')

        def launch(device):
            if startup_failure:
                raise RuntimeError('Simulated cache selection failure')
            device.launch()
            return '12345'

        with patch.object(cache.hermes, 'patch', side_effect=generate), \
                patch.object(cache, 'snapshot', side_effect=snapshot), \
                patch.object(cache.expo_cache, 'refresh_update', side_effect=update), \
                patch.object(cache, 'launch_patched', side_effect=launch), \
                patch.object(cache, 'pair', side_effect=AssertionError('Refresh must not pair again')), \
                contextlib.redirect_stdout(io.StringIO()):
            cache.refresh(device)

    def test_existing_pairing_and_original_backup_survive_upgrade(self):
        device = MemoryDevice()
        before = device.files.copy()
        self.run_refresh(device)
        for path in (cache.BACKUP, cache.DIRECTORY + '/connection.json'):
            self.assertEqual(device.files[path], before[path])
        self.assertEqual(device.files[cache.BUNDLE], b'new-bundle')
        self.assertEqual(device.files[cache.DATABASE], b'new-catalogue')
        self.assertTrue(device.running)

    def test_partial_replace_and_failed_start_restore_pre_refresh_state(self):
        for failure in ('partial-move', 'startup'):
            with self.subTest(failure=failure):
                device = MemoryDevice()
                before = device.files.copy()
                device.fail_next_database_move = failure == 'partial-move'
                with self.assertRaises(RuntimeError):
                    self.run_refresh(device, startup_failure=failure == 'startup')
                self.assertEqual(device.files, before)
                self.assertTrue(device.running)


if __name__ == '__main__':
    unittest.main()
