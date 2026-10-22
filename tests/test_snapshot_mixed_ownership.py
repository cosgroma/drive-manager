import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from drive_manager.core import Store
from drive_manager import manifests,snapshots

class MixedOwnershipSnapshotTests(unittest.TestCase):
    def setUp(self):
        probe=subprocess.run(['sudo','-n','--','true'],capture_output=True,timeout=10)
        if probe.returncode:self.skipTest('Noninteractive privilege unavailable')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'source';self.source.mkdir();self.archive=self.base/'archive';self.archive.mkdir()
        self.ordinary=self.source/'ordinary.txt';self.ordinary.write_text('user-owned data')
        self.rootfile=self.source/'root-owned.txt';self.rootfile.write_text('root-owned data')
        os.setxattr(self.rootfile,'user.recovery-test',b'exact metadata')
        os.chmod(self.rootfile,0o644);subprocess.run(['sudo','-n','--','chown','0:0',str(self.rootfile)],check=True,timeout=10)
        self.store=Store(self.base/'state',[self.source,self.archive],reserve=0)
    def capture(self):
        ident=manifests.enqueue_manifest(self.store,str(self.source))
        with self.store.db() as db:
            db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
        return [ident]
    def test_exact_mixed_ownership_backup_and_replay_leave_source_unchanged(self):
        ids=self.capture();before=manifests.file_signature(self.rootfile)
        ident=snapshots.enqueue(self.store,ids,str(self.archive),True)
        with self.store.db() as db:
            db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
        snapshots.run(self.store,job);snapshots.run(self.store,job)
        receipt=snapshots.catalog(self.store)[0]['receipt']
        self.assertTrue(receipt['restored_and_verified']);self.assertTrue(receipt['preserve_mixed_ownership'])
        self.assertEqual(manifests.file_signature(self.rootfile),before)
        self.assertEqual(os.getxattr(self.rootfile,'user.recovery-test'),b'exact metadata')
        self.assertFalse(receipt['retirement_authorized'])
    def test_default_mode_still_rejects_mixed_ownership(self):
        with self.assertRaisesRegex(ValueError,'Mixed ownership'):snapshots.enqueue(self.store,self.capture(),str(self.archive))
    def test_explicit_mode_still_rejects_hardlinks(self):
        os.link(self.ordinary,self.source/'same-inode')
        with self.assertRaisesRegex(ValueError,'hardlinked'):snapshots.enqueue(self.store,self.capture(),str(self.archive),True)
    def test_unavailable_privilege_creates_no_backup_job(self):
        ids=self.capture()
        with patch.object(snapshots,'command',side_effect=ValueError('Privilege unavailable')):
            with self.assertRaisesRegex(ValueError,'Privilege unavailable'):snapshots.enqueue(self.store,ids,str(self.archive),True)
        with self.store.db() as db:self.assertEqual(db.execute("select count(*) from jobs where kind='workspace_snapshot'").fetchone()[0],0)
    def test_mode_requires_boolean(self):
        with self.assertRaisesRegex(ValueError,'boolean'):snapshots.inputs(self.store,[], 'true')
    def test_privileged_executable_metadata_is_held(self):
        subprocess.run(['sudo','-n','--','chmod','4755',str(self.rootfile)],check=True,timeout=10)
        with self.assertRaisesRegex(ValueError,'Privileged executable metadata'):snapshots.enqueue(self.store,self.capture(),str(self.archive),True)
    def test_mixed_owner_directory_is_held(self):
        directory=self.source/'root-directory';directory.mkdir();subprocess.run(['sudo','-n','--','chown','0:0',str(directory)],check=True,timeout=10)
        with self.assertRaisesRegex(ValueError,'directories or links'):snapshots.enqueue(self.store,self.capture(),str(self.archive),True)

    def test_privileged_process_cancellation_leaves_no_process_group(self):
        import time
        from drive_manager.workspaces import command
        original=subprocess.Popen;children=[];began=time.monotonic()
        def launch(*args,**kwargs):
            proc=original(*args,**kwargs);children.append(proc.pid);return proc
        def cancel():
            if time.monotonic()-began>.5:raise RuntimeError('fixture cancellation')
        with patch('drive_manager.workspaces.subprocess.Popen',side_effect=launch):
            with self.assertRaisesRegex(RuntimeError,'fixture cancellation'):
                command(['sudo','-n','--','sleep','30'],check=cancel,timeout=5)
        self.assertTrue(children)
        for pid in children:
            try:os.killpg(pid,0)
            except ProcessLookupError:continue
            except PermissionError:pass
            subprocess.run(['sudo','-n','--','kill','-TERM','--','-'+str(pid)],capture_output=True,timeout=5)
            self.fail('Privileged process group survived cancellation')
