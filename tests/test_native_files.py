import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
import uuid
from drive_manager import manifests, native_files as nf
from drive_manager.core import Store
from drive_manager.protected_snapshots import protect_staging

class NativePayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'source';self.source.mkdir();(self.source/'empty').mkdir();(self.source/'data').write_bytes(b'essential ignored data')
        records={}
        for p in [self.source,self.source/'empty',self.source/'data']:
            rel=str(p.relative_to(self.source));sig=manifests.file_signature(p);kind='dir' if p.is_dir() else 'file';raw=p.read_bytes() if kind=='file' else b''
            records[rel]={'signature':sig,'native':{'relative':rel,'kind':kind,'size':len(raw),'mtime_ns':sig['mtime_ns'],'attributes':16 if kind=='dir' else 32,'sddl':'O:SYG:SYD:(A;;FA;;;SY)','streams':[],'target':[]},'sha256':hashlib.sha256(raw).hexdigest() if kind=='file' else None}
        self.item={'source':self.source,'manifest':'a'*32,'receipt':{'sha256':'b'*64},'entries':records}
    def archive(self):
        p=self.base/'payload.tar';nf.write_tar(self.item,p,lambda:None);return p
    def test_complete_payload_and_empty_directory_restoration(self):
        nf.validate_records(self.item['entries']);archive=self.archive();nf.audit_tar(self.item,archive,lambda:None);restore=self.base/'restore';restore.mkdir()
        with tarfile.open(archive) as tar:tar.extractall(restore,filter='data')
        nf.verify_restored(self.item,restore,lambda:None)
        doc=json.loads((restore/'native-inventory.json').read_text());self.assertFalse(doc['native_metadata_activation_verified']);self.assertFalse(doc['sacl_captured']);self.assertTrue((restore/'tree/empty').is_dir())
    def test_unsupported_data_never_silently_omitted(self):
        changes=[('kind','reparse'),('streams',[{'name':'extra','size':1,'sha256':'0'*64}]),('sddl',None),('attributes',1024),('attributes',4096),('attributes',16384)]
        for key,value in changes:
            with self.subTest(key=key,value=value):
                records=copy.deepcopy(self.item['entries']);records['data']['native'][key]=value
                with self.assertRaises(ValueError):nf.validate_records(records)
        for count in [0,2]:
            records=copy.deepcopy(self.item['entries']);records['data']['signature']['nlink']=count
            with self.assertRaises(ValueError):nf.validate_records(records)
    def test_traversal_missing_parents_and_missing_digest_are_rejected(self):
        for rel in ['../escape','/absolute','a/../escape','x\\y','C:stream']:
            records=copy.deepcopy(self.item['entries']);entry=records.pop('data');entry['native']['relative']=rel;records[rel]=entry
            with self.subTest(rel=rel),self.assertRaises(ValueError):nf.validate_records(records)
        records=copy.deepcopy(self.item['entries']);records['data']['sha256']=None
        with self.assertRaises(ValueError):nf.validate_records(records)
        records=copy.deepcopy(self.item['entries']);entry=records.pop('data');entry['native']['relative']='missing/data';records['missing/data']=entry
        with self.assertRaises(ValueError):nf.validate_records(records)
    def test_wrong_payload_digest_cannot_be_archived(self):
        self.item['entries']['data']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'payload'):self.archive()

    def test_source_payload_change_and_replacement_are_rejected(self):
        (self.source/'data').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.archive()
    def test_archive_extra_links_and_duplicate_members_are_rejected(self):
        for kind in ['extra','link','duplicate']:
            with self.subTest(kind=kind):
                path=self.base/(kind+'.tar');nf.write_tar(self.item,path,lambda:None)
                with tarfile.open(path,'a') as tar:
                    info=tarfile.TarInfo('tree/data' if kind=='duplicate' else 'unexpected')
                    if kind=='link':info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd';tar.addfile(info)
                    else:info.size=1;tar.addfile(info,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):nf.audit_tar(self.item,path,lambda:None)
    def test_restored_payload_and_metadata_changes_are_detected(self):
        path=self.archive();restore=self.base/'restore';restore.mkdir()
        with tarfile.open(path) as tar:tar.extractall(restore,filter='data')
        (restore/'tree/data').write_bytes(b'broken')
        with self.assertRaises(ValueError):nf.verify_restored(self.item,restore,lambda:None)
        (restore/'tree/data').write_bytes(b'essential ignored data');(restore/'native-inventory.json').write_text('{}')
        with self.assertRaises(ValueError):nf.verify_restored(self.item,restore,lambda:None)

@unittest.skipUnless(os.environ.get('DRIVE_MANAGER_NATIVE_FIXTURE')=='1','Explicit disposable native fixture only')
class NativeWindowsIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.state=Path(self.temp.name)/'state'
        ident=uuid.uuid4().hex;self.d=Path('/mnt/d/archive/workspaces/validation-fixtures')/('native-files-'+ident);self.h=Path('/mnt/h/archive/workspaces/validation-fixtures')/('native-files-'+ident)
        for p in [self.d,self.h]:
            self.assertFalse(p.exists());p.mkdir(parents=True);protect_staging(p);self.addCleanup(shutil.rmtree,p)
        self.source=self.d/'source';self.source.mkdir();(self.source/'.git').mkdir();(self.source/'.git/config').write_bytes(b'repository configuration fixture');(self.source/'empty').mkdir();(self.source/'ignored.bin').write_bytes(b'essential ignored payload')
        self.store=Store(self.state,[Path('/mnt/d'),Path('/mnt/h')],reserve=0)
    def manifest(self):
        ident=manifests.enqueue_manifest(self.store,str(self.source))
        with self.store.db() as db:db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
        manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
        return ident
    def test_native_fixture_full_capture_and_crash_reconciliation(self):
        manifest=self.manifest();ident=nf.enqueue(self.store,manifest,str(self.h/'archives'));self.assertEqual(ident,nf.enqueue(self.store,manifest,str(self.h/'archives')))
        with self.store.db() as db:db.execute("update jobs set status='running' where id=?",(ident,));job=dict(db.execute('select * from jobs where id=?',(ident,)).fetchone())
        __import__('drive_manager.snapshots',fromlist=['run']).run(self.store,job);receipt=json.loads((self.state/'workspace-snapshots'/ident/'result.json').read_text());self.assertTrue(receipt['restored_and_verified']);self.assertFalse(receipt['native_metadata_activation_verified']);self.assertFalse(receipt['retirement_authorized']);self.assertEqual(receipt['files'],2);self.assertEqual((self.source/'ignored.bin').read_bytes(),b'essential ignored payload')
        with self.store.db() as db:db.execute("update jobs set status='completed' where id=?",(ident,))
        from drive_manager.sources import search
        row=next(x for x in search(self.store,query=str(self.source))['items'] if x['path']==str(self.source))
        self.assertTrue(row['snapshots'][0]['verified']);self.assertFalse(row['snapshots'][0]['native_metadata_activation_verified']);self.assertIn('activation not verified',row['snapshots'][0]['scope'])
        with self.store.db() as db:db.execute("update jobs set status='running' where id=?",(ident,))
        (self.state/'workspace-snapshots'/ident/'result.json').unlink();nf.run(self.store,job);self.assertEqual(json.loads((self.state/'workspace-snapshots'/ident/'result.json').read_text())['sha256'],receipt['sha256'])
        published=Path(receipt['destination'])/'receipt.json';wrong=dict(receipt,retirement_authorized=True);published.write_text(json.dumps(wrong))
        with self.assertRaisesRegex(ValueError,'Published'):nf.run(self.store,job)
        published.write_text(json.dumps(dict(receipt,files=999)))
        with self.assertRaisesRegex(ValueError,'Published'):nf.run(self.store,job)

    def test_native_stream_is_refused_instead_of_lost(self):
        from drive_manager.models import powershell,windows_path
        powershell("Set-Content -LiteralPath $x.path -Stream 'retained-test-stream' -Value 'essential ADS fixture' -NoNewline",{'path':windows_path(self.source/'ignored.bin')})
        ident=self.manifest()
        with self.assertRaisesRegex(ValueError,'Named streams'):nf.enqueue(self.store,ident,str(self.h/'archives'))
    def test_manifest_seal_tampering_prevents_capture(self):
        ident=self.manifest();path=self.state/'workspace-manifests'/ident/'manifest.sqlite3'
        import sqlite3
        with sqlite3.connect(path) as db:db.execute("update entries set sha256=? where relative='ignored.bin'",('0'*64,))
        with self.assertRaisesRegex(ValueError,'seal'):nf.enqueue(self.store,ident,str(self.h/'archives'))

if __name__=='__main__':unittest.main()
