import json,pathlib,subprocess,tempfile,unittest
from unittest.mock import patch
from drive_manager.core import Store
from drive_manager.workspaces import workspace_source

class RegisteredExternalSourceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=pathlib.Path(self.temp.name);self.home=self.base/'home';self.home.mkdir();self.primary=self.home/'workspace';self.primary.mkdir();self.repo=self.home/'.external';self.repo.mkdir();subprocess.run(['git','init',str(self.repo)],check=True,capture_output=True);self.archive=self.base/'archive';self.archive.mkdir();self.store=Store(self.base/'state',[self.archive],reserve=0)
  self.patch=patch('pathlib.Path.home',return_value=self.home);self.patch.start();self.addCleanup(self.patch.stop);self.register()
 def register(self,status='active',project_status='active',path=None):
  (self.primary/'.wksp.json').write_text(json.dumps({'externalProjects':[{'status':project_status,'worktrees':[{'path':str(path or self.repo),'status':status}]}]}))
 def test_exact_active_self_contained_external_checkout_is_read_only_source(self):
  self.assertEqual(workspace_source(self.store,str(self.repo)),(self.repo,self.home))
  with self.assertRaises(ValueError):self.store.safe_path(str(self.repo),True)
 def test_unregistered_home_root_and_descendant_are_rejected(self):
  child=self.repo/'nested';child.mkdir()
  for path in [self.home,child,self.home/'unregistered']:
   with self.assertRaises(ValueError):workspace_source(self.store,str(path))
 def test_dormant_worktree_or_project_cannot_expand_source_scope(self):
  for wt,parent in [('dormant','active'),('active','dormant')]:
   self.register(wt,parent)
   with self.assertRaises(ValueError):workspace_source(self.store,str(self.repo))
 def test_redirected_registered_path_is_rejected(self):
  alias=self.home/'alias';alias.symlink_to(self.repo,target_is_directory=True);self.register(path=alias)
  with self.assertRaisesRegex(ValueError,'redirected'):workspace_source(self.store,str(alias))
 def test_linked_git_storage_and_alternates_are_rejected(self):
  alternates=self.repo/'.git/objects/info/alternates';alternates.write_text('/outside/objects\n')
  with self.assertRaisesRegex(ValueError,'alternates'):workspace_source(self.store,str(self.repo))
  alternates.unlink();gitdir=self.repo/'.git';gitdir.rename(self.repo/'.oldgit');gitdir.write_text('gitdir: /outside/repository\n')
  with self.assertRaisesRegex(ValueError,'coordinated'):workspace_source(self.store,str(self.repo))
 def test_unmodified_configured_home_source_still_works_without_registry(self):
  (self.primary/'.wksp.json').unlink();store=Store(self.base/'other-state',[self.repo],reserve=0)
  self.assertEqual(workspace_source(store,str(self.repo))[0],self.repo)
 def test_symlinked_registry_cannot_authorize_external_reads(self):
  path=self.primary/'.wksp.json';raw=path.read_bytes();path.unlink();target=self.base/'other-registry.json';target.write_bytes(raw);path.symlink_to(target)
  with self.assertRaises(ValueError):workspace_source(self.store,str(self.repo))
 def test_registered_external_tree_is_manifested_and_restored_without_following_links(self):
  from drive_manager import manifests,snapshots
  payload=self.repo/'local-untracked.txt';payload.write_bytes(b'unique local data\0')
  outside=self.home/'outside.txt';outside.write_text('external target stays outside capture');(self.repo/'outside-link').symlink_to(outside)
  ident=manifests.enqueue_manifest(self.store,str(self.repo))
  with self.store.db() as db:
   db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
  manifests.run_manifest(self.store,job)
  with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
  ident=snapshots.enqueue(self.store,[ident],str(self.archive))
  with self.store.db() as db:
   db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
  snapshots.run(self.store,job);receipt=snapshots.catalog(self.store)[0]['receipt'];self.assertTrue(receipt['restored_and_verified']);self.assertFalse(receipt['retirement_authorized']);self.assertEqual(payload.read_bytes(),b'unique local data\0');self.assertEqual(outside.read_text(),'external target stays outside capture')
 def runtime_fixture(self):
  root=self.home/'.pyenv/versions/3.12.13';(root/'bin').mkdir(parents=True);(root/'lib/python3.12').mkdir(parents=True);(root/'bin/python3.12').write_bytes(b'\x7fELFfixture runtime');(root/'lib/python3.12/os.py').write_text('# fixture stdlib\n');env=self.repo/'.venv/bin';env.mkdir(parents=True);(env/'python').symlink_to(root/'bin/python3.12');return root
 def test_only_the_exact_directly_referenced_runtime_prefix_is_readable(self):
  runtime=self.runtime_fixture();self.assertEqual(workspace_source(self.store,str(runtime)),(runtime,self.home))
  for path in [runtime.parent,runtime/'lib',runtime.parent/'3.12.12']:
   with self.assertRaises(ValueError):workspace_source(self.store,str(path))
  with self.assertRaises(ValueError):self.store.safe_path(str(runtime),True)
 def test_runtime_permission_disappears_when_referring_checkout_is_dormant(self):
  runtime=self.runtime_fixture();self.register(status='dormant')
  with self.assertRaises(ValueError):workspace_source(self.store,str(runtime))
 def test_redirected_venv_and_invalid_interpreter_cannot_expand_runtime_scope(self):
  runtime=self.runtime_fixture();(runtime/'bin/python3.12').write_bytes(b'not an ELF interpreter')
  with self.assertRaises(ValueError):workspace_source(self.store,str(runtime))
  (runtime/'bin/python3.12').write_bytes(b'\x7fELFfixture');(self.repo/'.venv').rename(self.repo/'.realvenv');(self.repo/'.venv').symlink_to(self.repo/'.realvenv',target_is_directory=True)
  with self.assertRaises(ValueError):workspace_source(self.store,str(runtime))
 def test_derived_runtime_prefix_can_be_independently_archived_without_git_storage(self):
  from drive_manager import manifests,snapshots
  runtime=self.runtime_fixture();ident=manifests.enqueue_manifest(self.store,str(runtime))
  with self.store.db() as db:
   db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
  manifests.run_manifest(self.store,job)
  with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
  ident=snapshots.enqueue(self.store,[ident],str(self.archive))
  with self.store.db() as db:
   db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
  snapshots.run(self.store,job);receipt=snapshots.catalog(self.store)[0]['receipt'];self.assertTrue(receipt['restored_and_verified']);self.assertFalse(receipt['retirement_authorized']);self.assertEqual((runtime/'bin/python3.12').read_bytes(),b'\x7fELFfixture runtime')
