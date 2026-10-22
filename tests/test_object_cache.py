import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from drive_manager.core import Store
from drive_manager import manifests,object_cache
from drive_manager.workspaces import git,history_state,enqueue_history,catalog


class ObjectCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.drive=self.root/'drive';self.drive.mkdir()
        working=self.drive/'working';working.mkdir();git(working,'init')
        git(working,'config','user.name','Cache Test');git(working,'config','user.email','cache@example.invalid')
        (working/'source.txt').write_text('unique tracked history');git(working,'add','.');git(working,'commit','-m','initial')
        self.source=self.drive/'source.git';git(working,'clone','--bare','--no-local',str(working),str(self.source))
        git(self.source,'config','--remove-section','remote.origin')
        git(self.source,'repack','-a','-d')
        git(self.source,'symbolic-ref','HEAD','refs/heads/unresolved-default')
        self.store=Store(self.root/'state',[self.drive],reserve=0)

    def capture(self):
        ident=manifests.enqueue_manifest(self.store,str(self.source))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,));job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(ident,))
        return ident

    def test_object_copy_matches_manifest_and_preserves_unresolved_head(self):
        ident=self.capture();before=history_state(self.source);raw=(self.source/'HEAD').read_bytes()
        result=object_cache.prepare(self.store,str(self.source),ident)
        self.assertEqual(history_state(Path(result['mirror']),isolated=True),before)
        self.assertEqual(history_state(self.source),before);self.assertEqual((self.source/'HEAD').read_bytes(),raw)
        self.assertFalse(result['retirement_authorized']);self.assertEqual(result['scope'],'git-object-cache-only')
        for row in result['files']:
            self.assertEqual((self.source/row['relative']).read_bytes(),(Path(result['mirror'])/row['relative']).read_bytes())
            self.assertNotEqual((self.source/row['relative']).stat().st_ino,(Path(result['mirror'])/row['relative']).stat().st_ino)
        git(Path(result['mirror']),'fsck','--full','--no-reflogs',isolated=True)

    def test_changed_object_file_is_rejected_before_cache_is_ready(self):
        ident=self.capture();pack=next((self.source/'objects/pack').glob('*.pack'))
        pack.chmod(0o644)
        with pack.open('ab') as handle:handle.write(b'newer source bytes')
        with self.assertRaises(ValueError):
            object_cache.prepare(self.store,str(self.source),ident)
        self.assertFalse(list((self.store.state/'git-object-caches').glob('*/ready.json')))

    def test_source_tip_change_retains_partial_cache_and_does_not_choose_a_branch(self):
        ident=self.capture();original=object_cache.copy_object;changed=[False]
        def mutate(*args,**kwargs):
            result=original(*args,**kwargs)
            if not changed[0]:
                changed[0]=True;oid=next(iter(history_state(self.source)[0].values()))
                git(self.source,'update-ref','refs/heads/new-tip',oid)
            return result
        with patch.object(object_cache,'copy_object',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'refs changed'):
                object_cache.prepare(self.store,str(self.source),ident)
        self.assertTrue(list((self.store.state/'git-object-caches').glob('*/intent.json')))
        self.assertFalse(list((self.store.state/'git-object-caches').glob('*/ready.json')))
        self.assertEqual((self.source/'HEAD').read_text(),'ref: refs/heads/unresolved-default\n')

    def test_external_object_dependency_requires_separate_review(self):
        (self.source/'objects/info/alternates').write_text(str(self.drive/'other-objects')+'\n')
        ident=self.capture()
        with self.assertRaisesRegex(ValueError,'alternates'):
            object_cache.prepare(self.store,str(self.source),ident)

    def test_local_bundle_is_independently_restored_without_repairing_source_head(self):
        result=object_cache.prepare(self.store,str(self.source),self.capture());before=(self.source/'HEAD').read_bytes()
        proof=object_cache.benchmark(self.store,result)
        self.assertTrue(proof['restored_and_fsck_verified']);self.assertFalse(proof['published'])
        self.assertEqual(proof['refs'],history_state(self.source)[0]);self.assertEqual((self.source/'HEAD').read_bytes(),before)
        self.assertTrue(Path(proof['bundle']).is_file())

    def test_corrupted_local_object_cache_is_rejected_before_bundle_creation(self):
        result=object_cache.prepare(self.store,str(self.source),self.capture());path=Path(result['mirror'])/result['files'][0]['relative']
        with path.open('ab') as handle:handle.write(b'corrupt local cache')
        with self.assertRaisesRegex(ValueError,'cache bytes differ'):
            object_cache.benchmark(self.store,result)

    def blocked_job_and_proof(self):
        result=object_cache.prepare(self.store,str(self.source),self.capture());proof=object_cache.benchmark(self.store,result)
        ident=enqueue_history(self.store,str(self.source))
        with self.store.db() as db:db.execute("UPDATE jobs SET status='blocked' WHERE id=?",(ident,))
        return ident,proof

    def test_verified_artifact_is_completed_by_daemon_reconciliation(self):
        ident,proof=self.blocked_job_and_proof();before=(self.source/'HEAD').read_bytes()
        destination=Path(object_cache.handoff(self.store,ident,proof))
        self.assertTrue((destination/'history.bundle').exists())
        thread=threading.Thread(target=self.store.worker,args=('transfer',));thread.start()
        try:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                with self.store.db() as db:row=db.execute('SELECT status,message FROM jobs WHERE id=?',(ident,)).fetchone()
                if row['status'] in ('completed','blocked'):break
                time.sleep(.1)
            self.assertEqual(row['status'],'completed',row['message'])
            receipt=catalog(self.store)[0]['receipt'];self.assertEqual(receipt['source'],str(self.source))
            self.assertTrue(receipt['restored_and_fsck_verified']);self.assertEqual(receipt['sha256'],proof['sha256'])
            self.assertEqual((self.source/'HEAD').read_bytes(),before)
        finally:self.store.stop.set();thread.join(5)

    def test_source_ref_changes_reject_handoff_without_publishing(self):
        ident,proof=self.blocked_job_and_proof();oid=next(iter(proof['refs'].values()))
        git(self.source,'update-ref','refs/heads/newer',oid)
        with self.assertRaisesRegex(ValueError,'Source tips changed'):object_cache.handoff(self.store,ident,proof)
        with self.store.db() as db:row=db.execute('SELECT status,payload FROM jobs WHERE id=?',(ident,)).fetchone()
        self.assertEqual(row['status'],'blocked');self.assertFalse(Path(json.loads(row['payload'])['destination']).exists())

    def test_publication_collision_preserves_existing_data_and_restores_job_state(self):
        ident,proof=self.blocked_job_and_proof()
        with self.store.db() as db:payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(ident,)).fetchone()[0])
        destination=Path(payload['destination']);destination.mkdir(parents=True);(destination/'existing.txt').write_text('retain existing destination')
        with self.assertRaises((ValueError,FileNotFoundError)):object_cache.handoff(self.store,ident,proof)
        self.assertEqual((destination/'existing.txt').read_text(),'retain existing destination')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0],'blocked')

    def test_cancelled_job_is_not_resumed_by_artifact_producer(self):
        ident,proof=self.blocked_job_and_proof();self.store.control(ident,'cancel')
        with self.assertRaisesRegex(ValueError,'cancelled'):object_cache.handoff(self.store,ident,proof)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0],'cancelled')

    def test_automation_hold_can_handoff_but_explicit_user_pause_is_retained(self):
        ident,proof=self.blocked_job_and_proof()
        with self.store.db() as db:db.execute("UPDATE jobs SET status='paused',message='Job pause' WHERE id=?",(ident,))
        with self.assertRaisesRegex(ValueError,'user-paused'):object_cache.handoff(self.store,ident,proof)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0],'paused')
            db.execute("UPDATE jobs SET message='Held pending large-repository export optimization after source-side timeout' WHERE id=?",(ident,))
        object_cache.handoff(self.store,ident,proof)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0],'pending')


if __name__=='__main__':unittest.main()
