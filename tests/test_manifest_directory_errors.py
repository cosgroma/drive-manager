import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from drive_manager import manifests

class DirectoryErrorTests(unittest.TestCase):
    def test_unreadable_child_has_one_error_record_and_siblings_remain_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'tree';root.mkdir();blocked=root/'database';blocked.mkdir()
            (root/'keep.txt').write_text('unique working file')
            output=Path(tmp)/'manifest.jsonl';original=manifests.os.scandir
            def denied(path):
                if Path(path)==blocked:raise PermissionError(13,'Permission denied',str(path))
                return original(path)
            with patch.object(manifests.os,'scandir',side_effect=denied):
                manifests.posix_tree(root,output,lambda:None)
            rows=[json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(len(rows),len({r['relative'] for r in rows}))
            entry=next(r for r in rows if r['relative']=='database')
            self.assertEqual(entry['kind'],'error');self.assertIn('Permission denied',entry['error'])
            self.assertEqual(next(r for r in rows if r['relative']=='keep.txt')['kind'],'file')
    def test_unreadable_root_emits_single_error_and_never_a_success_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'tree';root.mkdir();output=Path(tmp)/'manifest.jsonl'
            with patch.object(manifests.os,'scandir',side_effect=PermissionError(13,'Permission denied',str(root))):
                manifests.posix_tree(root,output,lambda:None)
            rows=[json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['relative'],'.');self.assertEqual(rows[0]['kind'],'error')
