import json,os,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from drive_manager.core import Store
from drive_manager.workspaces import git
from drive_manager import manifests,object_repairs

class ObjectRepairTests(unittest.TestCase):
    location=None
    drive_roots=None
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=self.location);self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.drive=self.base/'drive';self.drive.mkdir()
        origin=self.drive/'origin';origin.mkdir();git(origin,'init');git(origin,'config','user.name','Test');git(origin,'config','user.email','test@example.invalid')
        (origin/'file').write_text('unique original data');git(origin,'add','.');git(origin,'commit','-m','fixture')
        self.repo=self.drive/'repo.git';git(origin,'clone','--bare','--no-hardlinks',str(origin),str(self.repo));self.oid=git(origin,'rev-parse','HEAD:file').strip();self.rel='objects/'+self.oid[:2]+'/'+self.oid[2:];self.source=self.repo/self.rel
        self.artifact=self.drive/'recovered';shutil.copy2(self.source,self.artifact);self.good=self.artifact.read_bytes()
        self.store=Store(self.base/'state',self.drive_roots or [self.drive],reserve=0);self.manifest=manifests.enqueue_manifest(self.store,self.repo)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(self.manifest,));job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(self.manifest,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(self.manifest,))
        before=self.source.stat();self.bad=self.good[:-1]+bytes([self.good[-1]^1]);os.chmod(self.source,0o600);self.source.write_bytes(self.bad);os.chmod(self.source,before.st_mode);os.utime(self.source,ns=(before.st_atime_ns,before.st_mtime_ns))
    def propose(self):return object_repairs.propose(self.store,self.manifest,self.rel,self.artifact,'Restore exact object; retain damaged original')
    def claim(self,ident):
        self.store.approve([ident])
        with self.store.db() as db:
            c=dict(db.execute('SELECT * FROM candidates WHERE id=?',(ident,)).fetchone());db.execute("UPDATE jobs SET status='running' WHERE id=?",(c['job_id'],));job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(c['job_id'],)).fetchone())
        return job,c
    def test_reviewed_repair_full_fsck_quarantine_and_replay(self):
        ident=self.propose();job,c=self.claim(ident);self.store.run_transfer(job)
        r=json.loads((self.store.state/'git-object-repairs'/(job['id']+'.json')).read_text())
        self.assertEqual(r['phase'],'verified');self.assertTrue(r['repository_fsck_verified']);self.assertEqual(self.source.read_bytes(),self.good);self.assertEqual(Path(r['quarantine']).read_bytes(),self.bad)
        self.store.run_transfer(job);self.assertEqual(self.source.read_bytes(),self.good)
    def test_policy_and_unapproved_run_are_rejected(self):
        ident=self.propose()
        with self.assertRaisesRegex(ValueError,'checkbox'):self.store.approve([ident],policy=True,policy_id='none')
        with self.store.db() as db:c=dict(db.execute('SELECT * FROM candidates WHERE id=?',(ident,)).fetchone())
        with self.assertRaisesRegex(ValueError,'checkbox'):object_repairs.run(self.store,{'id':'x'},c)
        self.assertEqual(self.source.read_bytes(),self.bad)
    def test_changed_source_blocks_approval_and_no_job_is_queued(self):
        ident=self.propose();os.chmod(self.source,0o600);self.source.write_bytes(b'new source work')
        with self.assertRaisesRegex(ValueError,'source changed'):self.store.approve([ident])
        with self.store.db() as db:self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE kind='transfer'").fetchone()[0],0)
    def test_changed_recovery_blocks_approval(self):
        ident=self.propose();self.artifact.write_bytes(b'unverified replacement')
        with self.assertRaisesRegex(ValueError,'artifact changed'):self.store.approve([ident])
    def test_wrong_recovery_never_gets_proposed(self):
        self.artifact.write_bytes(b'wrong replacement')
        with self.assertRaisesRegex(ValueError,'sealed manifest'):self.propose()
    def test_source_changed_after_approval_is_retained(self):
        ident=self.propose();job,c=self.claim(ident);os.chmod(self.source,0o600);self.source.write_bytes(b'user work')
        with self.assertRaisesRegex(ValueError,'source changed'):self.store.run_transfer(job)
        self.assertEqual(self.source.read_bytes(),b'user work')
    def test_verification_failure_rolls_back_and_retry_is_safe(self):
        ident=self.propose();job,c=self.claim(ident)
        with patch.object(object_repairs,'git',side_effect=ValueError('injected full integrity failure')):
            with self.assertRaisesRegex(ValueError,'integrity failure'):self.store.run_transfer(job)
        self.assertEqual(self.source.read_bytes(),self.bad)
        r=json.loads((self.store.state/'git-object-repairs'/(job['id']+'.json')).read_text());self.assertEqual(r['phase'],'rolled-back')
        self.store.run_transfer(job);self.assertEqual(self.source.read_bytes(),self.good)
    def test_new_work_is_not_overwritten_during_failed_rollback(self):
        ident=self.propose();job,c=self.claim(ident)
        def altered(*args,**kwargs):
            os.chmod(self.source,0o600);self.source.write_bytes(b'newer concurrent work');raise ValueError('injected failure')
        with patch.object(object_repairs,'git',side_effect=altered):
            with self.assertRaisesRegex(ValueError,'injected failure'):self.store.run_transfer(job)
        r=json.loads((self.store.state/'git-object-repairs'/(job['id']+'.json')).read_text());self.assertEqual(r['phase'],'needs-attention');self.assertEqual(self.source.read_bytes(),b'newer concurrent work');self.assertEqual(Path(r['quarantine']).read_bytes(),self.bad)
    def test_security_preview_cannot_change_other_metadata(self):
        native=object_repairs.metadata(self.source);native['sddl']='original security'
        changed=dict(native,sddl='replacement security',mtime_ns=native['mtime_ns']+1)
        with patch.object(object_repairs,'metadata',side_effect=[native,changed]):
            with self.assertRaisesRegex(ValueError,'security descriptor difference'):
                object_repairs.propose(self.store,self.manifest,self.rel,self.artifact,'review',replacement_preview=self.artifact)
    def test_posix_security_override_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'security descriptor difference'):
            object_repairs.propose(self.store,self.manifest,self.rel,self.artifact,'review',replacement_preview=self.artifact)

    def test_quarantine_directory_collision_never_overwrites(self):
        ident=self.propose();job,c=self.claim(ident);folder=self.drive/'archive/workspaces/git-object-repairs'/job['id'];folder.mkdir(parents=True);(folder/'unrelated').write_text('keep')
        with self.assertRaises(FileExistsError):self.store.run_transfer(job)
        self.assertEqual((folder/'unrelated').read_text(),'keep');self.assertEqual(self.source.read_bytes(),self.bad)
