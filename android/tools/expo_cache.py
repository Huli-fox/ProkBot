"""Modify only Expo's update catalogue, preserving the embedded release and assets."""
import hashlib
import json
import sqlite3
import time
import uuid

UPDATE_ID = uuid.UUID('b1e722c3-9174-4be8-a05c-725b4bc75d37')
EMBEDDED_ID = uuid.UUID('4727f432-0be1-4c13-bad4-a8a121597e9f')
RUNTIME = '2938e8288ad0e03aa42443541b21c250fde0fa3d'
ROOM_HASH = 'f2331836f27deacc936e75b3f1a360bd'
FILENAME = 'prokbot-gateway-3050.hbc'


def validate(db, *, installed=False):
    if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise ValueError('Invalid Expo database')
    if db.execute('SELECT identity_hash FROM room_master_table WHERE id=42').fetchone()[0] != ROOM_HASH:
        raise ValueError('Unsupported Expo schema')
    rows = db.execute('SELECT id,runtime_version FROM updates').fetchall()
    expected = {EMBEDDED_ID.bytes, UPDATE_ID.bytes} if installed else {EMBEDDED_ID.bytes}
    if {bytes(row[0]) for row in rows} != expected or any(row[1] != RUNTIME for row in rows):
        raise ValueError('Unknown cached update. Restore or inspect the cache before applying this recipe')


def add_update(source, destination, bundle):
    """Source is a consistent SQLite snapshot; destination must not already exist."""
    if destination.exists():
        raise ValueError('Output database already exists')
    original = sqlite3.connect(source)
    try:
        validate(original)
        target = sqlite3.connect(destination)
        try:
            original.backup(target)
            target.execute('PRAGMA journal_mode=DELETE')
            target.execute('PRAGMA foreign_keys=ON')
            target.row_factory = sqlite3.Row
            update = dict(target.execute('SELECT * FROM updates WHERE id=?', (EMBEDDED_ID.bytes,)).fetchone())
            old_asset_id = update['launch_asset_id']
            asset = dict(target.execute('SELECT * FROM assets WHERE id=?', (old_asset_id,)).fetchone())
            asset_id = target.execute('SELECT max(id)+1 FROM assets').fetchone()[0]
            asset.update(id=asset_id, key='prokbot-' + str(UPDATE_ID), relative_path=FILENAME,
                         url=None, hash=hashlib.sha256(bundle).digest(), expected_hash=None,
                         download_time=int(time.time() * 1000), marked_for_deletion=0)
            manifest = json.loads(update['manifest'])
            manifest['id'] = str(UPDATE_ID)
            manifest['commitTime'] = update['commit_time'] + 1
            update.update(id=UPDATE_ID.bytes, launch_asset_id=asset_id, commit_time=update['commit_time'] + 1,
                          manifest=json.dumps(manifest, separators=(',', ':')), status=1, keep=1,
                          successful_launch_count=0, failed_launch_count=0)
            for table, values in [('assets', asset), ('updates', update)]:
                target.execute(f'INSERT INTO {table} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', list(values.values()))
            ids = target.execute('SELECT asset_id FROM updates_assets WHERE update_id=?', (EMBEDDED_ID.bytes,)).fetchall()
            if old_asset_id not in [row[0] for row in ids]:
                raise ValueError('Embedded launch asset association missing')
            for row in ids:
                target.execute('INSERT INTO updates_assets(update_id,asset_id) VALUES (?,?)',
                               (UPDATE_ID.bytes, asset_id if row[0] == old_asset_id else row[0]))
            if target.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Update asset consistency check failed')
            target.commit()
        finally:
            target.close()
    finally:
        original.close()


def refresh_update(source, destination, previous_bundle, bundle):
    """Replace our own launch asset hash without losing the current catalogue state."""
    if destination.exists():
        raise ValueError('Output database already exists')
    original = sqlite3.connect(source)
    try:
        validate(original, installed=True)
        row = original.execute('''SELECT a.id,a.relative_path,a.key,a.hash FROM assets a
            JOIN updates u ON u.launch_asset_id=a.id WHERE u.id=?''', (UPDATE_ID.bytes,)).fetchone()
        if (not row or row[1] != FILENAME or row[2] != 'prokbot-' + str(UPDATE_ID)
                or row[3] != hashlib.sha256(previous_bundle).digest()):
            raise ValueError('Installed launch asset does not match the saved bundle')
        # Do not change an asset shared with another update.
        links = original.execute('SELECT update_id FROM updates_assets WHERE asset_id=?', (row[0],)).fetchall()
        if links != [(UPDATE_ID.bytes,)]:
            raise ValueError('Unexpected shared launch asset')
        target = sqlite3.connect(destination)
        try:
            original.backup(target)
            target.execute('PRAGMA journal_mode=DELETE')
            target.execute('UPDATE assets SET hash=?,download_time=? WHERE id=?',
                           (hashlib.sha256(bundle).digest(), int(time.time() * 1000), row[0]))
            if target.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Update asset consistency check failed')
            target.commit()
        finally:
            target.close()
    finally:
        original.close()
