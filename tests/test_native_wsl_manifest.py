import base64
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from drive_manager import manifests
from drive_manager.core import Store
from drive_manager.native_reparse import decode_relative_file_link

class NativeWslManifestTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Path('/mnt/d/archive/workspaces/validation-fixtures')/('wsl-manifest-'+uuid.uuid4().hex)
        self.fixture.mkdir(parents=True);self.addCleanup(shutil.rmtree,self.fixture)
        self.source=self.fixture/'source';self.source.mkdir();(self.source/'sub').mkdir()
        (self.source/'data').write_bytes(b'unique ignored payload')
        self.make_link('../data')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'state',[Path('/mnt/d'),Path('/mnt/h')],reserve=0)
    def make_link(self,target):
        from drive_manager.models import powershell,windows_path
        p=self.source/'sub/link';p.write_bytes(b'')
        data=(2).to_bytes(4,'little')+target.encode();raw=(0xa000001d).to_bytes(4,'little')+len(data).to_bytes(2,'little')+b'\0\0'+data
        powershell(r"""
Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;
public static class FixtureLink {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFile(string p,uint a,uint s,IntPtr sec,uint d,uint f,IntPtr t);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool DeviceIoControl(SafeFileHandle h,uint c,byte[] input,int ins,IntPtr output,int outs,out int n,IntPtr o);
 public static void Apply(string p,string encoded) {
  using(var h=CreateFile(p,0x40000000,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
   if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   byte[] raw=Convert.FromBase64String(encoded);int n;
   if(!DeviceIoControl(h,0x900A4,raw,raw.Length,IntPtr.Zero,0,out n,IntPtr.Zero))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  }
 }
}
'@
[FixtureLink]::Apply($x.path,$x.raw)
""",{'path':windows_path(p),'raw':base64.b64encode(raw).decode()})
        self.assertEqual(os.readlink(p),target)
    def job(self,enabled=False):
        ident=manifests.enqueue_manifest(self.store,str(self.source),enabled)
        with self.store.db() as db:
            db.execute("update jobs set status='running' where id=?",(ident,))
            return dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
    def test_default_remains_refusal(self):
        with self.assertRaisesRegex(ValueError,'reparse'):manifests.run_manifest(self.store,self.job())
        self.assertEqual(os.readlink(self.source/'sub/link'),'../data')
    def test_explicit_mode_seals_raw_record_and_internal_target(self):
        job=self.job(True);manifests.run_manifest(self.store,job)
        receipt=manifests.catalog(self.store)[0]['result']
        self.assertTrue(receipt['preserve_wsl_file_links']);self.assertEqual(receipt['wsl_file_links'],1);self.assertEqual(receipt['files'],1)
        import sqlite3
        with sqlite3.connect(receipt['manifest']) as db:
            native,sig,sha=db.execute("select native,signature,sha256 from entries where relative='sub/link'").fetchone()
        record=decode_relative_file_link(json.loads(native)['reparse_buffer_base64'],'sub/link')
        self.assertEqual(record['raw_sha256'],sha);self.assertEqual(record['resolved_relative'],'data');self.assertIsNotNone(sig)
        self.assertEqual((self.source/'sub/link').read_bytes(),b'unique ignored payload')
    def test_full_native_link_recovery_and_receipt_reconciliation(self):
        from drive_manager import native_files as nf
        job=self.job(True);manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(job['id'],))
        with self.assertRaises(ValueError):nf.enqueue(self.store,job['id'])
        dest=Path('/mnt/h/archive/workspaces/validation-fixtures')/('wsl-recovery-'+uuid.uuid4().hex);dest.mkdir(parents=True);self.addCleanup(shutil.rmtree,dest)
        ident=nf.enqueue(self.store,job['id'],str(dest),True)
        self.assertEqual(ident,nf.enqueue(self.store,job['id'],str(dest),True))
        with self.store.db() as db:
            db.execute("update jobs set status='running' where id=?",(ident,));capture=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
        nf.run(self.store,capture)
        receipt_path=self.store.state/'workspace-snapshots'/ident/'result.json';receipt=json.loads(receipt_path.read_text())
        self.assertTrue(receipt['restored_and_verified']);self.assertEqual(receipt['wsl_file_links'],1);self.assertEqual(receipt['scope'],nf.LINK_SCOPE)
        self.assertFalse(receipt['link_security_metadata_captured']);self.assertFalse(receipt['native_metadata_activation_verified']);self.assertFalse(receipt['retirement_authorized'])
        receipt_path.unlink();nf.run(self.store,capture);self.assertEqual(json.loads(receipt_path.read_text()),receipt)
        with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
        from drive_manager.sources import search
        entry=next(x for x in search(self.store,query=str(self.source))['items'] if x['path']==str(self.source))
        self.assertTrue(entry['snapshots'][0]['verified']);self.assertIn('WSL file links',entry['snapshots'][0]['scope'])
        self.assertEqual(os.readlink(self.source/'sub/link'),'../data')
    def test_additional_native_link_stream_is_not_silently_omitted(self):
        from drive_manager.models import powershell,windows_path
        powershell(r"""
Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;
public static class FixtureLinkStream {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFile(string p,uint a,uint s,IntPtr sec,uint d,uint f,IntPtr t);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool WriteFile(SafeFileHandle h,byte[] data,uint count,out uint written,IntPtr o);
 public static void Write(string p) {
  using(var h=CreateFile(p+":essential-link-stream",0x40000000,7,IntPtr.Zero,2,0x02200000,IntPtr.Zero)) {
   if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   byte[] data=System.Text.Encoding.UTF8.GetBytes("essential extra stream");uint n;
   if(!WriteFile(h,data,(uint)data.Length,out n,IntPtr.Zero)||n!=data.Length)throw new InvalidOperationException("Fixture stream write failed");
  }
 }
}
'@
[FixtureLinkStream]::Write($x.path)
""",{'path':windows_path(self.source/'sub/link')})
        job=self.job(True)
        with self.assertRaisesRegex(ValueError,'inaccessible|preservation review'):manifests.run_manifest(self.store,job)
        self.assertEqual(os.readlink(self.source/'sub/link'),'../data')
    def test_link_outside_source_is_refused(self):
        (self.source/'sub/link').unlink();(self.fixture/'outside').write_bytes(b'external')
        self.make_link('../../outside')
        with self.assertRaisesRegex(ValueError,'escapes'):manifests.run_manifest(self.store,self.job(True))

if __name__=='__main__':unittest.main()
