import hashlib,json,os,pathlib,shutil,subprocess,tempfile,unittest
from unittest.mock import patch
from drive_manager.core import Store
from drive_manager import protected_snapshots as p,snapshots

ACTUAL=pathlib.Path.home()/'.local/share/drive-manager'
class ProtectedSnapshotTests(unittest.TestCase):
 def setUp(self):
  if subprocess.run(['sudo','-n','--','true'],capture_output=True).returncode:self.skipTest('Needs noninteractive privilege')
  self.base=pathlib.Path(tempfile.mkdtemp(prefix='dm-protected-test-'));self.addCleanup(self.cleanup)
  self.source=self.base/'source';self.source.mkdir();(self.source/'global').mkdir();(self.source/'PG_VERSION').write_text('15\n');(self.source/'global/pg_control').write_bytes(b'not a valid control file')
  self.archive=self.base/'archive';self.archive.mkdir();self.store=Store(self.base/'state',[self.source,self.archive],reserve=0)
  self.seal_dir=self.store.state/'validation/protected-cluster';self.seal_dir.mkdir(parents=True);self.seal_path=self.seal_dir/'seal.json'
  (self.store.state/'tools').symlink_to(ACTUAL/'tools',target_is_directory=True)
  (self.store.state/'workspace-review').mkdir();shutil.copyfile(ACTUAL/'workspace-review/pg15-recovery-tools-build.json',self.store.state/'workspace-review/pg15-recovery-tools-build.json')
  self.refresh()
 def cleanup(self):
  assert self.base.parent==pathlib.Path('/tmp') and self.base.name.startswith('dm-protected-test-') and not self.base.is_symlink()
  subprocess.run(['sudo','-n','--','rm','-rf','--',str(self.base)],check=True,timeout=30)
 def refresh(self):
  data=subprocess.check_output(['sudo','-n','--','/usr/bin/python3',str(pathlib.Path(p.__file__).with_name('protected_tree.py')),str(self.source)])
  self.seal_path.write_bytes(data);self.seal_sha=hashlib.sha256(data).hexdigest();return json.loads(data)
 def job(self):
  ident=p.enqueue(self.store,str(self.seal_path),self.seal_sha,str(self.archive))
  with self.store.db() as db:
   db.execute("update jobs set status='running' where id=?",(ident,));return dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
 def test_real_cold_cluster_preserves_protected_directories_and_reconciles(self):
  shutil.rmtree(self.source);build=json.loads((ACTUAL/'workspace-review/pg15-recovery-tools-build.json').read_text());binary=pathlib.Path(build['prefix'])/'bin/initdb'
  subprocess.run([str(binary),'-D',str(self.source),'--auth=trust','--no-locale','-U','fixture_admin'],check=True,capture_output=True,timeout=30)
  subprocess.run(['sudo','-n','--','chown','-R','999:999',str(self.source)],check=True);subprocess.run(['sudo','-n','--','chown','999:0',str(self.source)],check=True)
  before=self.refresh();job=self.job();snapshots.run(self.store,job);snapshots.run(self.store,job)
  receipt=snapshots.catalog(self.store)[0]['receipt'];self.assertTrue(receipt['restored_and_verified']);self.assertTrue(receipt['clean_shutdown_verified']);self.assertFalse(receipt['runtime_activation_verified']);self.assertFalse(receipt['retirement_authorized']);self.assertEqual(receipt['space_reclaimed'],0);self.assertEqual(self.refresh(),before)
  self.assertEqual(snapshots.catalog(self.store)[0]['sources'],[str(self.source)])
  public=pathlib.Path(receipt['destination'])/'receipt.json';v=json.loads(public.read_text());v['source_retained']=False;public.write_text(json.dumps(v))
  with self.assertRaisesRegex(ValueError,'private verification'):snapshots.run(self.store,job)
 def test_changed_source_stops_before_capture(self):
  job=self.job();(self.source/'PG_VERSION').write_text('16\n')
  with self.assertRaisesRegex(ValueError,'changed'):snapshots.run(self.store,job)
  self.assertFalse(pathlib.Path(json.loads(job['payload'])['destination']).exists())
 def test_invalid_clean_shutdown_never_publishes(self):
  job=self.job()
  with self.assertRaisesRegex(ValueError,'control state'):snapshots.run(self.store,job)
  self.assertFalse(pathlib.Path(json.loads(job['payload'])['destination']).exists())
 def test_tampered_seal_rejected_and_deduplicated_requests_share_one_job(self):
  a=p.enqueue(self.store,str(self.seal_path),self.seal_sha,str(self.archive));b=p.enqueue(self.store,str(self.seal_path),self.seal_sha,str(self.archive));self.assertEqual(a,b)
  self.seal_path.write_text('{}')
  with self.assertRaisesRegex(ValueError,'digest'):p.enqueue(self.store,str(self.seal_path),self.seal_sha,str(self.archive))
 def test_recovery_mode_and_traversal_seals_rejected(self):
  for change in ('recovery.signal','../escape'):
   d=json.loads(self.seal_path.read_text());r=dict(d['records'][-1]);r['relative']=change;d['records'].append(r);raw=json.dumps(d).encode();self.seal_path.write_bytes(raw)
   with self.assertRaises(ValueError):p.enqueue(self.store,str(self.seal_path),hashlib.sha256(raw).hexdigest(),str(self.archive))
   self.refresh()
 def test_restore_payload_and_ownership_corruption_rejected(self):
  a=json.loads(self.seal_path.read_text());b=json.loads(self.seal_path.read_text());b['records'][-1]['sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'payload'):p.verify_restored(a,b)
  b=json.loads(self.seal_path.read_text());b['records'][0]['signature']['uid']=12345
  with self.assertRaisesRegex(ValueError,'ownership'):p.verify_restored(a,b)
 def test_source_change_during_tar_is_held(self):
  job=self.job();original=p.command
  def mutate(args,**kwargs):
   if any(str(a).startswith('--pgdata=') for a in args):return 'Database cluster state: shut down\nCatalog version number: 202209061\n'
   result=original(args,**kwargs)
   if '--create' in args:(self.source/'PG_VERSION').write_text('16\n')
   return result
  with patch.object(p,'command',side_effect=mutate):
   with self.assertRaisesRegex(ValueError,'changed during independent'):snapshots.run(self.store,job)
  self.assertFalse(pathlib.Path(json.loads(job['payload'])['destination']).exists())
 def test_extra_archive_member_is_rejected_before_extraction(self):
  import tarfile
  job=self.job();original=p.command
  def inject(args,**kwargs):
   result=original(args,**kwargs)
   if '--create' in args:
    archive=pathlib.Path(next(str(a).split('=',1)[1] for a in args if str(a).startswith('--file=')))
    with tarfile.open(archive,'a') as t:t.addfile(tarfile.TarInfo('../escape'))
   return result
  with patch.object(p,'command',side_effect=inject):
   with self.assertRaisesRegex(ValueError,'Unexpected'):snapshots.run(self.store,job)
  self.assertFalse(pathlib.Path(json.loads(job['payload'])['destination']).exists());self.assertFalse((self.base/'escape').exists())
 def test_unavailable_privilege_cannot_enqueue_protected_job(self):
  with patch.object(p,'command',side_effect=ValueError('No privilege')):
   with self.assertRaisesRegex(ValueError,'No privilege'):self.job()
  with self.store.db() as db:self.assertEqual(db.execute("select count(*) from jobs where kind='workspace_snapshot'").fetchone()[0],0)
 def test_whole_project_with_nested_cluster_preserves_local_files_and_other_protected_data(self):
  (self.source/'PG_VERSION').unlink();shutil.rmtree(self.source/'global')
  cluster=self.source/'deploy/data/postgres';cluster.parent.mkdir(parents=True)
  build=json.loads((ACTUAL/'workspace-review/pg15-recovery-tools-build.json').read_text());binary=pathlib.Path(build['prefix'])/'bin/initdb'
  subprocess.run([str(binary),'-D',str(cluster),'--auth=trust','--no-locale','-U','fixture_admin'],check=True,capture_output=True,timeout=30)
  (self.source/'local-untracked.txt').write_bytes(b'local project edits\0ignored data')
  other=self.source/'protected-object-store';other.mkdir();(other/'object.bin').write_bytes(b'unique object-store payload')
  subprocess.run(['sudo','-n','--','chown','-R','999:999',str(cluster)],check=True);subprocess.run(['sudo','-n','--','chown','-R','0:0',str(other)],check=True)
  subprocess.run(['sudo','-n','--','chmod','700',str(other)],check=True)
  before=self.refresh();ident=p.enqueue(self.store,str(self.seal_path),self.seal_sha,str(self.archive),'deploy/data/postgres')
  with self.store.db() as db:
   db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
  snapshots.run(self.store,job);receipt=snapshots.catalog(self.store)[0]['receipt']
  self.assertEqual(receipt['scope'],'protected-posix-tree-with-postgres15-cold-cluster');self.assertEqual(receipt['cluster_relative'],'deploy/data/postgres');self.assertEqual(self.refresh(),before)
  self.assertTrue(receipt['clean_shutdown_verified']);self.assertFalse(receipt['runtime_activation_verified'])
 def test_cluster_relative_traversal_and_missing_directory_are_rejected(self):
  for relative in ['../outside','/absolute','missing','./noncanonical']:
   with self.assertRaises(ValueError):p.enqueue(self.store,str(self.seal_path),self.seal_sha,str(self.archive),relative)
 def test_nested_database_pid_is_rejected_even_when_project_root_has_no_pid(self):
  cluster=self.source/'deploy/pg';cluster.mkdir(parents=True);(cluster/'global').mkdir();(cluster/'PG_VERSION').write_text('15\n');(cluster/'global/pg_control').write_bytes(b'fake control');(cluster/'postmaster.pid').write_text('12345')
  self.refresh()
  with self.assertRaisesRegex(ValueError,'Active or recovery'):p.enqueue(self.store,str(self.seal_path),self.seal_sha,str(self.archive),'deploy/pg')
