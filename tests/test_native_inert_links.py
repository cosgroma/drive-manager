import base64,copy,hashlib,json,os,pathlib,tarfile,unittest
import test_native_files as base
from drive_manager import manifests,native_files as nf

R=pathlib.Path.home()/'.local/share/drive-manager/workspace-review'
OBS=json.loads((R/'d-wksp-native-link-stream-observation.json').read_text())['records']

class InertLinks(unittest.TestCase):
    def setUp(self):
        base.NativePayloadTests.setUp(self)
        self.item['preserve_native_link_records']=True
    def add_link(self,record,relative):
        p=self.source/relative;p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(record['linux_target'])
        for directory in [p.parent,*p.parent.parents]:
            if directory==self.source.parent:break
            rel=str(directory.relative_to(self.source));sig=manifests.file_signature(directory)
            self.item['entries'][rel]={'signature':sig,'native':{'relative':rel,'kind':'dir','size':0,'mtime_ns':sig['mtime_ns'],'attributes':16,'sddl':'D:','streams':[]},'sha256':None}
        sig=manifests.file_signature(p);streams=copy.deepcopy(record['streams']);raw=next(x for x in streams if x['id']==8)
        self.item['entries'][relative]={'signature':sig,'native':{'relative':relative,'kind':'reparse','attributes':1024,'streams':[],'link_backup_streams':streams},'sha256':raw['metadata_sha256']}
    def roundtrip(self):
        nf.validate_records(self.item['entries'],preserve_native_link_records=True)
        archive=self.base/'payload.tar';nf.write_tar(self.item,archive,lambda:None);nf.audit_tar(self.item,archive,lambda:None)
        restored=self.base/'restore';restored.mkdir()
        with tarfile.open(archive) as tar:
            self.assertFalse(any(m.issym() or m.islnk() for m in tar.getmembers()))
            tar.extractall(restored,filter='data')
        nf.verify_restored(self.item,restored,lambda:None)
        doc=json.loads((restored/'native-inventory.json').read_text());self.assertFalse(doc['links_materialized']);self.assertEqual(doc['scope'],nf.RECORD_SCOPE)
        return archive,restored
    def test_external_target_is_preserved_and_never_materialized(self):
        record=next(x for x in OBS if x['linux_target'].startswith('/'))
        self.add_link(record,'empty/link');archive,restored=self.roundtrip()
        self.assertFalse(os.path.lexists(restored/'tree/empty/link'))
        self.assertEqual(json.loads((restored/'native-inventory.json').read_text())['entries']['empty/link']['native']['link_backup_streams'],record['streams'])
    def test_windows_directory_link_preserved_as_record(self):
        record=next(x for x in OBS if x['relative'].endswith('/snl'))
        (self.source/'rtl').mkdir();sig=manifests.file_signature(self.source/'rtl')
        self.item['entries']['rtl']={'signature':sig,'native':{'relative':'rtl','kind':'dir','size':0,'attributes':16,'sddl':'D:','streams':[]},'sha256':None}
        self.add_link(record,'a/b/c/link');self.roundtrip()
    def test_unknown_stream_and_ea_identity_mismatch_block(self):
        self.add_link(next(x for x in OBS if x['linux_target'].startswith('/')),'empty/link')
        records=copy.deepcopy(self.item['entries']);records['empty/link']['signature']['uid']+=1
        with self.assertRaises(ValueError):nf.validate_records(records,preserve_native_link_records=True)
        records=copy.deepcopy(self.item['entries']);records['empty/link']['native']['link_backup_streams'].append({'id':4})
        with self.assertRaises(ValueError):nf.validate_records(records,preserve_native_link_records=True)
    def test_materialized_link_injection_rejected(self):
        self.add_link(next(x for x in OBS if x['linux_target'].startswith('/')),'empty/link');archive,restored=self.roundtrip()
        (restored/'tree/empty/link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):nf.verify_restored(self.item,restored,lambda:None)
        with tarfile.open(archive,'a') as tar:
            m=tarfile.TarInfo('tree/empty/link');m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd';tar.addfile(m)
        with self.assertRaises(ValueError):nf.audit_tar(self.item,archive,lambda:None)

if __name__=='__main__':unittest.main()
