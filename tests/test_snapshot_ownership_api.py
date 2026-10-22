import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch
from drive_manager.core import Store
from drive_manager.server import make_server

class OwnershipApiTests(unittest.TestCase):
    def test_explicit_flag_reaches_backup_engine_and_default_stays_false(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'state',[root],reserve=0);server=make_server(store,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
            try:
                token=json.load(urllib.request.urlopen(base+'/api/session',timeout=3))['token']
                for value,materialize in [(True,False),(None,None),(False,True),(True,True)]:
                    data={'manifests':['completed-manifest']}
                    if value is not None:data['preserve_mixed_ownership']=value
                    if materialize is not None:data['materialize_external_hardlinks']=materialize
                    request=urllib.request.Request(base+'/api/workspace/snapshot',data=json.dumps(data).encode(),headers={'X-Drive-Token':token,'Content-Type':'application/json'})
                    with patch('drive_manager.snapshots.enqueue',return_value='queued') as enqueue:
                        with urllib.request.urlopen(request,timeout=3) as response:self.assertTrue(json.load(response)['ok'])
                        self.assertEqual(enqueue.call_args.args[1:],(['completed-manifest'],None,value is True,materialize is True))
            finally:server.shutdown();server.server_close();thread.join()
