import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drive_manager.core import Store
from drive_manager import manifests

class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.drive=self.root/'drive';self.drive.mkdir()
        self.source=self.drive/'source';self.source.mkdir()
        (self.source/'.git').mkdir();(self.source/'.git'/'config').write_text('repository configuration')
        (self.source/'ignored.bin').write_bytes(b'essential ignored data')
        (self.source/'local.txt').write_text('uncommitted work')
        self.store=Store(self.root/'state',[self.drive],reserve=0)
    def job(self):
        ident=manifests.enqueue_manifest(self.store,str(self.source))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
    def test_all_files_and_resume_cache_and_nested_git_config(self):
        job=self.job();manifests.run_manifest(self.store,job)
        result=manifests.catalog(self.store)[0]['result']
        self.assertEqual(result['files'],3)
        self.assertFalse(result['archive_copy_verified'])
        matches=manifests.browse(self.store,job['id'],'config')
        self.assertEqual([i['path'] for i in matches['items']],['.git/config'])
        self.assertEqual(manifests.browse(self.store,job['id'],'%')['items'],[])
        with self.assertRaises(ValueError):manifests.browse(self.store,'../outside')
        before=result['sha256']
        with patch.object(manifests,'checked_hash',side_effect=AssertionError('unchanged file rehashed')):
            manifests.run_manifest(self.store,job)
        self.assertEqual(manifests.catalog(self.store)[0]['result']['sha256'],before)
        self.assertEqual((self.source/'local.txt').read_text(),'uncommitted work')
    def test_tree_added_during_hashing_rejects_manifest(self):
        original=manifests.checked_hash
        def add_file(*args):
            value=original(*args);(self.source/'new-file').write_text('new work');return value
        job=self.job()
        with patch.object(manifests,'checked_hash',side_effect=add_file):
            with self.assertRaisesRegex(ValueError,'Tree or native metadata changed'):
                manifests.run_manifest(self.store,job)
        self.assertIsNone(manifests.catalog(self.store)[0]['result'])
        manifests.run_manifest(self.store,job)
        self.assertEqual(manifests.catalog(self.store)[0]['result']['files'],4)
    def test_link_recorded_without_following_and_special_file_blocks(self):
        outside=self.drive/'outside';outside.mkdir();(outside/'unique.txt').write_text('outside source')
        (self.source/'link').symlink_to(outside,target_is_directory=True)
        job=self.job();manifests.run_manifest(self.store,job)
        result=manifests.catalog(self.store)[0]['result']
        self.assertEqual(result['files'],3)
        import sqlite3,os
        db=sqlite3.connect(result['manifest'])
        self.assertEqual(json.loads(db.execute("select native from entries where relative='link'").fetchone()[0])['target'],str(outside));db.close()
        os.mkfifo(self.source/'pipe')
        with self.assertRaisesRegex(ValueError,'special'):
            manifests.run_manifest(self.store,job)
    def test_rename_and_metadata_changes_between_passes_block(self):
        original=manifests.enumerate_tree;calls=[0]
        def mutate(*args):
            calls[0]+=1
            if calls[0]==2:(self.source/'local.txt').chmod(0o600)
            return original(*args)
        job=self.job()
        with patch.object(manifests,'enumerate_tree',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'identity changed'):
                manifests.run_manifest(self.store,job)
    def test_primary_workspace_readonly_scope_is_separate_from_transfer_roots(self):
        home=self.root/'home';primary=home/'workspace'/'project';primary.mkdir(parents=True)
        (primary/'local.txt').write_text('active code')
        with patch.object(Path,'home',return_value=home):
            ident=manifests.enqueue_manifest(self.store,str(primary))
            with self.store.db() as db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
                job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
            manifests.run_manifest(self.store,job)
        self.assertEqual(manifests.catalog(self.store)[0]['result']['files'],1)
        with self.assertRaisesRegex(ValueError,'outside'):
            self.store.safe_path(str(primary))

    def test_comparison_distinguishes_payloads_and_excludes_git_internals(self):
        left=self.job();manifests.run_manifest(self.store,left)
        other=self.drive/'other';other.mkdir()
        (other/'ignored.bin').write_bytes(b'essential ignored data')
        (other/'local.txt').write_text('different source revision')
        (other/'new.txt').write_text('unique other content')
        ident=manifests.enqueue_manifest(self.store,str(other))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            right=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,right)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id IN (?,?)",(left['id'],right['id']))
        result=manifests.compare(self.store,left['id'],right['id'])
        self.assertEqual(result['counts'],dict(same_payload=1,different_payload=1,only_left=0,only_right=1,different_kind=0))
        self.assertFalse(result['retirement_authorized'])
        self.assertEqual(len(manifests.comparisons(self.store)),1)

    def test_changed_open_file_is_not_accepted(self):
        path=self.source/'local.txt';sig=manifests.file_signature(path)
        path.write_text('different data')
        with self.assertRaisesRegex(ValueError,'changed'):
            manifests.checked_hash(path,sig,lambda:None)
