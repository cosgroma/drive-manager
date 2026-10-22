import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

from drive_manager.core import Store
from drive_manager import registry,sources
from drive_manager.server import make_server


class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.drive=self.base/'drive';self.drive.mkdir()
        self.store=Store(self.base/'state',[self.drive],reserve=0)
        self.review=self.store.state/'workspace-review';self.review.mkdir()
        self.primary=str(Path.home()/'workspace/projects/canonical')
        self.metadata=self.base/'registry.json'
        self.metadata.write_text(json.dumps({'workspaceRoot':str(Path.home()/'workspace'),'projects':[{'id':'curated','name':'Curated project','status':'active','worktrees':[{'path':self.primary,'role':'primary checkout','branch':'feature/current'}]}]}))
        self.addCleanup(patch.stopall);patch.object(registry,'registry_path',return_value=self.metadata).start()
        self.old='/mnt/e/repos/old.git';self.dest='/mnt/e/archive/workspaces/e/repos/old.git/tree/version'
        rows=[{'path':self.old,'root':'/mnt/e/repos','bare':True,'head':'f'*40,'refs':['refs/heads/old-feature '+'f'*40],
               'remotes':['remote.origin.url https://user:secret@example.invalid/private'],'changes':None,'status_complete':True,
               'canonical_matches':[{'path':self.primary}]}]
        rows += [{'path':'/mnt/d/wksp/project-'+str(i).zfill(2),'root':'/mnt/d/wksp','bare':False,'refs':[],
                  'changes':None,'status_complete':False} for i in range(26)]
        (self.review/'comparison.json').write_text(json.dumps({'created':'2026-01-01T00:00:00Z','discovery_depth':5,'repositories':rows}))
        (self.review/'additional-discovery.json').write_text(json.dumps({'created':1,'depth':6,'repositories':[{'path':'/mnt/h/wksp/private','root':'/mnt/h/wksp','bare':False}], 'unexpanded_frontiers':['/mnt/h/wksp/deeper']}))

    def job(self,ident,kind,path,status='completed'):
        with self.store.db() as db:db.execute('INSERT INTO jobs(id,kind,path,status,payload) VALUES(?,?,?,?,?)',(ident,kind,path,status,'{}'))

    def evidence(self):
        self.job('history','workspace_history',self.old)
        h={'job':'history','source':self.old,'destination':'/mnt/d/archive/history','restored_and_fsck_verified':True,'refs':{'refs/heads/preserved-only':'a'*40},'sha256':'b'*64}
        with self.store.db() as db:db.execute('INSERT INTO workspace_archives(job_id,source,destination,receipt) VALUES(?,?,?,?)',('history',self.old,h['destination'],json.dumps(h)))
        self.job('archive','transfer',self.old)
        receipt={'job':'archive','candidate':'candidate','source':self.old,'destination':self.dest,'phase':'archived','payloads_verified':True,'native_metadata_verified':True,'legacy_payload_reads_verified':True}
        self.store.write_receipt(self.store.state/'workspace-relocations/archive.json',receipt)
        with self.store.db() as db:db.execute("INSERT INTO candidates(id,kind,source,destination,snapshot,size,reason,confidence,status,job_id) VALUES('candidate','workspace_archive',?,?,'{}',0,'reason','goal','completed','archive')",(self.old,self.dest))
        self.job('manifest','workspace_manifest',self.dest)
        m={'job':'manifest','source':self.dest,'files':5,'sha256':'c'*64,'archive_copy_verified':False}
        with self.store.db() as db:db.execute('INSERT INTO workspace_manifests(job_id,source,result) VALUES(?,?,?)',('manifest',self.dest,json.dumps(m)))
        return receipt

    def test_search_pagination_curated_roles_and_unknown_status_are_read_only(self):
        before=self.metadata.read_bytes()
        first=sources.search(self.store,root='/mnt/d',limit=20);second=sources.search(self.store,root='/mnt/d',offset=20,limit=20)
        self.assertEqual(first['total_matched'],26);self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),6)
        self.assertIsNone(first['items'][0]['discovery'][0]['change_count']);self.assertTrue(first['items'][0]['evidence']['unassessed'])
        self.assertEqual(sources.search(self.store,query='D:\\wksp\\project-03')['total_matched'],1)
        self.assertEqual(sources.search(self.store,query='old-feature')['total_matched'],1)
        primary=sources.search(self.store,query='Curated feature/current')['items'][0]
        self.assertEqual(primary['registrations'][0]['status'],'active');self.assertEqual(primary['registrations'][0]['role'],'primary checkout')
        self.assertNotIn('secret',json.dumps(sources.search(self.store)));self.assertEqual(before,self.metadata.read_bytes())
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_physical_archive_evidence_is_merged_and_restoration_does_not_create_a_copy(self):
        self.evidence();known=sources.search(self.store)['total_known']
        result=sources.search(self.store,query='preserved-only');self.assertEqual(result['total_matched'],1)
        row=result['items'][0];self.assertEqual(row['path'],self.old);self.assertTrue(row['evidence']['archived'])
        self.assertEqual(row['manifests'][0]['input_source'],self.dest);self.assertFalse(row['manifests'][0]['independent_copy_verified'])
        self.assertFalse(row['retirement_authorized']);self.assertTrue(row['evidence']['history']);self.assertTrue(row['evidence']['manifest'])
        receipt=json.loads((self.store.state/'workspace-relocations/archive.json').read_text());receipt['phase']='restored'
        self.store.write_receipt(self.store.state/'workspace-relocations/archive.json',receipt)
        with self.store.db() as db:db.execute("UPDATE candidates SET status='restored' WHERE id='candidate'")
        restored=sources.search(self.store);self.assertEqual(restored['total_known'],known);self.assertEqual(restored['evidence_counts'].get('archived',0),0)

    def test_mismatched_receipts_are_not_verified_and_decisions_refresh_live(self):
        self.evidence()
        with self.store.db() as db:
            h=json.loads(db.execute("SELECT receipt FROM workspace_archives WHERE job_id='history'").fetchone()[0]);h['source']='/mnt/h/unrelated'
            db.execute("UPDATE workspace_archives SET receipt=? WHERE job_id='history'",(json.dumps(h),))
            db.execute("UPDATE candidates SET status='review' WHERE id='candidate'")
        result=sources.search(self.store,coverage='review');self.assertEqual(result['total_matched'],1);self.assertFalse(result['items'][0]['evidence']['history'])
        with self.store.db() as db:db.execute("UPDATE candidates SET status='rejected' WHERE id='candidate'")
        self.assertEqual(sources.search(self.store,coverage='review')['total_matched'],0)

    def test_file_move_review_belongs_to_deepest_known_workspace(self):
        with self.store.db() as db:
            for ident,source in [('ref',self.old+'/refs/heads/develop'),('media','/mnt/e/media/movie.bin')]:
                db.execute("INSERT INTO candidates(id,kind,source,destination,snapshot,reason,status) VALUES(?,'move',?,?,'{}','Preserve invalid ref for review','review')",(ident,source,'/mnt/e/archive/'+ident))
        result=sources.search(self.store,coverage='review')
        self.assertEqual(result['total_matched'],1)
        row=result['items'][0]
        self.assertEqual(row['path'],self.old)
        self.assertEqual(row['reviews'][0]['source'],self.old+'/refs/heads/develop')
        self.assertEqual(row['reviews'][0]['reason'],'Preserve invalid ref for review')

    def test_full_file_backup_evidence_is_searchable_and_bound_to_job_and_sources(self):
        self.job('input','workspace_manifest',self.primary)
        self.job('full','workspace_snapshot',self.primary)
        destination=str(self.drive/'full-file-archive')
        with self.store.db() as db:
            db.execute('INSERT INTO workspace_manifests(job_id,source) VALUES(?,?)',('input',self.primary))
            db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps({'manifests':['input'],'destination':destination}),'full'))
        receipt={'job':'full','sources':[self.primary],'destination':destination,'restored_and_verified':True,'scope':'full-visible-posix-trees'}
        path=self.store.state/'workspace-snapshots/full/result.json';self.store.write_receipt(path,receipt)
        result=sources.search(self.store,query=destination,coverage='snapshot')
        self.assertEqual(result['total_matched'],1);self.assertEqual(result['items'][0]['path'],self.primary)
        self.assertTrue(result['items'][0]['evidence']['snapshot']);self.assertFalse(result['retirement_authorized'])
        receipt['sources']=['/unrelated'];path.write_text(json.dumps(receipt))
        self.assertEqual(sources.search(self.store,coverage='snapshot')['total_matched'],0)

    def test_http_scope_and_pagination_are_bounded(self):
        server=make_server(self.store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/api/workspace/sources?'
            data=json.load(urllib.request.urlopen(url+'root=/mnt/d&limit=1'));self.assertEqual(len(data['items']),1)
            for query in ['root=/etc','coverage=delete','offset=-1','limit=101','limit=nope']:
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+query)
                self.assertEqual(error.exception.code,400)
        finally:server.shutdown();server.server_close();thread.join()
