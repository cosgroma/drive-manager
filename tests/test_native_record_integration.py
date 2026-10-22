import json,os,pathlib,shutil,tempfile,unittest,uuid
from drive_manager import manifests,native_files as nf
from drive_manager.core import Store
from drive_manager.models import powershell,windows_path
R=pathlib.Path.home()/'.local/share/drive-manager/workspace-review'
OBS=json.loads((R/'d-wksp-native-link-stream-observation.json').read_text())['records']
FIXTURE_SCRIPT='\nAdd-Type -TypeDefinition @\'\nusing System;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;\npublic static class FixtureLinkEa {\n [StructLayout(LayoutKind.Sequential)] public struct IoStatus {public IntPtr Status;public IntPtr Information;}\n [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFile(string p,uint a,uint s,IntPtr sec,uint d,uint f,IntPtr t);\n [DllImport("kernel32.dll",SetLastError=true)] static extern bool DeviceIoControl(SafeFileHandle h,uint c,byte[] input,int ins,byte[] output,int outs,out int n,IntPtr o);\n [DllImport("ntdll.dll")] static extern uint NtSetEaFile(SafeFileHandle h,out IoStatus status,byte[] data,uint size);\n [DllImport("ntdll.dll")] static extern uint NtQueryEaFile(SafeFileHandle h,out IoStatus status,byte[] data,uint size,[MarshalAs(UnmanagedType.U1)]bool single,IntPtr list,uint listSize,IntPtr index,[MarshalAs(UnmanagedType.U1)]bool restart);\n public static string[] Apply(string path,string encoded,string encodedEa) {\n  using(var h=CreateFile(path,0xc0000000,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {\n   if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());\n   byte[] raw=Convert.FromBase64String(encoded);int n;\n   if(!DeviceIoControl(h,0x900A4,raw,raw.Length,null,0,out n,IntPtr.Zero))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());\n   byte[] ea=Convert.FromBase64String(encodedEa);IoStatus io;uint status=NtSetEaFile(h,out io,ea,(uint)ea.Length);if(status!=0)throw new InvalidOperationException("NtSetEaFile status "+status.ToString("X8"));\n   byte[] actual=new byte[16384];if(!DeviceIoControl(h,0x900A8,null,0,actual,actual.Length,out n,IntPtr.Zero))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());\n   string reparse=Convert.ToBase64String(actual,0,n);byte[] readEa=new byte[65536];status=NtQueryEaFile(h,out io,readEa,(uint)readEa.Length,false,IntPtr.Zero,0,IntPtr.Zero,true);if(status!=0)throw new InvalidOperationException("NtQueryEaFile status "+status.ToString("X8"));\n   return new string[]{reparse,Convert.ToBase64String(readEa,0,checked((int)io.Information.ToInt64()))};\n  }\n }\n}\n\'@\n$results=@();foreach($entry in $x.entries){try{$actual=[FixtureLinkEa]::Apply($entry.path,$entry.reparse,$entry.ea);$results+=@{path=$entry.path;applied=$true;raw_reparse_matches=($actual[0] -ceq $entry.reparse);raw_ea_matches=($actual[1] -ceq $entry.ea);actual_ea_base64=$actual[1]}}catch{$results+=@{path=$entry.path;applied=$false;error=$_.Exception.Message}}};@{results=$results}|ConvertTo-Json -Depth 6 -Compress\n'

class NativeRecordIntegration(unittest.TestCase):
    def test_native_capture_archive_restore_and_receipt_reconciliation(self):
        parent=pathlib.Path('/mnt/h/archive/workspaces/validation-fixtures')
        root=parent/('inert-link-integration-'+uuid.uuid4().hex);root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree,root)
        source=root/'source';source.mkdir();(source/'a/b/c').mkdir(parents=True);(source/'rtl').mkdir()
        (source/'unique-ignored-file').write_bytes(b'ignored content must survive')
        selected=[(next(x for x in OBS if x['linux_target'].startswith('/')),'external'),(next(x for x in OBS if x['relative'].endswith('/snl')),'a/b/c/directory-link')]
        entries=[]
        for record,relative in selected:
            p=source/relative;p.write_bytes(b'')
            entries.append({'path':windows_path(p),'reparse':next(x['metadata_base64'] for x in record['streams'] if x['id']==8),'ea':next(x['metadata_base64'] for x in record['streams'] if x['id']==2)})
        results=json.loads(powershell(FIXTURE_SCRIPT,{'entries':entries}))['results']
        self.assertTrue(all(x['applied'] and x['raw_ea_matches'] and x['raw_reparse_matches'] for x in results))
        with tempfile.TemporaryDirectory() as temp:
            store=Store(pathlib.Path(temp)/'state',[pathlib.Path('/mnt/h')],reserve=0)
            ident=manifests.enqueue_manifest(store,str(source),preserve_native_link_records=True)
            with store.db() as db:
                db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
            manifests.run_manifest(store,job)
            with store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
            item=nf.load(store,ident,preserve_native_link_records=True)
            self.assertEqual(item['receipt']['link_records'],2)
            with self.assertRaises(ValueError):nf.load(store,ident)
            capture=nf.enqueue(store,ident,str(root/'archives'),preserve_native_link_records=True)
            self.assertEqual(capture,nf.enqueue(store,ident,str(root/'archives'),preserve_native_link_records=True))
            with store.db() as db:
                db.execute("update jobs set status='running' where id=?",(capture,));job=dict(db.execute('select * from jobs where id=?',(capture,)).fetchone())
            nf.run(store,job)
            result=store.state/'workspace-snapshots'/capture/'result.json';receipt=json.loads(result.read_text())
            self.assertEqual(receipt['scope'],nf.RECORD_SCOPE);self.assertEqual(receipt['link_records'],2)
            self.assertFalse(receipt['links_materialized']);self.assertTrue(receipt['restored_and_verified']);self.assertFalse(receipt['retirement_authorized'])
            result.unlink();nf.run(store,job);self.assertEqual(json.loads(result.read_text()),receipt)
            with store.db() as db:db.execute("update jobs set status='completed' where id=?",(capture,))
            from drive_manager.sources import search
            entry=next(x for x in search(store,query=str(source))['items'] if x['path']==str(source))
            self.assertTrue(entry['snapshots'][0]['verified']);self.assertIn('inert raw link',entry['snapshots'][0]['scope'])
            self.assertEqual((source/'unique-ignored-file').read_bytes(),b'ignored content must survive')
            self.assertEqual(os.readlink(source/'external'),selected[0][0]['linux_target'])
            with store.db() as db:
                original=db.execute('select result from workspace_manifests where job_id=?',(ident,)).fetchone()[0]
                altered=json.loads(original);altered['link_records']+=1
                db.execute('update workspace_manifests set result=? where job_id=?',(json.dumps(altered),ident))
            with self.assertRaisesRegex(ValueError,'count differs'):nf.load(store,ident,preserve_native_link_records=True)
            with store.db() as db:db.execute('update workspace_manifests set result=? where job_id=?',(original,ident))
            (source/'external').unlink();(source/'external').symlink_to('/missing-different-target')
            with self.assertRaisesRegex(ValueError,'changed'):nf.verify_source(item,pathlib.Path(temp)/'drift.jsonl',lambda:None)


if __name__=='__main__':unittest.main()
