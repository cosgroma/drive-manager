import json
import unittest
import sqlite3
from unittest.mock import patch
import test_relocations as fixtures
from drive_manager import manifests, relocations

class ArchiveReviewRefreshTests(unittest.TestCase):
    setUp=fixtures.RelocationTests.setUp
    def fresh_manifest(self,source=None):
        ident=manifests.enqueue_manifest(self.store,str(source or self.source))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='completed' WHERE id=?",(ident,))
        return ident
    def candidate(self,ident):
        with self.store.db() as db:
            return dict(db.execute('SELECT * FROM candidates WHERE id=?',(ident,)).fetchone())
    def test_refresh_preserves_decision_reason_destination_and_audit_lineage(self):
        ident=relocations.propose(self.store,self.manifest,reason='Role unknown: preserve unique local changes')
        before=self.candidate(ident)
        (self.source/'untracked.txt').write_text('new unique user work')
        fresh=self.fresh_manifest()
        self.assertEqual(relocations.refresh_review(self.store,ident,fresh,self.manifest),ident)
        after=self.candidate(ident)
        for key in ('id','source','destination','reason','status','confidence','job_id','created'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(after['status'],'review');self.assertIsNone(after['job_id'])
        self.assertEqual(json.loads(after['snapshot'])['manifest'],fresh)
        self.assertFalse(self.source.is_symlink());self.assertFalse(__import__('pathlib').Path(after['destination']).exists())
        with self.store.db() as db:
            events=[r[0] for r in db.execute("SELECT message FROM events WHERE message LIKE 'Archival review baseline refreshed%'")]
        self.assertEqual(len(events),1);self.assertIn(self.manifest,events[0]);self.assertIn(fresh,events[0])
        self.store.approve([ident])
        self.assertEqual(self.candidate(ident)['status'],'queued')
    def test_refresh_rejects_approved_proposal(self):
        ident=relocations.propose(self.store,self.manifest);fresh=self.fresh_manifest();self.store.approve([ident]);before=self.candidate(ident)
        with self.assertRaisesRegex(ValueError,'unapproved'):relocations.refresh_review(self.store,ident,fresh,self.manifest)
        self.assertEqual(self.candidate(ident),before)
    def test_refresh_rejects_wrong_old_manifest(self):
        ident=relocations.propose(self.store,self.manifest);fresh=self.fresh_manifest();before=self.candidate(ident)
        with self.assertRaisesRegex(ValueError,'expected old'):relocations.refresh_review(self.store,ident,fresh,'wrong')
        self.assertEqual(self.candidate(ident),before)
    def test_refresh_rejects_root_drift_after_fresh_inventory(self):
        ident=relocations.propose(self.store,self.manifest);fresh=self.fresh_manifest();(self.source/'new-file').write_text('user change');before=self.candidate(ident)
        with self.assertRaisesRegex(ValueError,'root changed'):relocations.refresh_review(self.store,ident,fresh,self.manifest)
        self.assertEqual(self.candidate(ident),before)
    def test_refresh_rejects_destination_collision(self):
        ident=relocations.propose(self.store,self.manifest);fresh=self.fresh_manifest();before=self.candidate(ident)
        from pathlib import Path
        dest=Path(before['destination']);dest.mkdir(parents=True);(dest/'unique').write_text('existing data')
        with self.assertRaisesRegex(ValueError,'destination'):relocations.refresh_review(self.store,ident,fresh,self.manifest)
        self.assertEqual((dest/'unique').read_text(),'existing data');self.assertEqual(self.candidate(ident),before)
    def test_refresh_does_not_overwrite_concurrent_approval(self):
        ident=relocations.propose(self.store,self.manifest);fresh=self.fresh_manifest();before=self.candidate(ident)
        original=relocations.dependency_gate
        def approve_during_gate(source):
            result=original(source)
            with patch.object(relocations,'dependency_gate',original):
                self.store.approve([ident])
            return result
        with patch.object(relocations,'dependency_gate',side_effect=approve_during_gate):
            with self.assertRaisesRegex(ValueError,'changed during refresh'):relocations.refresh_review(self.store,ident,fresh,self.manifest)
        self.assertEqual(self.candidate(ident)['snapshot'],before['snapshot'])

    def test_refresh_rejects_other_source_manifest(self):
        ident=relocations.propose(self.store,self.manifest);before=self.candidate(ident)
        other=self.drive/'other';other.mkdir();(other/'unique').write_text('different source')
        fresh=self.fresh_manifest(other)
        with self.assertRaisesRegex(ValueError,'same source'):relocations.refresh_review(self.store,ident,fresh,self.manifest)
        self.assertEqual(self.candidate(ident),before)
    def test_refresh_rejects_tampered_manifest(self):
        ident=relocations.propose(self.store,self.manifest);fresh=self.fresh_manifest();before=self.candidate(ident)
        path=self.store.state/'workspace-manifests'/fresh/'manifest.sqlite3'
        with sqlite3.connect(path) as db:db.execute("UPDATE entries SET sha256=? WHERE relative='code.txt'",('0'*64,))
        with self.assertRaisesRegex(ValueError,'verification receipt'):relocations.refresh_review(self.store,ident,fresh,self.manifest)
        self.assertEqual(self.candidate(ident),before)
    def test_refresh_rechecks_dependency_hold(self):
        ident=relocations.propose(self.store,self.manifest);fresh=self.fresh_manifest();before=self.candidate(ident)
        with patch.object(relocations,'dependency_gate',side_effect=ValueError('New dependency hold')):
            with self.assertRaisesRegex(ValueError,'dependency hold'):relocations.refresh_review(self.store,ident,fresh,self.manifest)
        self.assertEqual(self.candidate(ident),before)
    def test_refresh_cannot_reuse_same_manifest(self):
        ident=relocations.propose(self.store,self.manifest);before=self.candidate(ident)
        with self.assertRaisesRegex(ValueError,'new manifest'):relocations.refresh_review(self.store,ident,self.manifest,self.manifest)
        self.assertEqual(self.candidate(ident),before)
