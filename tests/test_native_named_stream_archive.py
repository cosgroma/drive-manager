import base64,copy,hashlib,io,json,tarfile,unittest
import test_native_files as base
from drive_manager import native_files as nf

class NamedStreamArchive(unittest.TestCase):
 def setUp(self):
  base.NativePayloadTests.setUp(self);self.data=b'\0\xff private native metadata';self.stream={'name':'PG$Secure','size':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest()};self.item['entries']['data']['native']['streams']=[self.stream]
  empty={'name':'root-stream','size':0,'sha256':hashlib.sha256(b'').hexdigest()};self.item['entries']['.']['native']['streams']=[empty]
  self.item.update(preserve_named_streams=True,named_stream_payloads=[dict(empty,relative='.',data_base64=''),dict(self.stream,relative='data',data_base64=base64.b64encode(self.data).decode())])
 def archive(self):
  nf.validate_records(self.item['entries'],preserve_named_streams=True);p=self.base/'payload.tar';nf.write_tar(self.item,p,lambda:None);return p
 def test_full_payload_and_root_stream_data_round_trip(self):
  p=self.archive();nf.audit_tar(self.item,p,lambda:None);dest=self.base/'restore';dest.mkdir()
  with tarfile.open(p) as tar:tar.extractall(dest,filter='data')
  nf.verify_restored(self.item,dest,lambda:None);doc=json.loads((dest/'native-inventory.json').read_text());self.assertEqual(doc['scope'],nf.STREAM_SCOPE);self.assertFalse(doc['native_stream_activation_verified']);self.assertEqual(doc['named_stream_payloads'],self.item['named_stream_payloads']);self.assertEqual((dest/'tree/data').read_bytes(),b'essential ignored data')
 def test_capacity_estimate_accounts_for_encoded_payload_and_metadata(self):
  self.assertEqual(nf.document_size_bound(self.item),len(nf.encoded_document(self.item)))
 def test_default_refusal_and_combined_mode_rejection_remain(self):
  with self.assertRaises(ValueError):nf.validate_records(self.item['entries'])
  with self.assertRaises(ValueError):nf.validate_records(self.item['entries'],preserve_wsl_file_links=True,preserve_named_streams=True)
  with self.assertRaises(ValueError):nf.validate_records(self.item['entries'],preserve_native_link_records=True,preserve_named_streams=True)
 def test_missing_extra_or_corrupt_stream_data_cannot_be_archived(self):
  original=copy.deepcopy(self.item['named_stream_payloads'])
  for values in [[],original+original,original[:1],[original[0],dict(original[1],data_base64='')]]:
   self.item['named_stream_payloads']=values
   with self.assertRaises(ValueError):nf.encoded_document(self.item)
 def test_archive_metadata_tampering_rejected_before_extraction(self):
  original=self.archive();changed=self.base/'changed.tar'
  with tarfile.open(original) as source,tarfile.open(changed,'w') as target:
   for member in source:
    data=source.extractfile(member).read() if member.isfile() else None
    if member.name=='native-inventory.json':
     doc=json.loads(data);doc['named_stream_payloads'][1]['data_base64']='AAAA';data=json.dumps(doc).encode();member.size=len(data)
    target.addfile(member,io.BytesIO(data) if data is not None else None)
  with self.assertRaisesRegex(ValueError,'inventory differs'):nf.audit_tar(self.item,changed,lambda:None)

if __name__=='__main__':unittest.main(verbosity=2)
