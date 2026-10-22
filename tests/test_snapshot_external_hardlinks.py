import json
import os
from pathlib import Path
import tempfile
import unittest
from drive_manager.core import Store
from drive_manager import manifests,snapshots

class ExternalHardlinkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'tree';self.source.mkdir();self.archive=self.root/'archive';self.archive.mkdir()
        self.file=self.source/'library.py';self.file.write_text('unique library payload\n');os.chmod(self.file,0o640);os.setxattr(self.file,'user.test',b'preserve')
        self.alias=self.root/'cache-alias';os.link(self.file,self.alias)
        self.store=Store(self.root/'state',[self.source,self.archive],reserve=0)
    def capture(self):
        ident=manifests.enqueue_manifest(self.store,str(self.source))
        with self.store.db() as db:
            db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
        return [ident]
    def job(self):
        ident=snapshots.enqueue(self.store,self.capture(),str(self.archive),materialize_external_hardlinks=True)
        with self.store.db() as db:
            db.execute("update jobs set status='running' where id=?",(ident,));return dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
    def test_independent_backup_preserves_payload_metadata_and_original_aliases(self):
        job=self.job();before=manifests.file_signature(self.file);snapshots.run(self.store,job);receipt=snapshots.catalog(self.store)[0]['receipt']
        self.assertTrue(receipt['restored_and_verified']);self.assertTrue(receipt['materialize_external_hardlinks']);self.assertEqual(receipt['external_hardlink_files'],1)
        self.assertEqual(receipt['external_hardlink_aliases_not_recreated'],1)
        self.assertEqual(manifests.file_signature(self.file),before);self.assertEqual(os.stat(self.file).st_ino,os.stat(self.alias).st_ino)
        topology=json.loads((Path(receipt['destination'])/'external-hardlinks.json').read_text());self.assertEqual(topology['files'][0]['original_nlink'],2)
        snapshots.run(self.store,job)
    def test_default_mode_still_blocks_external_hardlinks(self):
        with self.assertRaisesRegex(ValueError,'hardlinked'):snapshots.enqueue(self.store,self.capture(),str(self.archive))
    def test_internal_aliases_are_not_silently_flattened(self):
        os.link(self.file,self.source/'internal-alias')
        with self.assertRaisesRegex(ValueError,'Internal hardlink groups'):snapshots.enqueue(self.store,self.capture(),str(self.archive),materialize_external_hardlinks=True)
    def test_changed_external_alias_holds_publication(self):
        job=self.job();self.alias.write_text('new changes through external alias')
        with self.assertRaisesRegex(ValueError,'differs'):snapshots.run(self.store,job)
        self.assertEqual(self.file.read_text(),'new changes through external alias')
    def test_topology_record_tampering_blocks_reconciliation(self):
        job=self.job();snapshots.run(self.store,job);destination=Path(json.loads(job['payload'])['destination']);(destination/'external-hardlinks.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'topology digest'):snapshots.run(self.store,job)
    def test_mode_requires_boolean(self):
        with self.assertRaisesRegex(ValueError,'boolean'):snapshots.inputs(self.store,[],materialize_external_hardlinks='true')
