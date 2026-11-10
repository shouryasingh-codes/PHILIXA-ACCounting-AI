from contextlib import closing
"""Source acceptance only; never launches a blocked executable or posts to Tally."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from helper.migration import migrate
from helper.network_diagnostics import failure_record
from helper.package_runtime import startup_enabled
from helper.msix_manifest import manifest


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = Path(self.temp.name)/'legacy'; self.old.mkdir()
        self.new = Path(self.temp.name)/'package'
        (self.old/'settings.json').write_text(json.dumps({'base':'https://philixa.invalid','paused':True}))
        self.db = sqlite3.connect(self.old/'sync.sqlite3')
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE actions (id TEXT PRIMARY KEY, state TEXT)')
        self.db.execute("INSERT INTO actions VALUES ('same-action','verification_pending')")
        self.db.commit()

    def test_wal_backup_preserves_pending_identity_and_source(self):
        self.assertTrue(migrate(self.old,self.new))
        with closing(sqlite3.connect(self.new/'sync.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT * FROM actions').fetchall(), [('same-action','verification_pending')])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        self.assertTrue((self.old/'settings.json').exists())
        self.assertTrue((self.old/'sync.sqlite3').exists())
        self.assertFalse(migrate(self.old,self.new))

    def test_invalid_settings_never_marks_migrated(self):
        (self.old/'settings.json').write_text('[]')
        with self.assertRaises(RuntimeError): migrate(self.old,self.new)
        self.assertFalse((self.new/'migration-v1.json').exists())

    def test_existing_destination_never_overwritten(self):
        self.new.mkdir(); (self.new/'settings.json').write_text('{"existing":true}')
        with self.assertRaises(RuntimeError): migrate(self.old,self.new)
        self.assertIn('existing',(self.new/'settings.json').read_text())

    def test_interrupted_promotion_recovers_same_backup(self):
        from helper import migration
        with patch.object(migration,'_finish',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): migrate(self.old,self.new)
        self.assertFalse((self.new/'migration-v1.json').exists())
        self.assertTrue(migrate(self.old,self.new))
        self.assertTrue((self.new/'migration-v1.json').exists())

    def test_modified_interrupted_backup_is_rejected(self):
        from helper import migration
        with patch.object(migration,'_finish',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): migrate(self.old,self.new)
        (self.new/'legacy-backup-v1/settings.json.staged').write_text('{}')
        with self.assertRaises(RuntimeError): migrate(self.old,self.new)


class PackageTests(unittest.TestCase):
    def test_retirement_requires_enabled_startup_and_migration(self):
        from helper.legacy_retirement import retire_after_verified_read
        with patch('helper.legacy_retirement.subprocess.run') as run:
            self.assertFalse(retire_after_verified_read('unused','unused',False))
            run.assert_not_called()

    def test_no_identity_no_package(self):
        with self.assertRaises(ValueError): manifest({})

    def test_manifest_restricts_lifecycle_and_privileges(self):
        # Test-only metadata. Never written into a release artifact.
        xml = manifest(dict(partner_center_verified=True,name='Test.Connector',publisher='CN=TestOwner',
                            product_id='9ABCDEFGHIJK',publisher_display_name='TestOwner'))
        root=ET.fromstring(xml)
        self.assertIn('10.0.19045.0',xml)
        self.assertIn('3.7.1.0',xml)
        self.assertIn('windows.startupTask',xml)
        self.assertIn('runFullTrust',xml)
        self.assertNotIn('allowElevation',xml)
        self.assertNotIn('internetClientServer',xml)
        self.assertNotIn('schtasks',xml)

    def test_disabled_startup_is_not_enabled(self):
        for state in ('disabled','disabled_by_user','disabled_by_policy','unknown'):
            self.assertFalse(startup_enabled(state))
        self.assertTrue(startup_enabled('enabled'))

    def test_exception_messages_and_locals_are_not_logged(self):
        try: raise FileNotFoundError('Bearer SECRET invoice CUSTOMER password')
        except Exception as exc: result=failure_record(exc)
        serialized=json.dumps(result)
        for secret in ('SECRET','CUSTOMER','Bearer','password'):
            self.assertNotIn(secret,serialized)
        self.assertEqual(result['exception_type'],'FileNotFoundError')
        self.assertGreater(result['frames'][-1]['line'],0)


if __name__=='__main__': unittest.main()
