import base64
import hashlib
import unittest
from unittest.mock import patch
from drive_manager import native_files as nf

class NativeStreamCapacity(unittest.TestCase):
    def test_large_inventory_requires_explicit_stream_format(self):
        records={rel:{'native':{'relative':rel,'kind':'dir','streams':[],'sddl':'D:','attributes':16},'signature':{'mode':0o40700},'sha256':None} for rel in ['.',*(f'directory-{i}' for i in range(100000))]}
        with self.assertRaisesRegex(ValueError,'bounded'):nf.validate_records(records)
        with self.assertRaisesRegex(ValueError,'bounded'):nf.validate_records(records,preserve_wsl_file_links=True)
        nf.validate_records(records,preserve_named_streams=True)
        with patch('drive_manager.native_link_records.MAX_RECORDS',100000):
            with self.assertRaisesRegex(ValueError,'bounded'):nf.validate_records(records,preserve_named_streams=True)

    def test_stream_data_counts_toward_serialized_inventory_budget(self):
        data=b'bounded binary data\0\xff'*100
        stream={'name':'PG$Secure','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        item={'source':'fixture','manifest':'a'*32,'receipt':{'sha256':'b'*64},'entries':{'.':{'native':{'kind':'dir','streams':[stream]}}},'preserve_named_streams':True,'named_stream_payloads':[dict(stream,relative='.',data_base64=base64.b64encode(data).decode())]}
        actual=len(nf.encoded_document(item))
        self.assertEqual(nf.document_size_bound(item),actual)
        with patch('drive_manager.native_link_records.MAX_INVENTORY_BYTES',actual):
            self.assertEqual(len(nf.encoded_document(item)),actual)
            self.assertEqual(nf.document_size_bound(item),actual)
        with patch('drive_manager.native_link_records.MAX_INVENTORY_BYTES',actual-1):
            with self.assertRaisesRegex(ValueError,'size budget'):nf.encoded_document(item)
            with self.assertRaisesRegex(ValueError,'size budget'):nf.document_size_bound(item)

if __name__=='__main__':unittest.main()
