import base64,copy,hashlib,unittest
from unittest.mock import patch
from drive_manager import native_streams as ns

class StreamPayloads(unittest.TestCase):
 def setUp(self):
  self.data=b'\0\xff bounded stream data';self.stream={'name':'PG$Secure','size':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest()};self.entries={'file':{'native':{'kind':'file','streams':[self.stream]}}};self.payload=dict(self.stream,relative='file',data_base64=base64.b64encode(self.data).decode())
 def test_exact_payload_and_empty_stream_round_trip(self):
  self.assertEqual(ns.validate_payloads(self.entries,[self.payload]),[self.payload])
  empty={'name':'empty','size':0,'sha256':hashlib.sha256(b'').hexdigest()};entries={'.':{'native':{'kind':'dir','streams':[empty]}}};ns.validate_payloads(entries,[dict(empty,relative='.',data_base64='')])
 def test_payload_corruption_and_descriptor_changes_are_rejected(self):
  for key,value in [('data_base64',base64.b64encode(b'x'*len(self.data)).decode()),('size',0),('sha256','0'*64),('relative','other'),('name','other')]:
   item=dict(self.payload);item[key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):ns.validate_payloads(self.entries,[item])
 def test_missing_extra_duplicate_and_malformed_payloads_rejected(self):
  for payloads in ([],[self.payload,self.payload],[dict(self.payload,extra=True)],None,[dict(self.payload,relative=[])],[dict(self.payload,data_base64='!')]):
   with self.assertRaises(ValueError):ns.validate_payloads(self.entries,payloads)
 def test_invalid_names_paths_hashes_and_sizes_rejected(self):
  for name in ('',':bad','../bad','x\\y','x\0y'):
   entries=copy.deepcopy(self.entries);entries['file']['native']['streams'][0]['name']=name
   with self.assertRaises(ValueError):ns.descriptors(entries)
  for relative in ('../file','/file','a/../file','a//file','a:file',1):
   with self.assertRaises(ValueError):ns.descriptors({relative:self.entries['file']})
  for field,value in [('size',True),('size',-1),('size',ns.MAX_STREAM_BYTES+1),('sha256','bad')]:
   entries=copy.deepcopy(self.entries);entries['file']['native']['streams'][0][field]=value
   with self.assertRaises(ValueError):ns.descriptors(entries)
 def test_ambiguous_names_and_budget_are_rejected(self):
  entries=copy.deepcopy(self.entries);entries['file']['native']['streams'].append(dict(self.stream,name='pg$secure'))
  with self.assertRaises(ValueError):ns.descriptors(entries)
  with patch.object(ns,'MAX_TOTAL_BYTES',1),self.assertRaises(ValueError):ns.descriptors(self.entries)
  with patch.object(ns,'MAX_STREAMS',0),self.assertRaises(ValueError):ns.descriptors(self.entries)

if __name__=='__main__':unittest.main(verbosity=2)
