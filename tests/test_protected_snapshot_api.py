import json,pathlib,tempfile,threading,unittest,urllib.request
from unittest.mock import patch
from drive_manager.core import Store
from drive_manager.server import make_server
class ProtectedApiTests(unittest.TestCase):
 def test_authenticated_request_queues_only_explicit_sealed_source(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=pathlib.Path(temporary);store=Store(root/'state',[root],reserve=0);server=make_server(store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
   try:
    token=json.load(urllib.request.urlopen(base+'/api/session',timeout=3))['token'];body={'seal_path':'/private/seal.json','seal_sha256':'a'*64,'archive_root':'/archive'}
    request=urllib.request.Request(base+'/api/workspace/postgres-snapshot',data=json.dumps(body).encode(),headers={'X-Drive-Token':token,'Content-Type':'application/json'})
    with patch('drive_manager.protected_snapshots.enqueue',return_value='queued') as enqueue:
     with urllib.request.urlopen(request,timeout=3) as response:self.assertTrue(json.load(response)['ok'])
     self.assertEqual(enqueue.call_args.args[1:],('/private/seal.json','a'*64,'/archive','.'))
    body['cluster_relative']='deploy/pg'
    request=urllib.request.Request(base+'/api/workspace/postgres-snapshot',data=json.dumps(body).encode(),headers={'X-Drive-Token':token,'Content-Type':'application/json'})
    with patch('drive_manager.protected_snapshots.enqueue',return_value='queued') as enqueue:
     with urllib.request.urlopen(request,timeout=3) as response:self.assertTrue(json.load(response)['ok'])
     self.assertEqual(enqueue.call_args.args[1:],('/private/seal.json','a'*64,'/archive','deploy/pg'))
   finally:server.shutdown();server.server_close();thread.join()
