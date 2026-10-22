import copy,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drive_manager.core import Store
from drive_manager import registry

TOOL=Path.home()/'workspace/scripts/wksp.py'

@unittest.skipUnless(TOOL.exists(),'Workspace-manager CLI is required for metadata integration checks')
class RegistryDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'workspace';self.root.mkdir()
        self.drive=self.base/'drive';self.drive.mkdir();self.file=self.root/'.wksp.json'
        self.targets=[str(self.root/('missing-'+str(i))) for i in range(3)]
        self.data={'schemaVersion':1,'workspaceRoot':str(self.root),'statusValues':['active','dormant'],
                   'projects':[{'id':'parent','name':'Keep curated name','summary':'Keep curated summary','status':'active','kind':'tooling','tags':['keep'],
                     'worktrees':[{'path':str(self.root/'canonical'),'status':'active','role':'primary'}],
                     'relatedRepositories':[{'path':p,'status':'dormant','role':'supporting project','branch':'main','dirtyFiles':2} for p in self.targets]}],
                   'externalProjects':[],'sergeant':{'components':[],'designs':[],'engines':[]}}
        self.file.write_text(json.dumps(self.data,indent=2)+'\n')
        (self.root/'canonical').mkdir();(self.root/'canonical'/'user.txt').write_text('preserve these files')
        self.addCleanup(patch.stopall)
        patch.object(registry,'registry_path',return_value=self.file).start()
        patch.object(registry,'tool_path',return_value=TOOL).start()
        self.store=Store(self.base/'state',[self.drive],reserve=0)
    def propose(self,index):return registry.propose_missing(self.store,self.targets[index],'Unregister missing support checkout; preserve its recovery record')
    def claim(self,ident):
        with self.store.db() as db:
            c=dict(db.execute('SELECT * FROM candidates WHERE id=?',(ident,)).fetchone())
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(c['job_id'],))
            j=dict(db.execute('SELECT * FROM jobs WHERE id=?',(c['job_id'],)).fetchone())
        return j,c
    def test_three_approved_removals_preserve_unrelated_curated_fields_and_replay(self):
        ids=[self.propose(i) for i in range(3)];self.store.approve(ids)
        for ident in ids:
            job,candidate=self.claim(ident);self.store.run_transfer(job);self.store.run_transfer(job)
            record=json.loads((self.store.state/'registry-decisions'/(job['id']+'.json')).read_text())
            self.assertFalse(record['data_recovery_verified']);self.assertEqual(record['files_removed'],0)
        expected=copy.deepcopy(self.data);expected['projects'][0]['relatedRepositories']=[]
        self.assertEqual(json.loads(self.file.read_text()),expected)
        self.assertEqual((self.root/'canonical'/'user.txt').read_text(),'preserve these files')
        self.assertEqual(len(list((self.store.state/'registry-backups').glob('*.json'))),3)
    def test_restored_checkout_blocks_the_whole_approval_batch(self):
        ids=[self.propose(i) for i in range(2)];Path(self.targets[1]).mkdir()
        with self.assertRaisesRegex(ValueError,'now exists'):self.store.approve(ids)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(json.loads(self.file.read_text()),self.data)
    def test_changed_entry_blocks_but_unrelated_edit_is_preserved(self):
        ident=self.propose(0);self.store.approve([ident]);job,candidate=self.claim(ident)
        changed=copy.deepcopy(self.data);changed['projects'][0]['summary']='User changed this while the job waited';self.file.write_text(json.dumps(changed))
        self.store.run_transfer(job)
        actual=json.loads(self.file.read_text());self.assertEqual(actual['projects'][0]['summary'],changed['projects'][0]['summary'])
        ident=self.propose(1);self.store.approve([ident]);job,candidate=self.claim(ident)
        actual['projects'][0]['relatedRepositories'][0]['role']='New user intent';self.file.write_text(json.dumps(actual))
        with self.assertRaisesRegex(ValueError,'changed since review'):self.store.run_transfer(job)
    def test_no_ordinary_transfer_scope_expansion_and_rejection_is_retained(self):
        with self.assertRaisesRegex(ValueError,'outside'):self.store.propose(str(self.file),str(self.drive/'copied.json'))
        ident=self.propose(0);self.store.reject([ident])
        with self.assertRaisesRegex(ValueError,'rejected'):self.propose(0)
