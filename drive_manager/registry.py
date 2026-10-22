"""Reviewed metadata-only removal of missing workspace registrations."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid


class MissingRegistration(ValueError):pass


def registry_path():return Path.home()/'workspace/.wksp.json'
def tool_path():return Path.home()/'workspace/scripts/wksp.py'
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))


def read_registry():
    path=registry_path()
    if path.resolve()!=path or not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_nlink!=1:
        raise ValueError('Registry must be the original regular metadata file')
    raw=path.read_bytes();return path,raw,json.loads(raw)


def locate(data,target):
    groups=[('projects',data.get('projects',[])),('externalProjects',data.get('externalProjects',[]))]
    groups += [('sergeant.'+key,data.get('sergeant',{}).get(key,[])) for key in ('components','designs','engines')]
    found=[]
    for group,projects in groups:
        for project in projects:
            for collection in ('worktrees','relatedRepositories','submodules'):
                for index,entry in enumerate(project.get(collection,[])):
                    if entry.get('path')==target:
                        found.append((dict(group=group,parent_id=project['id'],collection=collection,entry=entry),project,index))
    if not found:raise MissingRegistration('Registration is no longer managed; prepare a fresh review')
    if len(found)>1:raise ValueError('Registration is ambiguous; prepare a fresh review')
    return found[0]


def tool_hashes():
    tool=tool_path();files=[tool,tool.parent/'wksp/inventory.py',tool.parent/'wksp/paths.py',tool.parent/'wksp/cli.py']
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def validate(store,candidate):
    path,raw,data=read_registry();target=Path(candidate['source']);snap=json.loads(candidate['snapshot'])
    if data.get('workspaceRoot')!=snap['workspace_root'] or data.get('schemaVersion')!=snap['schema_version']:
        raise ValueError('Registry workspace identity changed since review')
    if candidate['destination']!=str(path) or path.parent not in target.parents or target.resolve(strict=False)!=target:
        raise ValueError('Registration operation is outside the primary workspace metadata scope')
    if os.path.lexists(target):raise ValueError('Checkout now exists; missing-registration approval is stale')
    context,_,_=locate(data,str(target))
    if canonical(context)!=canonical(snap['context']):raise ValueError('Registration changed since review')
    if tool_hashes()!=snap['tool_hashes']:raise ValueError('Registry command implementation changed since review')
    return path,raw,data,context


def propose_missing(store,target,reason):
    path,raw,data=read_registry();context,_,_=locate(data,str(target))
    snapshot={'context':context,'workspace_root':data.get('workspaceRoot'),'schema_version':data.get('schemaVersion'),'tool_hashes':tool_hashes(),'data_recovery_verified':False}
    candidate=dict(source=str(target),destination=str(path),snapshot=json.dumps(snapshot))
    validate(store,candidate)
    with store.db() as db:
        rows=db.execute("SELECT id,status,snapshot FROM candidates WHERE kind='registry_remove' AND source=? ORDER BY created DESC",(str(target),)).fetchall()
        for row in rows:
            if row['status'] in ('review','queued'):return row['id']
            if row['status']=='rejected' and json.loads(row['snapshot'])['context']==context:
                raise ValueError('Previous missing-registration removal was rejected; decision retained')
        ident=uuid.uuid4().hex
        db.execute("INSERT INTO candidates(id,kind,source,destination,snapshot,size,reason,confidence,created,updated) VALUES(?,'registry_remove',?,?,?,?,?,'review',?,?)",
                   (ident,str(target),str(path),json.dumps(snapshot),0,reason,time.time(),time.time()))
    store.event('Missing-registration metadata review prepared; no files or branches will be removed: '+str(target))
    return ident


def run(store,job,candidate):
    receipt_path=store.state/'registry-decisions'/(job['id']+'.json')
    if receipt_path.exists():
        record=json.loads(receipt_path.read_text())
        path,raw,data=read_registry()
        try:locate(data,candidate['source'])
        except MissingRegistration:
            if record['source']!=candidate['source'] or record['registry']!=str(path):raise ValueError('Registry recovery record differs from this job')
            # Only reconcile the metadata outcome; never overwrite newer unrelated edits.
            record['phase']='absent';record['verified_at']=time.time();store.write_receipt(receipt_path,record)
            finish(store,job,candidate);return
    path,raw,data,context=validate(store,candidate)
    expected=copy.deepcopy(data);_,project,index=locate(expected,candidate['source'])
    removed=project[context['collection']].pop(index)
    record=dict(job=job['id'],candidate=candidate['id'],registry=str(path),source=candidate['source'],context=context,
                original_index=index,before_sha256=hashlib.sha256(raw).hexdigest(),phase='prepared',at=time.time(),
                data_recovery_verified=False,files_removed=0,branches_removed=0)
    store.write_receipt(store.state/'registry-backups'/(job['id']+'.json'),{'registry':str(path),'before':data,'sha256':record['before_sha256']})
    store.write_receipt(receipt_path,record)
    store.check(job['id'])
    env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'}
    proc=subprocess.run([sys.executable,str(tool_path()),'remove',candidate['source'],'--inventory',str(path)],capture_output=True,text=True,timeout=60,env=env)
    if proc.returncode:raise ValueError('Supported registry remove command failed; metadata backup retained')
    updated=path.read_bytes()
    if json.loads(updated)!=expected:raise ValueError('Registry differs from the exact reviewed removal; preserve current data and inspect the backup')
    record.update(phase='removed',after_sha256=hashlib.sha256(updated).hexdigest(),verified_at=time.time())
    store.write_receipt(receipt_path,record)
    finish(store,job,candidate)


def finish(store,job,candidate):
    with store.db() as db:db.execute("UPDATE candidates SET status='completed',updated=? WHERE id=?",(time.time(),candidate['id']))
    store.progress(job['id'],0,0,'Missing registration removed; exact recovery metadata retained; no files or branches deleted')
    store.event('User-approved missing-registration removal completed: '+candidate['source'],job['id'])


def catalog(store):
    with store.db() as db:
        rows=db.execute("SELECT c.id,c.source,c.destination,c.reason,c.status,c.job_id,j.status job_status,j.message FROM candidates c LEFT JOIN jobs j ON j.id=c.job_id WHERE c.kind='registry_remove' ORDER BY c.created DESC").fetchall()
    return [dict(r) for r in rows]
