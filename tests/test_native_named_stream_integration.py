import pathlib,json,base64,hashlib,shutil,tempfile,unittest,uuid,tarfile
from drive_manager import manifests,native_files as nf,native_streams
from drive_manager.core import Store
from drive_manager.models import powershell,windows_path

WRITE=r'''
Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;
public static class StreamFixtureWriter {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFile(string p,uint a,uint s,IntPtr sec,uint d,uint f,IntPtr t);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool WriteFile(SafeFileHandle h,byte[] data,uint count,out uint written,IntPtr o);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool FlushFileBuffers(SafeFileHandle h);
 public static void Write(string path,string name,string encoded) {
  using(var h=CreateFile(path+":"+name,0x40000000,7,IntPtr.Zero,2,0x02200000,IntPtr.Zero)) {
   if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   byte[] bytes=Convert.FromBase64String(encoded);uint written;
   if(bytes.Length>0&&(!WriteFile(h,bytes,(uint)bytes.Length,out written,IntPtr.Zero)||written!=bytes.Length))throw new InvalidOperationException("Fixture stream write failed");
   if(!FlushFileBuffers(h))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  }
 }
}
'@
foreach($entry in $x.entries){[StreamFixtureWriter]::Write($entry.path,$entry.name,$entry.data_base64)}
@{ok=$true}|ConvertTo-Json -Compress
'''

class NativeStreamIntegration(unittest.TestCase):
 def test_native_capture_reconciliation_reactivation_and_source_drift(self):
  parent=pathlib.Path('/mnt/h/archive/workspaces/validation-fixtures');fixture=parent/('named-stream-'+uuid.uuid4().hex);fixture.mkdir(parents=True);self.addCleanup(shutil.rmtree,fixture);source=fixture/'source';source.mkdir();(source/'nested').mkdir();(source/'payload').write_bytes(b'unique regular payload')
  streams=[{'relative':'.','name':'root-stream','data':b'root metadata'},{'relative':'payload','name':'PG$Secure','data':b'\0\xff bounded security metadata'},{'relative':'nested','name':'encryptable','data':b''}]
  requests=[{'path':windows_path(source/x['relative']),'name':x['name'],'data_base64':base64.b64encode(x['data']).decode()} for x in streams];self.assertTrue(json.loads(powershell(WRITE,{'entries':requests}))['ok'])
  with tempfile.TemporaryDirectory() as temp:
   store=Store(pathlib.Path(temp)/'state',[pathlib.Path('/mnt/h')],reserve=0);ident=manifests.enqueue_manifest(store,str(source))
   with store.db() as db:
    db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
   manifests.run_manifest(store,job)
   with store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
   with self.assertRaises(ValueError):nf.enqueue(store,ident,str(fixture/'archives'))
   with self.assertRaises(ValueError):nf.enqueue(store,ident,str(fixture/'archives'),preserve_named_streams='yes')
   item=nf.load(store,ident,preserve_named_streams=True);self.assertEqual(item['receipt']['named_streams'],3)
   capture=nf.enqueue(store,ident,str(fixture/'archives'),preserve_named_streams=True);self.assertEqual(capture,nf.enqueue(store,ident,str(fixture/'archives'),preserve_named_streams=True))
   with store.db() as db:
    db.execute("update jobs set status='running' where id=?",(capture,));job=dict(db.execute('select * from jobs where id=?',(capture,)).fetchone())
   nf.run(store,job);result=store.state/'workspace-snapshots'/capture/'result.json';receipt=json.loads(result.read_text());self.assertEqual(receipt['scope'],nf.STREAM_SCOPE);self.assertEqual(receipt['named_stream_payloads'],3);self.assertFalse(receipt['native_stream_activation_verified']);self.assertFalse(receipt['retirement_authorized']);self.assertTrue(receipt['restored_and_verified'])
   result.unlink();nf.run(store,job);self.assertEqual(json.loads(result.read_text()),receipt)
   with store.db() as db:db.execute("update jobs set status='completed' where id=?",(capture,))
   from drive_manager.sources import search
   entry=next(x for x in search(store,query=str(source))['items'] if x['path']==str(source));self.assertTrue(entry['snapshots'][0]['verified']);self.assertIn('named stream bytes',entry['snapshots'][0]['scope'])
   with tarfile.open(pathlib.Path(receipt['destination'])/'native-tree.tar') as archive:document=json.load(archive.extractfile('native-inventory.json'))
   activated=fixture/'activated';activated.mkdir();(activated/'nested').mkdir();(activated/'payload').write_bytes(b'')
   requests=[{'path':windows_path(activated/x['relative']),'name':x['name'],'data_base64':x['data_base64']} for x in document['named_stream_payloads']];self.assertTrue(json.loads(powershell(WRITE,{'entries':requests}))['ok']);self.assertEqual(native_streams.capture(activated,item['entries'],lambda:None),document['named_stream_payloads'])
   powershell(WRITE,{'entries':[{'path':windows_path(source/'payload'),'name':'PG$Secure','data_base64':base64.b64encode(b'changed').decode()}]})
   with self.assertRaisesRegex(ValueError,'changed'):nf.verify_source(item,pathlib.Path(temp)/'native-after-change.jsonl',lambda:None)

if __name__=='__main__':unittest.main(verbosity=2)
