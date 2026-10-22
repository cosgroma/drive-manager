import unittest
from unittest.mock import patch
from drive_manager import native_files as nf

class NativeRecordCapacity(unittest.TestCase):
    def test_complete_inventory_above_legacy_limit_is_supported_only_explicitly(self):
        records={}
        for rel in ['.',*(f'directory-{i}' for i in range(100000))]:
            records[rel]={'native':{'relative':rel,'kind':'dir','streams':[],'sddl':'D:','attributes':16},'signature':{'mode':0o40700},'sha256':None}
        with self.assertRaisesRegex(ValueError,'bounded'):nf.validate_records(records)
        nf.validate_records(records,preserve_native_link_records=True)
        with patch('drive_manager.native_link_records.MAX_RECORDS',100000):
            with self.assertRaisesRegex(ValueError,'bounded'):nf.validate_records(records,preserve_native_link_records=True)
    def test_serialized_metadata_budget_rejects_oversize_inventory(self):
        item={'source':'fixture','manifest':'a'*32,'receipt':{'sha256':'b'*64},'entries':{'.':{'native':{'kind':'dir'}}},'preserve_native_link_records':True}
        with patch('drive_manager.native_link_records.MAX_INVENTORY_BYTES',128):
            with self.assertRaisesRegex(ValueError,'size budget'):nf.encoded_document(item)

if __name__=='__main__':unittest.main()
