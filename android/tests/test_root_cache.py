import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import expo_cache
import hermes


class AddressTests(unittest.TestCase):
    def test_origins(self):
        self.assertEqual(hermes.origin('HTTPS://Example.COM:443/'), 'https://example.com')
        self.assertEqual(hermes.origin('https://[::1]:8443/'), 'https://[::1]:8443')
        for address in ('http://host', 'http://127.0.0.1:18081', 'https://user:pass@host',
                        'https://host/api', 'https://host?q=1', 'https://host?', 'https://host#',
                        'https://host:0', 'https://host:99999', 'https://ho\nst'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                hermes.origin(address)


class CacheTests(unittest.TestCase):
    def test_additive_update_preserves_embedded_assets_and_rejects_unknown_update(self):
        with tempfile.TemporaryDirectory(prefix='prokbot-cache-test-') as temp:
            source, destination = Path(temp) / 'original.db', Path(temp) / 'patched.db'
            db = sqlite3.connect(source)
            db.executescript('''
                CREATE TABLE room_master_table(id INTEGER PRIMARY KEY,identity_hash TEXT);
                CREATE TABLE assets(id INTEGER PRIMARY KEY,key TEXT,type TEXT,relative_path TEXT,
                    url TEXT,hash BLOB,expected_hash TEXT,download_time INTEGER,marked_for_deletion INTEGER);
                CREATE TABLE updates(id BLOB PRIMARY KEY,runtime_version TEXT,commit_time INTEGER,manifest TEXT,
                    launch_asset_id INTEGER REFERENCES assets(id),status INTEGER,keep INTEGER,
                    successful_launch_count INTEGER,failed_launch_count INTEGER);
                CREATE TABLE updates_assets(update_id BLOB REFERENCES updates(id),asset_id INTEGER REFERENCES assets(id),
                    PRIMARY KEY(update_id,asset_id));
            ''')
            db.execute('INSERT INTO room_master_table VALUES(42,?)', (expo_cache.ROOM_HASH,))
            db.execute("INSERT INTO assets VALUES(17,'original-js','js','embedded',NULL,NULL,NULL,NULL,0)")
            db.execute("INSERT INTO assets VALUES(18,'original-image','png','resource',NULL,NULL,NULL,NULL,0)")
            db.execute('INSERT INTO updates VALUES(?,?,?,?,17,1,1,4,0)',
                       (expo_cache.EMBEDDED_ID.bytes, expo_cache.RUNTIME, 100,
                        json.dumps({'id': str(expo_cache.EMBEDDED_ID), 'commitTime': 100, 'assets': []})))
            db.executemany('INSERT INTO updates_assets VALUES(?,?)', [(expo_cache.EMBEDDED_ID.bytes, i) for i in (17, 18)])
            db.commit(); db.close()
            original_bytes = source.read_bytes()
            bundle = b'test-only-content'
            expo_cache.add_update(source, destination, bundle)
            self.assertEqual(source.read_bytes(), original_bytes)
            db = sqlite3.connect(destination)
            try:
                self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(db.execute('SELECT launch_asset_id FROM updates WHERE id=?', (expo_cache.EMBEDDED_ID.bytes,)).fetchone()[0], 17)
                new_id = db.execute('SELECT launch_asset_id FROM updates WHERE id=?', (expo_cache.UPDATE_ID.bytes,)).fetchone()[0]
                self.assertEqual(db.execute('SELECT asset_id FROM updates_assets WHERE update_id=? ORDER BY asset_id', (expo_cache.UPDATE_ID.bytes,)).fetchall(), [(18,), (new_id,)])
                self.assertEqual(db.execute('SELECT hash FROM assets WHERE id=?', (new_id,)).fetchone()[0], hashlib.sha256(bundle).digest())
                with self.assertRaisesRegex(ValueError, 'Unknown cached update'):
                    expo_cache.validate(db)
            finally:
                db.close()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                expo_cache.add_update(source, destination, bundle)
            # Refresh must preserve the embedded entry, launch counters and unrelated
            # assets while changing only our own launch asset hash and timestamp.
            refreshed = Path(temp) / 'refreshed.db'
            before = destination.read_bytes()
            new_bundle = b'new-test-only-content'
            expo_cache.refresh_update(destination, refreshed, bundle, new_bundle)
            self.assertEqual(destination.read_bytes(), before)
            db = sqlite3.connect(refreshed)
            old = sqlite3.connect(destination)
            try:
                expo_cache.validate(db, installed=True)
                for table in ('updates', 'updates_assets', 'room_master_table'):
                    self.assertEqual(db.execute('SELECT * FROM ' + table).fetchall(),
                                     old.execute('SELECT * FROM ' + table).fetchall())
                self.assertEqual(db.execute('SELECT * FROM assets WHERE id IN (17,18)').fetchall(),
                                 old.execute('SELECT * FROM assets WHERE id IN (17,18)').fetchall())
                self.assertEqual(db.execute('SELECT hash FROM assets WHERE id=?', (new_id,)).fetchone()[0],
                                 hashlib.sha256(new_bundle).digest())
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            finally:
                db.close(); old.close()
            with self.assertRaisesRegex(ValueError, 'does not match'):
                expo_cache.refresh_update(destination, Path(temp) / 'bad.db', b'unexpected', new_bundle)
            db = sqlite3.connect(destination)
            db.execute("UPDATE updates SET id=? WHERE id=?", (b'unrecognized-ota', expo_cache.UPDATE_ID.bytes))
            db.commit(); db.close()
            with self.assertRaisesRegex(ValueError, 'Unknown cached update'):
                expo_cache.refresh_update(destination, Path(temp) / 'unknown.db', bundle, new_bundle)


@unittest.skipUnless(os.environ.get('PROKBOT_TEST_BUNDLE'), 'Set PROKBOT_TEST_BUNDLE to an extracted official HBC')
class RecipeTests(unittest.TestCase):
    def test_recipe_and_integrity(self):
        path = Path(os.environ['PROKBOT_TEST_BUNDLE'])
        original = path.read_bytes()
        result = hermes.patch(original, 'http://127.0.0.1:18081', 'PROKBOT_ASSESSMENT_ONLY_NOT_A_REAL_TOKEN_0000',
                              probe=True, gateway_send=False)
        reference = path.with_name('probe.android.hbc')
        if reference.exists():
            self.assertEqual(result, reference.read_bytes())
        self.assertEqual(result[-20:], hashlib.sha1(result[:-20]).digest())
        self.assertEqual(result[hermes.OLD_BODY:hermes.OLD_BODY + 4], original[hermes.OLD_BODY:hermes.OLD_BODY + 4])
        for start, end in [(0, 32), (36, hermes.HEADER), (hermes.HEADER + 12, len(original) - 20)]:
            self.assertEqual(result[start:end], original[start:end])
        with self.assertRaises(ValueError):
            hermes.patch(original[:-1] + b'x', 'https://host', 'a' * 32)
        with self.assertRaises(ValueError):
            hermes.patch(original, 'https://host', 'short')

    def test_gateway_sender_uses_existing_fallback_without_rewriting_other_functions(self):
        original = Path(os.environ['PROKBOT_TEST_BUNDLE']).read_bytes()
        args = (original, 'https://127.0.0.1:18443', 'TEST_ONLY_DEVICE_TOKEN_' + '0' * 24)
        old = hermes.patch(*args, gateway_send=False)
        result = hermes.patch(*args)
        self.assertEqual([i for i, (a, b) in enumerate(zip(old[:-20], result[:-20])) if a != b],
                         [hermes.SEND_SOURCE + 2])
        self.assertEqual(result[-20:], hashlib.sha1(result[:-20]).digest())
        self.assertEqual(struct.unpack_from('<I', result, 32)[0], len(result))
        # DefineOwnById options.grokBotSendSource = r1 (undefined); the existing
        # stampSender(undefined) and ChatSession nullish fallback stay intact.
        self.assertEqual(result[hermes.SEND_SOURCE:hermes.SEND_SOURCE + 6],
                         struct.pack('<BBBBH', 86, 11, 1, 27, 35277))
        for offset, size in ((13619687, 53), (13829872, 1325), (18465363, 23), (13715963, 24)):
            self.assertEqual(result[offset:offset + size], original[offset:offset + size])


if __name__ == '__main__':
    unittest.main()
