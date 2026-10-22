import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import unittest
import test_native_files as base_tests
from drive_manager import manifests,native_files as nf

class NativeWslArchiveTests(unittest.TestCase):
    def setUp(self):
        base_tests.NativePayloadTests.setUp(self)
        target='../data';p=self.source/'empty/link';p.symlink_to(target)
        data=(2).to_bytes(4,'little')+target.encode();raw=(0xa000001d).to_bytes(4,'little')+len(data).to_bytes(2,'little')+b'\0\0'+data
        self.item['entries']['empty']['signature']=manifests.file_signature(self.source/'empty')
        self.item['entries']['empty/link']={'signature':manifests.file_signature(p),'native':{'relative':'empty/link','kind':'reparse','size':0,'attributes':1056,'sddl':None,'streams':[],'target':[],'mtime_ns':p.lstat().st_mtime_ns,'reparse_additional_streams_absent':True,'reparse_buffer_base64':base64.b64encode(raw).decode()},'sha256':hashlib.sha256(raw).hexdigest()}
        self.item['preserve_wsl_file_links']=True
    def archive(self):
        nf.validate_records(self.item['entries'],True);p=self.base/'payload.tar';nf.write_tar(self.item,p,lambda:None);return p
    def restore(self,p):
        dest=self.base/'restore';dest.mkdir()
        with tarfile.open(p) as t:t.extractall(dest,filter='data')
        return dest
    def test_link_and_raw_record_round_trip(self):
        p=self.archive();nf.audit_tar(self.item,p,lambda:None);dest=self.restore(p);nf.verify_restored(self.item,dest,lambda:None)
        self.assertEqual(os.readlink(dest/'tree/empty/link'),'../data')
        self.assertEqual((dest/'tree/empty/link').read_bytes(),b'essential ignored data')
        doc=json.loads((dest/'native-inventory.json').read_text());self.assertEqual(doc['scope'],nf.LINK_SCOPE)
        self.assertEqual(doc['entries']['empty/link']['native']['reparse_buffer_base64'],self.item['entries']['empty/link']['native']['reparse_buffer_base64'])
    def test_default_still_refuses_links_and_chains_are_refused(self):
        with self.assertRaises(ValueError):nf.validate_records(self.item['entries'])
        records=copy.deepcopy(self.item['entries']);records['data']['native']['kind']='reparse'
        with self.assertRaises(ValueError):nf.validate_records(records,True)
    def test_source_target_change_blocks_capture(self):
        p=self.source/'empty/link';p.unlink();p.symlink_to('../missing')
        with self.assertRaises(ValueError):self.archive()
    def test_wrong_restored_target_is_rejected(self):
        dest=self.restore(self.archive());p=dest/'tree/empty/link';p.unlink();p.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):nf.verify_restored(self.item,dest,lambda:None)
    def test_archive_link_tampering_is_rejected_before_extraction(self):
        source=self.archive();changed=self.base/'changed.tar'
        with tarfile.open(source) as inp,tarfile.open(changed,'w') as out:
            for member in inp:
                if member.issym():member.linkname='/etc/passwd'
                out.addfile(member,inp.extractfile(member) if member.isfile() else None)
        with self.assertRaisesRegex(ValueError,'link differs'):nf.audit_tar(self.item,changed,lambda:None)
    def test_raw_record_digest_tampering_is_rejected(self):
        self.item['entries']['empty/link']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'raw digest'):nf.validate_records(self.item['entries'],True)

if __name__=='__main__':unittest.main()
