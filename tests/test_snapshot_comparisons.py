import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

from drive_manager.core import Store
from drive_manager import manifests,snapshot_comparisons
from drive_manager.server import make_server


class SnapshotComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.drive=self.base/'drive';self.drive.mkdir()
        self.left=self.drive/'left';self.left.mkdir();(self.left/'.git/objects').mkdir(parents=True)
        (self.left/'.git/objects/unreachable').write_bytes(b'keep even unnamed Git data')
        (self.left/'.git/config').write_text('local repository configuration')
        (self.left/'local.txt').write_text('uncommitted user data')
        (self.left/'ignored.bin').write_bytes(b'essential ignored data');(self.left/'empty').mkdir()
        (self.left/'relative-link').symlink_to('local.txt')
        self.right=self.drive/'right';shutil.copytree(self.left,self.right,symlinks=True)
        self.store=Store(self.base/'state',[self.drive],reserve=0)

    def capture(self,path,recorded_extra=None,extra_relative='local.txt'):
        ident=manifests.enqueue_manifest(self.store,str(path))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        enumerate_original=manifests.enumerate_tree
        def enumerate_fixture(source,output,check):
            enumerate_original(source,output,check)
            if recorded_extra:
                rows=[json.loads(line) for line in output.read_text().splitlines()]
                for row in rows:
                    if row['relative']==extra_relative:row.update(copy.deepcopy(recorded_extra))
                output.write_text(''.join(manifests.canonical(row)+'\n' for row in rows))
        with patch.object(manifests,'enumerate_tree',side_effect=enumerate_fixture):manifests.run_manifest(self.store,job)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(ident,))
        return ident

    def test_identical_full_tree_includes_git_empty_directories_and_links(self):
        a,b=self.capture(self.left),self.capture(self.right)
        result=snapshot_comparisons.compare(self.store,a,b)
        self.assertEqual(result['counts']['same_payload'],5)  # Four files and a preserved link target.
        self.assertEqual(result['counts']['same_directory'],4)  # Root, .git, objects and empty.
        self.assertTrue(result['all_recorded_payloads_equal']);self.assertTrue(result['compared_metadata_equal'])
        self.assertTrue(result['manifest_digests_verified']);self.assertFalse(result['metadata_equivalence_proven'])
        self.assertFalse(result['retirement_authorized'])

    def test_working_payload_equality_does_not_hide_unique_git_internals(self):
        (self.right/'.git/objects/unreachable').write_bytes(b'different unnamed Git data')
        a,b=self.capture(self.left),self.capture(self.right)
        working=manifests.compare(self.store,a,b)
        self.assertEqual(working['counts']['different_payload'],0)
        full=snapshot_comparisons.compare(self.store,a,b)
        self.assertEqual(full['counts']['different_payload'],1)
        self.assertEqual(full['samples']['different_payload'],['.git/objects/unreachable'])
        self.assertFalse(full['all_recorded_payloads_equal'])

    def test_missing_empty_directory_and_file_type_change_are_detected(self):
        (self.right/'empty').rmdir();(self.right/'ignored.bin').unlink();(self.right/'ignored.bin').mkdir()
        a,b=self.capture(self.left),self.capture(self.right)
        result=snapshot_comparisons.compare(self.store,a,b)
        self.assertEqual(result['counts']['only_left'],1);self.assertEqual(result['samples']['only_left'],['empty'])
        self.assertEqual(result['counts']['different_kind'],1);self.assertFalse(result['membership_equal'])

    def test_named_stream_payload_and_acl_differences_are_not_ignored(self):
        # Simulate native enumeration records; default-stream files remain real.
        stream={'name':'private-notes','size':4,'sha256':hashlib.sha256(b'note').hexdigest()}
        a=self.capture(self.left,{'streams':[stream],'sddl':'owner-and-dacl-A'})
        b=self.capture(self.right,{'streams':[stream],'sddl':'owner-and-dacl-B'})
        acl=snapshot_comparisons.compare(self.store,a,b)
        self.assertTrue(acl['all_recorded_payloads_equal']);self.assertFalse(acl['compared_metadata_equal'])
        self.assertEqual(acl['samples']['different_recorded_metadata'],['local.txt'])
        changed={**stream,'sha256':hashlib.sha256(b'else').hexdigest()}
        c=self.capture(self.right,{'streams':[changed],'sddl':'owner-and-dacl-A'})
        ads=snapshot_comparisons.compare(self.store,a,c)
        self.assertEqual(ads['samples']['different_payload'],['local.txt']);self.assertFalse(ads['all_recorded_payloads_equal'])

    def test_tampered_or_incomplete_manifests_cannot_publish_comparison(self):
        a,b=self.capture(self.left),self.capture(self.right)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='running' WHERE id=?",(b,))
        with self.assertRaisesRegex(ValueError,'completed'):snapshot_comparisons.compare(self.store,a,b)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(b,))
        path=self.store.state/'workspace-manifests'/b/'manifest.sqlite3'
        with sqlite3.connect(path) as db:db.execute("UPDATE entries SET sha256=? WHERE relative='local.txt'",('0'*64,))
        with self.assertRaisesRegex(ValueError,'verification receipt'):snapshot_comparisons.compare(self.store,a,b)
        self.assertEqual(list((self.store.state/'workspace-comparisons').glob('*.json')),[])

    def test_directory_stream_data_present_in_a_manifest_is_compared(self):
        stream={'name':'directory-note','size':4,'sha256':hashlib.sha256(b'note').hexdigest()}
        a=self.capture(self.left,{'streams':[stream]},extra_relative='empty')
        b=self.capture(self.right,{'streams':[{**stream,'sha256':hashlib.sha256(b'else').hexdigest()}]},extra_relative='empty')
        result=snapshot_comparisons.compare(self.store,a,b)
        self.assertEqual(result['samples']['different_payload'],['empty'])
        self.assertFalse(result['all_recorded_payloads_equal'])

    def test_unknown_capture_profile_does_not_imply_complete_stream_coverage(self):
        a,b=self.capture(self.left),self.capture(self.right)
        with self.store.db() as db:
            result=json.loads(db.execute('SELECT result FROM workspace_manifests WHERE job_id=?',(a,)).fetchone()[0])
            result.pop('native_metadata');result.pop('named_stream_scope')
            db.execute('UPDATE workspace_manifests SET result=? WHERE job_id=?',(json.dumps(result),a))
        comparison=snapshot_comparisons.compare(self.store,a,b)
        self.assertTrue(comparison['all_recorded_payloads_equal'])
        self.assertEqual(comparison['named_stream_capture_scopes'][0],'unrecorded')
        self.assertFalse(comparison['directory_stream_capture_complete'])
        self.assertFalse(comparison['metadata_models_compatible']);self.assertFalse(comparison['compared_metadata_equal'])

    def test_samples_are_bounded_and_http_scope_is_explicit(self):
        for i in range(65):(self.left/('unique-'+str(i))).write_text('preserve')
        a,b=self.capture(self.left),self.capture(self.right)
        result=snapshot_comparisons.compare(self.store,a,b)
        self.assertEqual(result['counts']['only_left'],65);self.assertEqual(len(result['samples']['only_left']),50)
        server=make_server(self.store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)
            session=json.load(urllib.request.urlopen(url+'/api/session'))
            req=urllib.request.Request(url+'/api/workspace/compare',data=json.dumps({'left':a,'right':b,'scope':'full'}).encode(),headers={'Content-Type':'application/json','X-Drive-Token':session['token'],'Origin':url})
            response=json.load(urllib.request.urlopen(req));self.assertTrue(response['ok'])
            self.assertEqual(response['id']['comparison_kind'],'full-tree');self.assertFalse(response['id']['retirement_authorized'])
            catalog=json.load(urllib.request.urlopen(url+'/api/workspace/comparisons'))
            self.assertEqual(catalog[0]['scope'],result['scope']);self.assertTrue(catalog[0]['manifest_digests_verified'])
        finally:server.shutdown();server.server_close();thread.join()
