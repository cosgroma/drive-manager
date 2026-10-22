import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from drive_manager.core import Store
from drive_manager.server import make_server

class NativeFileApiTests(unittest.TestCase):
    def test_explicit_native_route_preserves_authentication_and_posix_route(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'state',[root],reserve=0);server=make_server(store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
            try:
                data=json.dumps({'manifest':'completed-native-manifest'}).encode()
                with patch('drive_manager.native_files.enqueue',return_value='native-job') as native:
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(base+'/api/workspace/native-file-snapshot',data=data,headers={'Content-Type':'application/json'}),timeout=3)
                    self.assertEqual(error.exception.code,403);native.assert_not_called()
                    token=json.load(urllib.request.urlopen(base+'/api/session',timeout=3))['token'];headers={'X-Drive-Token':token,'Content-Type':'application/json'}
                    result=json.load(urllib.request.urlopen(urllib.request.Request(base+'/api/workspace/native-file-snapshot',data=data,headers=headers),timeout=3));self.assertEqual(result,{'ok':True,'id':'native-job'});self.assertEqual(native.call_args.args[1:],('completed-native-manifest',None,False,False))
                    linked=json.dumps({'manifest':'completed-linked-manifest','preserve_wsl_file_links':True}).encode()
                    result=json.load(urllib.request.urlopen(urllib.request.Request(base+'/api/workspace/native-file-snapshot',data=linked,headers=headers),timeout=3));self.assertEqual(result['id'],'native-job');self.assertEqual(native.call_args.args[1:],('completed-linked-manifest',None,True,False))
                    inert=json.dumps({'manifest':'inert-manifest','preserve_native_link_records':True}).encode()
                    result=json.load(urllib.request.urlopen(urllib.request.Request(base+'/api/workspace/native-file-snapshot',data=inert,headers=headers),timeout=3));self.assertEqual(result['id'],'native-job');self.assertEqual(native.call_args.args[1:],('inert-manifest',None,False,True))
                with patch('drive_manager.manifests.enqueue_manifest',return_value='linked-manifest') as manifest:
                    data=json.dumps({'source':'/mnt/d/fixture','preserve_wsl_file_links':True}).encode()
                    result=json.load(urllib.request.urlopen(urllib.request.Request(base+'/api/workspace/manifest',data=data,headers=headers),timeout=3));self.assertEqual(result['id'],'linked-manifest');self.assertEqual(manifest.call_args.args[1:],('/mnt/d/fixture',True,False))
                with patch('drive_manager.snapshots.enqueue',return_value='posix-job') as posix,patch('drive_manager.native_files.enqueue') as native:
                    data=json.dumps({'manifests':['posix-manifest']}).encode();result=json.load(urllib.request.urlopen(urllib.request.Request(base+'/api/workspace/snapshot',data=data,headers=headers),timeout=3));self.assertEqual(result['id'],'posix-job');native.assert_not_called();self.assertEqual(posix.call_args.args[1:],(['posix-manifest'],None,False,False))
            finally:server.shutdown();server.server_close();thread.join()
