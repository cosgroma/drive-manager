import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_relocations as fixtures
from drive_manager import manifests,relocations
from drive_manager.workspaces import git,refs


class ReviewedRestoreTests(unittest.TestCase):
    setUp=fixtures.RelocationTests.setUp
    ready=fixtures.RelocationTests.ready

    def claim(self,ident):
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())

    def changed_archive(self):
        job,candidate=self.ready();relocations.run(self.store,job,candidate)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(job['id'],))
        self.original=job['id'];self.destination=Path(candidate['destination'])
        (self.destination/'newer.txt').write_text('new work created after archival')
        git(self.destination,'add','newer.txt');git(self.destination,'commit','-m','newer archived work')
        (self.destination/'ignored-local-data').write_bytes(b'untracked new data')
        self.new_refs=refs(self.destination)
        self.fresh=manifests.enqueue_manifest(self.store,str(self.destination))
        manifests.run_manifest(self.store,self.claim(self.fresh))
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(self.fresh,))

    def approved(self):
        ident=relocations.propose_reviewed_restore(self.store,self.original,self.fresh)
        self.store.approve([ident])
        with self.store.db() as db:c=dict(db.execute('SELECT * FROM candidates WHERE id=?',(ident,)).fetchone())
        return self.claim(c['job_id']),c

    def test_stale_restore_holds_then_checkbox_baseline_preserves_newer_commits_and_files(self):
        self.changed_archive()
        old=relocations.enqueue_restore(self.store,self.original)
        with self.assertRaisesRegex(ValueError,'differs|changed'):relocations.run_restore(self.store,self.claim(old))
        with self.store.db() as db:db.execute("UPDATE jobs SET status='blocked' WHERE id=?",(old,))
        with self.assertRaisesRegex(ValueError,'existing restoration'):relocations.propose_reviewed_restore(self.store,self.original,self.fresh)
        self.store.control(old,'cancel')
        ident=relocations.propose_reviewed_restore(self.store,self.original,self.fresh)
        with self.assertRaisesRegex(ValueError,'checkbox'):self.store.approve([ident],policy=True)
        self.assertTrue(self.source.is_symlink())
        self.store.approve([ident])
        with self.store.db() as db:c=dict(db.execute('SELECT * FROM candidates WHERE id=?',(ident,)).fetchone())
        job=self.claim(c['job_id']);self.store.run_transfer(job)
        self.store.run_transfer(job)  # Replay must not move or lose newer data.
        self.assertFalse(self.source.is_symlink());self.assertFalse(self.destination.exists())
        self.assertEqual(refs(self.source),self.new_refs)
        self.assertEqual((self.source/'ignored-local-data').read_bytes(),b'untracked new data')
        _,receipt,_=relocations.relocation_receipt(self.store,self.original)
        self.assertEqual(receipt['manifest'],self.manifest)
        self.assertEqual(receipt['restore_manifest'],self.fresh)
        self.assertEqual(receipt['space_reclaimed'],0)

    def test_post_review_edit_blocks_without_removing_alias_or_new_work(self):
        self.changed_archive();job,c=self.approved()
        (self.destination/'newer.txt').write_text('another edit after approval')
        with self.assertRaisesRegex(ValueError,'differs|changed'):self.store.run_transfer(job)
        self.assertTrue(self.source.is_symlink());self.assertTrue(self.destination.exists())
        self.assertEqual((self.source/'newer.txt').read_text(),'another edit after approval')

    def test_unrelated_manifest_collision_and_rejected_baseline_are_not_approved(self):
        self.changed_archive()
        with self.assertRaisesRegex(ValueError,'exact archived tree'):
            relocations.propose_reviewed_restore(self.store,self.original,self.manifest)
        ident=relocations.propose_reviewed_restore(self.store,self.original,self.fresh)
        self.store.reject([ident])
        with self.assertRaisesRegex(ValueError,'rejected'):relocations.propose_reviewed_restore(self.store,self.original,self.fresh)
        # A later fresh manifest can be reviewed, but cannot authorize overwriting a collision.
        fresh=manifests.enqueue_manifest(self.store,str(self.destination));manifests.run_manifest(self.store,self.claim(fresh))
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(fresh,))
        ident=relocations.propose_reviewed_restore(self.store,self.original,fresh)
        relocations.remove_alias(self.source,self.destination);self.source.mkdir();(self.source/'other-user-work').write_text('preserve')
        with self.assertRaisesRegex(ValueError,'compatibility junction'):self.store.approve([ident])
        self.assertTrue(self.destination.exists());self.assertEqual((self.source/'other-user-work').read_text(),'preserve')

    def test_crash_after_publication_recovers_using_approved_fresh_manifest(self):
        self.changed_archive();job,c=self.approved();verify=relocations.verify_tree
        def crash_after_move(store,manifest,base,*args,**kwargs):
            if Path(base)==self.source:raise RuntimeError('crash after publication')
            return verify(store,manifest,base,*args,**kwargs)
        with patch.object(relocations,'verify_tree',side_effect=crash_after_move):
            with self.assertRaisesRegex(RuntimeError,'crash after publication'):self.store.run_transfer(job)
        self.assertFalse(self.source.is_symlink());self.assertFalse(self.destination.exists())
        self.store.run_transfer(job)
        self.assertEqual(refs(self.source),self.new_refs)
        self.assertEqual((self.source/'newer.txt').read_text(),'new work created after archival')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT status FROM candidates WHERE id=?',(c['id'],)).fetchone()[0],'completed')

    def test_crash_between_native_rename_and_receipt_update_reconciles(self):
        self.changed_archive();job,c=self.approved();write=self.store.write_receipt
        def crash_before_receipt(path,record):
            if record.get('phase')=='restore_published':raise RuntimeError('crash before receipt update')
            return write(path,record)
        with patch.object(self.store,'write_receipt',side_effect=crash_before_receipt):
            with self.assertRaisesRegex(RuntimeError,'before receipt update'):self.store.run_transfer(job)
        self.assertFalse(self.destination.exists());self.assertFalse(self.source.is_symlink())
        _,receipt,_=relocations.relocation_receipt(self.store,self.original)
        self.assertEqual(receipt['phase'],'archived')
        self.store.run_transfer(job)
        self.assertEqual(refs(self.source),self.new_refs)
        self.assertEqual((self.source/'ignored-local-data').read_bytes(),b'untracked new data')

    def test_crash_after_alias_removal_rebuilds_only_authorized_missing_alias(self):
        self.changed_archive();job,c=self.approved();remove=relocations.remove_alias
        def crash_after_alias(*args):
            remove(*args);raise RuntimeError('crash after alias removal')
        with patch.object(relocations,'remove_alias',side_effect=crash_after_alias):
            with self.assertRaisesRegex(RuntimeError,'after alias removal'):self.store.run_transfer(job)
        self.assertFalse(self.source.exists());self.assertTrue(self.destination.exists())
        # No durable authorization means it must hold, retaining all archive data.
        proof=self.store.state/'workspace-restorations'/(job['id']+'.json');raw=proof.read_bytes();proof.unlink()
        with self.assertRaisesRegex(ValueError,'compatibility junction'):self.store.run_transfer(job)
        self.assertFalse(self.source.exists());self.assertTrue(self.destination.exists())
        proof.write_bytes(raw);self.store.run_transfer(job)
        self.assertFalse(self.source.is_symlink());self.assertFalse(self.destination.exists())
        self.assertEqual(refs(self.source),self.new_refs)
