import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from drive_manager.core import Store
from drive_manager import manifests, snapshots
from drive_manager.workspaces import git


class FullFileSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'source';self.source.mkdir()
        self.archive=self.base/'archive';self.archive.mkdir()
        self.first=self.source/'notes';self.first.mkdir();self.second=self.source/'notes-maint';self.second.mkdir()
        (self.first/'empty-directory').mkdir();(self.first/'dirty.txt').write_text('unique local edits')
        (self.first/'ignored.bin').write_bytes(b'not committed\0\xff')
        (self.first/'inside-link').symlink_to('dirty.txt');(self.first/'outside-link').symlink_to('/does/not/exist')
        (self.second/'-literal filename\n.txt').write_text('second tree')
        os.chmod(self.first/'dirty.txt',0o640);os.setxattr(self.first/'dirty.txt','user.archive-test',b'\0\xffraw')
        os.utime(self.first/'dirty.txt',ns=(1700000000123456789,1700000000123456789))
        self.store=Store(self.base/'state',[self.source,self.archive],reserve=0)

    def capture(self):
        ids=[]
        for source in (self.first,self.second):
            ident=manifests.enqueue_manifest(self.store,str(source));ids.append(ident)
            with self.store.db() as db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,));job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
            manifests.run_manifest(self.store,job)
            with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(ident,))
        return ids

    def job(self):
        ident=snapshots.enqueue(self.store,self.capture(),str(self.archive))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())

    def test_full_trees_restore_payloads_links_xattrs_modes_and_nanosecond_times(self):
        job=self.job();before=manifests.file_signature(self.first/'dirty.txt');snapshots.run(self.store,job)
        receipt=snapshots.catalog(self.store)[0]['receipt'];self.assertTrue(receipt['restored_and_verified'])
        self.assertFalse(receipt['retirement_authorized']);self.assertEqual(receipt['space_reclaimed'],0)
        self.assertEqual(manifests.file_signature(self.first/'dirty.txt'),before)
        self.assertEqual(os.readlink(self.first/'outside-link'),'/does/not/exist')
        self.assertEqual(os.getxattr(self.first/'dirty.txt','user.archive-test'),b'\0\xffraw')
        with tarfile.open(Path(receipt['destination'])/'trees.tar') as archive:
            self.assertIn('notes-maint/-literal filename\n.txt',archive.getnames())
        snapshots.run(self.store,job)  # Reconcile after a crash following atomic publication.

    def test_changed_source_is_held_before_copy(self):
        job=self.job();(self.first/'dirty.txt').write_text('newer unapproved edits')
        with self.assertRaisesRegex(ValueError,'differs'):snapshots.run(self.store,job)
        self.assertEqual((self.first/'dirty.txt').read_text(),'newer unapproved edits')
        self.assertFalse(Path(json.loads(job['payload'])['destination']).exists())

    def test_duplicate_pending_requests_do_not_copy_the_same_trees_twice(self):
        identifiers=self.capture();first=snapshots.enqueue(self.store,identifiers,str(self.archive))
        second=snapshots.enqueue(self.store,list(reversed(identifiers)),str(self.archive))
        self.assertEqual(first,second)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE kind='workspace_snapshot'").fetchone()[0],1)

    def test_hardlinked_files_require_a_separate_preservation_plan(self):
        os.link(self.first/'dirty.txt',self.first/'same-inode')
        with self.assertRaisesRegex(ValueError,'hardlinked'):snapshots.enqueue(self.store,self.capture(),str(self.archive))

    def test_changes_during_copy_hold_publication_and_retain_attempt_on_retry(self):
        job=self.job();original=snapshots.command
        def mutate(args,**kwargs):
            result=original(args,**kwargs)
            if '--create' in args:(self.first/'dirty.txt').write_text('newer edits')
            return result
        with patch.object(snapshots,'command',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'differs'):snapshots.run(self.store,job)
        destination=Path(json.loads(job['payload'])['destination']);self.assertFalse(destination.exists())
        with self.assertRaises(ValueError):snapshots.run(self.store,job)
        self.assertTrue(list(destination.parent.glob('.retained-attempt-*')))

    def test_malformed_extra_tar_member_is_rejected_before_extraction(self):
        identifiers=self.capture();items=snapshots.inputs(self.store,identifiers);path=self.base/'malicious.tar'
        with tarfile.open(path,'w') as archive:archive.addfile(tarfile.TarInfo('../escape'))
        with self.assertRaisesRegex(ValueError,'Unexpected'):snapshots.audit_tar(path,items,lambda:None)
        self.assertFalse((self.base/'escape').exists())

    def test_manifest_tampering_and_public_receipt_substitution_are_rejected(self):
        job=self.job();snapshots.run(self.store,job)
        destination=Path(json.loads(job['payload'])['destination']);receipt_path=destination/'receipt.json'
        receipt=json.loads(receipt_path.read_text());receipt['source_retained']=False;receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'private verification'):snapshots.run(self.store,job)
        ident=json.loads(job['payload'])['manifests'][0]
        with sqlite3.connect(self.store.state/'workspace-manifests'/ident/'manifest.sqlite3') as db:
            db.execute("UPDATE entries SET sha256=? WHERE relative='dirty.txt'",('0'*64,))
        with self.assertRaisesRegex(ValueError,'seal'):snapshots.inputs(self.store,[ident])

    def test_workspace_worker_runs_snapshot_jobs(self):
        ident=snapshots.enqueue(self.store,self.capture(),str(self.archive))
        thread=threading.Thread(target=self.store.worker,args=('workspace',));thread.start()
        try:
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                with self.store.db() as db:row=db.execute('select status,message from jobs where id=?',(ident,)).fetchone()
                if row['status'] in ('completed','blocked'):break
                time.sleep(.1)
            self.assertEqual(row['status'],'completed',row['message'])
        finally:self.store.stop.set();thread.join(5)

    def test_linked_git_worktrees_are_captured_together_without_repairing_sources(self):
        (self.second/'-literal filename\n.txt').unlink();self.second.rmdir();git(self.first,'init');git(self.first,'config','user.name','Archive Test');git(self.first,'config','user.email','archive@example.invalid')
        git(self.first,'add','dirty.txt');git(self.first,'commit','-m','tracked history')
        git(self.first,'worktree','add','-b','maintenance',str(self.second))
        (self.first/'dirty.txt').write_text('uncommitted local change');before=(self.second/'.git').read_bytes()
        job=self.job();snapshots.run(self.store,job);receipt=snapshots.catalog(self.store)[0]['receipt']
        with tarfile.open(Path(receipt['destination'])/'trees.tar') as archive:
            self.assertIn('notes/.git/worktrees/notes-maint/gitdir',archive.getnames())
            self.assertEqual(archive.extractfile('notes-maint/.git').read(),before)
        self.assertEqual((self.second/'.git').read_bytes(),before);self.assertEqual((self.first/'dirty.txt').read_text(),'uncommitted local change')
