import base64
import copy
import json
import pathlib
import unittest
from drive_manager.native_link_records import decode_ea, decode_link, decode_streams

R = pathlib.Path.home()/'.local/share/drive-manager/workspace-review'
RECORDS = json.loads((R/'d-wksp-native-link-stream-observation.json').read_text())['records']

class RecordsTests(unittest.TestCase):
    def test_all_captured_records(self):
        for record in RECORDS:
            with self.subTest(relative=record['relative']):
                result=decode_streams(record['streams'],record['relative'])
                self.assertEqual(result['link']['target'],record['linux_target'])
                self.assertTrue(result['link']['activation_deferred'])
        self.assertEqual(len(RECORDS),16)
        self.assertEqual(sum(decode_streams(r['streams'],r['relative'])['link']['external'] for r in RECORDS),1)
    def test_unknown_and_missing_streams(self):
        for ids in ([2],[8],[2,8,4],[2,2]):
            streams=[dict(RECORDS[0]['streams'][0],id=i) for i in ids]
            with self.assertRaises(ValueError):decode_streams(streams,'a/link')
    def test_stream_tampering(self):
        for key,value in [('name',':other'),('size',0),('attributes',1),('metadata_sha256','0'*64)]:
            x=copy.deepcopy(RECORDS[0]['streams']);x[0][key]=value
            with self.assertRaises(ValueError):decode_streams(x,'a/link')
    def test_ea_corruption(self):
        stream=next(s for s in RECORDS[0]['streams'] if s['id']==2)
        raw=base64.b64decode(stream['metadata_base64'])
        mutations=[raw[:-1],raw+b'\0',b'\0'*4+raw[4:],raw[:8]+b'!'+raw[9:],raw[:4]+b'\1'+raw[5:]]
        for value in mutations:
            with self.assertRaises(ValueError):decode_ea(base64.b64encode(value).decode())
    def test_noncanonical_paths(self):
        encoded=RECORDS[0]['streams'][0]['metadata_base64']
        for path in ('','.', '/a','../a','a/../b','a//b','a\\b','a:b'):
            with self.assertRaises(ValueError):decode_link(encoded,path)
    def test_windows_link_rejects_flags_offsets_and_names(self):
        record=next(r for r in RECORDS if r['relative'].endswith('/snl'))
        raw=base64.b64decode(next(s for s in record['streams'] if s['id']==8)['metadata_base64'])
        mutations=[]
        for offset,value in [(16,0),(8,1),(10,255),(44,0)]:
            bad=bytearray(raw);bad[offset]=value;mutations.append(bytes(bad))
        for value in mutations:
            with self.assertRaises(ValueError):decode_link(base64.b64encode(value).decode(),record['relative'])

    def test_bad_reparse(self):
        raw=base64.b64decode(RECORDS[0]['streams'][0]['metadata_base64'])
        for value in (raw[:-1],raw+b'x',b'\0'*4+raw[4:],raw[:8]+b'\3\0\0\0'+raw[12:]):
            with self.assertRaises(ValueError):decode_link(base64.b64encode(value).decode(),'a/link')

if __name__=='__main__':unittest.main(verbosity=2)
