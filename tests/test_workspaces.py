import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from drive_manager.core import Store, digest
from drive_manager.workspaces import enqueue_history, run_history, git, refs, history_state,catalog, publish_directory


class WorkspaceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.drive = self.root / 'drive'; self.drive.mkdir()
        self.repo = self.drive / 'project'; self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Archive Test')
        git(self.repo, 'config', 'user.email', 'archive@example.invalid')
        (self.repo / 'source.txt').write_text('original')
        (self.repo / '.gitignore').write_text('ignored.bin\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'base')
        git(self.repo, 'branch', 'historical-only')
        git(self.repo, 'tag', '-a', 'v1', '-m', 'annotated tag')
        git(self.repo, 'checkout', '--detach')
        (self.repo / 'source.txt').write_text('newer')
        git(self.repo, 'commit', '-am', 'detached history')
        (self.repo / 'source.txt').write_text('local edits')
        (self.repo / 'untracked.txt').write_text('unique local file')
        (self.repo / 'ignored.bin').write_bytes(b'essential ignored data')
        self.store = Store(self.root / 'state', [self.drive], reserve=0)

    def job(self):
        ident = enqueue_history(self.store, str(self.repo))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (ident,))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())

    def test_snapshot_restores_detached_head_tags_and_keeps_local_files(self):
        before = refs(self.repo)
        job = self.job(); run_history(self.store, job)
        receipt = catalog(self.store)[0]['receipt']
        self.assertEqual(receipt['refs'], before)
        self.assertTrue(receipt['restored_and_fsck_verified'])
        self.assertEqual(receipt['space_reclaimed'], 0)
        self.assertEqual(receipt['scope'], 'git-history-only')
        self.assertEqual(receipt['sha256'], digest(Path(receipt['destination']) / 'history.bundle'))
        self.assertEqual((self.repo / 'source.txt').read_text(), 'local edits')
        self.assertEqual((self.repo / 'untracked.txt').read_text(), 'unique local file')
        self.assertEqual((self.repo / 'ignored.bin').read_bytes(), b'essential ignored data')
        self.assertEqual(refs(self.repo), before)
        # A crash after publication is reconciled without replacing the archive.
        run_history(self.store, job)
        with (Path(receipt['destination']) / 'history.bundle').open('ab') as f: f.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            run_history(self.store, job)

    def test_ref_change_blocks_publication(self):
        from drive_manager import workspaces
        original = workspaces.git
        def mutate(path, *args, **kwargs):
            output = original(path, *args, **kwargs)
            if args[:2] == ('bundle', 'create'):
                original(self.repo, 'branch', 'created-during-snapshot')
            return output
        job = self.job()
        with patch.object(workspaces, 'git', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'refs changed'):
                run_history(self.store, job)
        self.assertFalse(Path(json.loads(job['payload'])['destination']).exists())
        self.assertIsNone(catalog(self.store)[0]['receipt'])
        run_history(self.store, job)
        self.assertIn('refs/heads/created-during-snapshot', catalog(self.store)[0]['receipt']['refs'])

    def test_empty_destination_never_overwritten(self):
        staging = self.drive / 'staging'; staging.mkdir()
        destination = self.drive / 'existing'; destination.mkdir()
        with self.assertRaises(FileExistsError): publish_directory(staging, destination)
        self.assertTrue(staging.exists())

    def test_inherited_repository_path_rejected_and_queue_deduplicated(self):
        nested = self.repo / 'nested'; nested.mkdir()
        with self.assertRaisesRegex(ValueError, 'repository root'):
            enqueue_history(self.store, str(nested))
        a = enqueue_history(self.store, str(self.repo))
        self.assertEqual(a, enqueue_history(self.store, str(self.repo)))

    def test_bare_repository_with_no_branch_head_is_not_silently_archived(self):
        bare = self.drive / 'empty.git'
        git(self.repo, 'init', '--bare', str(bare))
        ident = enqueue_history(self.store, str(bare))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (ident,))
            job = dict(db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())
        with self.assertRaises(ValueError): run_history(self.store, job)
        self.assertIsNone(next(r for r in catalog(self.store) if r['job_id']==ident)['receipt'])

    def unborn_bare(self):
        bare=self.drive/'unborn-default.git';git(self.repo,'clone','--bare','--no-local',str(self.repo),str(bare))
        git(bare,'symbolic-ref','HEAD','refs/heads/unselected-default')
        ident=enqueue_history(self.store,str(bare))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,));job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        return bare,job

    def test_named_history_with_unborn_default_is_restored_without_source_repair(self):
        bare,job=self.unborn_bare();raw=(bare/'HEAD').read_bytes();before,head=history_state(bare)
        self.assertNotIn('HEAD',before);self.assertEqual(head['kind'],'unresolved')
        run_history(self.store,job)
        receipt=next(r['receipt'] for r in catalog(self.store) if r['job_id']==job['id'])
        self.assertEqual(receipt['refs'],before);self.assertEqual(receipt['head_state'],head)
        self.assertTrue(receipt['restored_and_fsck_verified']);self.assertEqual((bare/'HEAD').read_bytes(),raw)
        self.assertEqual(history_state(bare),(before,head))
        self.assertNotIn('refs/heads/unselected-default',receipt['refs'])
        self.assertEqual(list((self.store.state/'workspace-restore-checks').iterdir()),[])

    def test_unborn_head_change_blocks_publication_even_when_named_tips_match(self):
        from drive_manager import workspaces
        bare,job=self.unborn_bare();original=workspaces.git
        def mutate(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            if Path(path)==bare and args[:2]==('bundle','create'):original(bare,'symbolic-ref','HEAD','refs/heads/different-unborn')
            return value
        with patch.object(workspaces,'git',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'refs changed'):run_history(self.store,job)
        self.assertFalse(Path(json.loads(job['payload'])['destination']).exists())

    def test_restore_check_ignores_global_hooks_templates_and_external_object_stores(self):
        template=self.root/'user-template';hooks=template/'hooks';hooks.mkdir(parents=True)
        objects=template/'objects/info';objects.mkdir(parents=True)
        (objects/'alternates').write_text(str(self.repo/'.git/objects')+'\n')
        marker=self.root/'unexpected-hook'
        hook=hooks/'reference-transaction';hook.write_text('#!/bin/sh\ntouch "'+str(marker)+'"\n');hook.chmod(0o755)
        config=self.root/'global.gitconfig';config.write_text('[init]\n templateDir = '+str(template)+'\n[core]\n hooksPath = '+str(hooks)+'\n')
        job=self.job()
        with patch.dict('os.environ',{'GIT_CONFIG_GLOBAL':str(config)}):run_history(self.store,job)
        self.assertFalse(marker.exists());self.assertTrue(catalog(self.store)[0]['receipt']['restored_and_fsck_verified'])

    def test_unborn_head_metadata_is_bound_to_private_intent_on_replay(self):
        bare,job=self.unborn_bare();run_history(self.store,job)
        path=Path(json.loads(job['payload'])['destination'])/'receipt.json';receipt=json.loads(path.read_text())
        receipt['head_state']['symbolic_ref']='refs/heads/unapproved-replacement';path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'private capture intent'):run_history(self.store,job)
        self.assertEqual(history_state(bare)[1]['symbolic_ref'],'refs/heads/unselected-default')

    def test_retry_retains_previous_bundle_and_its_capture_intent(self):
        from drive_manager import workspaces
        bare,job=self.unborn_bare();original=workspaces.git
        def interrupt(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            if Path(path)==bare and args[:2]==('bundle','create'):raise ValueError('simulated interruption after bundle creation')
            return value
        with patch.object(workspaces,'git',side_effect=interrupt):
            with self.assertRaisesRegex(ValueError,'simulated interruption'):run_history(self.store,job)
        destination=Path(json.loads(job['payload'])['destination']);staging=destination.parent/('.pending-'+job['id'])
        before=digest(staging/'history.bundle');run_history(self.store,job)
        attempts=list(destination.parent.glob('.retained-attempt-*'));self.assertEqual(len(attempts),1)
        self.assertEqual(digest(attempts[0]/'history.bundle'),before)
        self.assertEqual(json.loads((attempts[0]/'capture-intent.json').read_text())['head_state']['kind'],'unresolved')

    def test_attached_head_symbolic_target_is_preserved_in_restore_check(self):
        git(self.repo,'checkout','-b','attached-archive-state')
        before=history_state(self.repo);raw=(self.repo/'.git/HEAD').read_bytes()
        job=self.job();run_history(self.store,job);receipt=catalog(self.store)[0]['receipt']
        self.assertEqual(receipt['head_state'],before[1])
        self.assertEqual(receipt['head_state']['symbolic_ref'],'refs/heads/attached-archive-state')
        self.assertEqual((self.repo/'.git/HEAD').read_bytes(),raw)
        self.assertEqual((self.repo/'source.txt').read_text(),'local edits')

    def test_public_bundle_and_checksum_cannot_override_private_verified_digest(self):
        bare,job=self.unborn_bare();run_history(self.store,job)
        folder=Path(json.loads(job['payload'])['destination']);bundle=folder/'history.bundle'
        with bundle.open('ab') as handle:handle.write(b'changed public archive')
        path=folder/'receipt.json';receipt=json.loads(path.read_text());receipt['sha256']=digest(bundle);path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'private verified digest'):run_history(self.store,job)

    def test_readable_refs_are_preserved_while_broken_empty_ref_stays_unchanged(self):
        bare,job=self.unborn_bare();broken=bare/'refs/heads/develop';broken.parent.mkdir(parents=True,exist_ok=True);broken.write_bytes(b'')
        run_history(self.store,job);receipt=next(r['receipt'] for r in catalog(self.store) if r['job_id']==job['id'])
        self.assertTrue(receipt['source_ref_warnings']);self.assertIn('develop',' '.join(receipt['source_ref_warnings']))
        self.assertTrue(receipt['restored_and_fsck_verified']);self.assertNotIn('refs/heads/develop',receipt['refs'])
        self.assertEqual(broken.read_bytes(),b'');self.assertEqual(receipt['head_state']['symbolic_ref'],'refs/heads/unselected-default')

    def test_empty_default_ref_is_recorded_without_choosing_a_tip(self):
        bare,job=self.unborn_bare();broken=bare/'refs/heads/unselected-default'
        broken.parent.mkdir(parents=True,exist_ok=True);broken.write_bytes(b'')
        before=(bare/'HEAD').read_bytes();run_history(self.store,job)
        receipt=next(r['receipt'] for r in catalog(self.store) if r['job_id']==job['id'])
        self.assertEqual(receipt['head_state'],{'kind':'unresolved','symbolic_ref':'refs/heads/unselected-default'})
        self.assertTrue(receipt['source_ref_warnings']);self.assertTrue(receipt['restored_and_fsck_verified'])
        self.assertEqual(broken.read_bytes(),b'');self.assertEqual((bare/'HEAD').read_bytes(),before)
