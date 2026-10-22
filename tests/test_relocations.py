import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drive_manager.core import Store
from drive_manager.workspaces import git, refs
from drive_manager import manifests,relocations

class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.drive=self.root/'drive';self.drive.mkdir()
        self.source=self.drive/'project';self.source.mkdir()
        git(self.source,'init');git(self.source,'config','user.name','Test');git(self.source,'config','user.email','test@example.invalid')
        (self.source/'code.txt').write_text('versioned code');git(self.source,'add','.');git(self.source,'commit','-m','base')
        (self.source/'untracked.txt').write_text('preserve uncommitted data')
        self.store=Store(self.root/'state',[self.drive],reserve=0)
        ident=manifests.enqueue_manifest(self.store,str(self.source))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,));job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(ident,))
        self.manifest=ident
    def ready(self):
        ident=relocations.propose(self.store,self.manifest)
        self.store.approve([ident])
        with self.store.db() as db:
            candidate=dict(db.execute('SELECT * FROM candidates WHERE id=?',(ident,)).fetchone())
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(candidate['job_id'],))
            job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(candidate['job_id'],)).fetchone())
        return job,candidate
    def test_archive_replay_and_explicit_restore_preserve_original_data_and_git(self):
        before=refs(self.source);job,candidate=self.ready()
        relocations.run(self.store,job,candidate)
        destination=Path(candidate['destination'])
        self.assertTrue(self.source.is_symlink());self.assertTrue(destination.is_dir())
        self.assertEqual((self.source/'untracked.txt').read_text(),'preserve uncommitted data')
        self.assertEqual(refs(self.source),before)
        relocations.run(self.store,job,candidate)
        ident=relocations.enqueue_restore(self.store,job['id'])
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,));restore=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        relocations.run_restore(self.store,restore)
        self.assertFalse(self.source.is_symlink());self.assertFalse(destination.exists())
        self.assertEqual(refs(self.source),before)
        self.assertEqual(relocations.catalog(self.store)[0]['receipt']['phase'],'restored')
    def test_junction_failure_rolls_back_without_deleting_unique_files(self):
        job,candidate=self.ready()
        with patch.object(relocations,'create_junction',side_effect=OSError('link creation failed')):
            with self.assertRaisesRegex(OSError,'link creation failed'):relocations.run(self.store,job,candidate)
        self.assertTrue(self.source.is_dir());self.assertFalse(self.source.is_symlink())
        self.assertEqual((self.source/'untracked.txt').read_text(),'preserve uncommitted data')
        self.assertFalse(Path(candidate['destination']).exists())
    def test_changed_file_blocks_before_any_move(self):
        job,candidate=self.ready();(self.source/'code.txt').write_text('new user edits')
        with self.assertRaisesRegex(ValueError,'differs|changed'):relocations.run(self.store,job,candidate)
        self.assertFalse(self.source.is_symlink());self.assertEqual((self.source/'code.txt').read_text(),'new user edits')
        self.assertFalse(Path(candidate['destination']).exists())
    def test_destination_collision_is_never_overwritten(self):
        job,candidate=self.ready();dest=Path(candidate['destination']);dest.mkdir(parents=True)
        (dest/'existing').write_text('keep this existing destination')
        with self.assertRaisesRegex(ValueError,'exists'):relocations.run(self.store,job,candidate)
        self.assertTrue((self.source/'code.txt').exists());self.assertEqual((dest/'existing').read_text(),'keep this existing destination')
    def test_working_tree_is_not_automatically_authorized(self):
        with self.assertRaisesRegex(ValueError,'Automatic relocation'):
            relocations.propose(self.store,self.manifest,automatic=True)
        with self.store.db() as db:self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE kind='transfer'").fetchone()[0],0)
    def test_relative_remote_is_rejected_even_when_followed_by_absolute_remote(self):
        git(self.source,'config','--add','remote.origin.url','../sibling.git')
        git(self.source,'config','--add','remote.origin.url','https://example.invalid/project.git')
        with self.assertRaisesRegex(ValueError,'Parent-relative remote'):
            relocations.dependency_gate(self.source)

    def test_nested_collection_bare_archive_moves_and_restores_with_refs_intact(self):
        nested=self.drive/'repos/libs/python/modules/history.git';nested.parent.mkdir(parents=True)
        git(self.source,'clone','--bare','--no-local',str(self.source),str(nested))
        git(nested,'config','--remove-section','remote.origin')
        original=refs(nested)
        ident=manifests.enqueue_manifest(self.store,str(nested))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(ident,))
        candidate_id=relocations.propose(self.store,ident,automatic=True)
        with self.store.db() as db:
            candidate=dict(db.execute('SELECT * FROM candidates WHERE id=?',(candidate_id,)).fetchone())
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(candidate['job_id'],))
            job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(candidate['job_id'],)).fetchone())
        relocations.run(self.store,job,candidate)
        self.assertTrue(nested.is_symlink());self.assertEqual(refs(nested),original)
        restore_id=relocations.enqueue_restore(self.store,job['id'])
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(restore_id,))
            restore=dict(db.execute('SELECT * FROM jobs WHERE id=?',(restore_id,)).fetchone())
        relocations.run_restore(self.store,restore)
        self.assertFalse(nested.is_symlink());self.assertEqual(refs(nested),original)

    def test_nested_collection_excludes_backup_and_unrecognized_layouts(self):
        for name in ('backups','archive','snapshots','unknown','apps/deeper'):
            with self.assertRaisesRegex(ValueError,'recognized historical'):
                relocations.automatic_collection(self.drive/'repos'/name/'history.git')

    def test_observed_library_collections_are_bounded_to_one_level(self):
        root=self.drive/'repos'
        for collection in ('libs','utils','opt'):
            with self.subTest(collection=collection):
                parent=root/collection;parent.mkdir(parents=True,exist_ok=True)
                self.assertEqual(relocations.automatic_collection(parent/'history.git'),root)
                with self.assertRaisesRegex(ValueError,'recognized historical'):
                    relocations.automatic_collection(parent/'nested/history.git')
                (parent/'.git').write_text('gitdir: elsewhere')
                with self.assertRaisesRegex(ValueError,'inside another repository'):
                    relocations.automatic_collection(parent/'history.git')
                (parent/'.git').unlink()

    def test_reviewed_deep_library_layouts_check_every_ancestor(self):
        root=self.drive/'repos'
        for layout in ('libs/python','libs/python/modules','libs/sdr'):
            parent=root/layout;parent.mkdir(parents=True,exist_ok=True)
            source=parent/'history.git'
            self.assertEqual(relocations.automatic_collection(source),root)
            ancestor=parent
            while True:
                marker=ancestor/'.git';marker.write_text('gitdir: missing')
                with self.assertRaisesRegex(ValueError,'inside another repository'):
                    relocations.automatic_collection(source)
                marker.unlink()
                (ancestor/'HEAD').write_text('ref: refs/heads/main')
                (ancestor/'objects').mkdir()
                with self.assertRaisesRegex(ValueError,'inside another repository'):
                    relocations.automatic_collection(source)
                (ancestor/'HEAD').unlink();(ancestor/'objects').rmdir()
                if ancestor==root:break
                ancestor=ancestor.parent
        for layout in ('libs/python/unknown','libs/sdr/nested','libs/python/modules/deeper','os/linux','sergeant/docs/unknown'):
            with self.assertRaisesRegex(ValueError,'recognized historical'):
                relocations.automatic_collection(root/layout/'history.git')

    def test_reviewed_documentation_layouts_reject_every_enclosing_git_boundary(self):
        root=self.drive/'repos'
        for layout in ('sergeant/docs','sergeant/docs/presentations','sergeant/docs/systems_engineering','sergeant/docs/systems_engineering/architecture','sergeant/docs/systems_engineering/analysis'):
            parent=root/layout;parent.mkdir(parents=True,exist_ok=True)
            source=parent/'history.git';self.assertEqual(relocations.automatic_collection(source),root)
            ancestor=parent
            while True:
                marker=ancestor/'.git';marker.write_text('gitdir: external')
                with self.assertRaisesRegex(ValueError,'inside another repository'):relocations.automatic_collection(source)
                marker.unlink();(ancestor/'HEAD').write_text('ref: refs/heads/main');(ancestor/'objects').mkdir()
                with self.assertRaisesRegex(ValueError,'inside another repository'):relocations.automatic_collection(source)
                (ancestor/'HEAD').unlink();(ancestor/'objects').rmdir()
                if ancestor==root:break
                ancestor=ancestor.parent
        for layout in ('sergeant','sergeant/docs/unknown','sergeant/docs/presentations/nested','sergeant/docs/systems_engineering/architecture/extra','sergeant/docs/systems_engineering/analysis/extra'):
            with self.assertRaisesRegex(ValueError,'recognized historical'):relocations.automatic_collection(root/layout/'history.git')

    def test_nested_collection_rejects_enclosing_working_and_bare_repositories(self):
        parent=self.drive/'repos/apps';parent.mkdir(parents=True)
        (parent/'.git').write_text('gitdir: elsewhere')
        with self.assertRaisesRegex(ValueError,'inside another repository'):
            relocations.automatic_collection(parent/'history.git')
        (parent/'.git').unlink();(parent.parent/'HEAD').write_text('ref: refs/heads/main')
        (parent.parent/'objects').mkdir()
        with self.assertRaisesRegex(ValueError,'inside another repository'):
            relocations.automatic_collection(parent/'history.git')

    def test_post_move_failure_returns_entire_tree_to_original_path(self):
        job,candidate=self.ready();original=relocations.verify_tree;failed=[False]
        def fail_after(*args,**kwargs):
            if kwargs.get('after_move') and not failed[0]:
                failed[0]=True;raise ValueError('simulated post-move mismatch')
            return original(*args,**kwargs)
        with patch.object(relocations,'verify_tree',side_effect=fail_after):
            with self.assertRaisesRegex(ValueError,'post-move'):relocations.run(self.store,job,candidate)
        self.assertFalse(self.source.is_symlink());self.assertTrue((self.source/'untracked.txt').exists())
        self.assertFalse(Path(candidate['destination']).exists())
