"""Verified local Git object mirrors for export performance experiments.

These caches preserve default object bytes and readable tips, not a full archive.
They never alter a source repository or authorize source retirement.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time
import uuid

from . import manifests
from .relocations import dependency_gate, load_manifest
from .workspaces import command, git, history_state, workspace_source


def object_members(source, expected, check):
    """Check exact membership and identities without following source links."""
    seen=set();todo=[source/'objects']
    while todo:
        check();path=todo.pop();relative=str(path.relative_to(source))
        if relative not in expected or manifests.file_signature(path)!=expected[relative]['signature']:
            raise ValueError('Object-store identity or membership changed: '+relative)
        kind=expected[relative]['kind'];seen.add(relative)
        if kind=='dir':todo.extend(path/e.name for e in os.scandir(path))
        elif kind!='file':raise ValueError('Object-store links and special files need separate review')
    if seen!=set(expected):raise ValueError('Object-store members are missing')


def copy_object(source, destination, entry, check):
    if manifests.file_signature(source)!=entry['signature']:
        raise ValueError('Object file changed before copy')
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    sha=hashlib.sha256()
    with os.fdopen(fd,'rb') as original, destination.open('xb') as target:
        while True:
            check();block=original.read(1024*1024)
            if not block:break
            target.write(block);sha.update(block)
        target.flush();os.fsync(target.fileno())
    if sha.hexdigest()!=entry['sha256'] or manifests.file_signature(source)!=entry['signature']:
        raise ValueError('Object file identity or copied payload differs from manifest')
    signature=manifests.file_signature(destination)
    if manifests.checked_hash(destination,signature,check)!=entry['sha256']:
        raise ValueError('Local object copy failed independent SHA-256 verification')


def prepare(store, source, manifest, check=lambda:None, progress=lambda message:None):
    source,_=workspace_source(store,source)
    result,database=load_manifest(store,manifest)
    if result['source']!=str(source):raise ValueError('Object-cache manifest belongs to another source')
    if not dependency_gate(source)['bare']:raise ValueError('Object staging currently requires a self-contained bare repository')
    before_warnings=[];before,head=history_state(source,check,warning_sink=before_warnings)
    object_format=git(source,'rev-parse','--show-object-format',check=check).strip()
    expected={}
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
        for relative,raw,signature,sha in db.execute("SELECT relative,native,signature,sha256 FROM entries WHERE relative='objects' OR relative LIKE 'objects/%'"):
            native=json.loads(raw)
            if (relative in ('objects/info/alternates','objects/info/http-alternates') or relative.endswith('.promisor')):
                raise ValueError('External or partial object stores require a separate preservation plan')
            if native['kind'] not in ('file','dir') or not signature:
                raise ValueError('Unsupported object-store entry')
            if native['kind']=='file' and not sha:raise ValueError('Object file is not hashed in completed manifest')
            expected[relative]=dict(kind=native['kind'],signature=json.loads(signature),sha256=sha)
    object_members(source,expected,check)
    amount=sum(e['signature']['size'] for e in expected.values() if e['kind']=='file')
    parent=store.state/'git-object-caches';parent.mkdir(mode=0o700,exist_ok=True)
    if shutil.disk_usage(parent).free<int(store.setting('reserve'))+amount+256*1024**2:
        raise ValueError('Local object cache would cross the storage reserve')
    root=parent/uuid.uuid4().hex;root.mkdir(mode=0o700)
    mirror=root/'mirror.git';template=root/'empty-template';template.mkdir()
    record=dict(source=str(source),manifest=manifest,manifest_sha256=result['sha256'],cache=str(root),
                mirror=str(mirror),refs=before,head_state=head,source_ref_warnings=before_warnings,
                object_format=object_format,scope='git-object-cache-only',source_retained=True,
                retirement_authorized=False,bytes=amount,created_at=time.time())
    store.write_receipt(root/'intent.json',record)
    command(['git','init','--bare','--template='+str(template),'--object-format='+object_format,str(mirror)],check=check,isolated=True)
    last_capacity=[0.0]
    def guarded_check():
        check()
        if time.monotonic()-last_capacity[0]>5:
            last_capacity[0]=time.monotonic()
            if shutil.disk_usage(parent).free<int(store.setting('reserve'))+64*1024**2:
                raise ValueError('Object-cache capacity reserve reached; partial cache retained')
    copied=[];started=time.monotonic()
    for relative,entry in sorted(expected.items()):
        guarded_check();destination=mirror/relative
        if entry['kind']=='dir':destination.mkdir(parents=True,exist_ok=True);continue
        progress('Copying and independently hashing '+relative)
        copy_object(source/relative,destination,entry,guarded_check)
        copied.append(dict(relative=relative,bytes=entry['signature']['size'],sha256=entry['sha256']))
        store.write_receipt(root/'progress.json',dict(files=copied,source=str(source),complete=False))
    object_members(source,expected,check)
    warnings=[]
    if history_state(source,check,warning_sink=warnings)!=(before,head) or warnings!=before_warnings:
        raise ValueError('Source refs changed during object staging; partial mirror retained')
    updates=''.join('update '+name+' '+oid+'\n' for name,oid in before.items() if name!='HEAD')
    git(mirror,'update-ref','--no-deref','--stdin',input_text=updates,check=check,isolated=True)
    if head['symbolic_ref']:git(mirror,'symbolic-ref','HEAD',head['symbolic_ref'],check=check,isolated=True)
    else:git(mirror,'update-ref','--no-deref','HEAD',before['HEAD'],check=check,isolated=True)
    if history_state(mirror,check,isolated=True)!=(before,head):raise ValueError('Staged readable tips or HEAD semantics differ')
    record.update(files=copied,copy_and_hash_seconds=time.monotonic()-started,verified_at=time.time(),
                  limitations=['Default Git object bytes and readable tips only; raw ref/config metadata and NTFS streams are not copied.',
                               'A local object cache is not a published or recovery-verified history safeguard.'])
    store.write_receipt(root/'ready.json',record)
    progress('Local object bytes and readable tips verified; independent history export still required')
    return record


def benchmark(store, record, check=lambda:None, progress=lambda message:None):
    """Produce and independently restore a bundle; leave publication to a reviewable handoff."""
    from .core import digest
    import tempfile
    source,_=workspace_source(store,record['source'])
    root=Path(record['cache']);mirror=Path(record['mirror'])
    if (root.parent!=store.state/'git-object-caches' or root.resolve()!=root or mirror!=root/'mirror.git'
            or mirror.resolve()!=mirror or json.loads((root/'ready.json').read_text())!=record):
        raise ValueError('Object-cache provenance or private location changed')
    result,database=load_manifest(store,record['manifest'])
    if result['source']!=str(source) or result['sha256']!=record['manifest_sha256']:
        raise ValueError('Object-cache input seal changed')
    expected={}
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
        for relative,raw,signature,sha in db.execute("SELECT relative,native,signature,sha256 FROM entries WHERE relative='objects' OR relative LIKE 'objects/%'"):
            expected[relative]=dict(kind=json.loads(raw)['kind'],signature=json.loads(signature),sha256=sha)
    copied={f['relative']:f for f in record['files']}
    files={rel:e for rel,e in expected.items() if e['kind']=='file'}
    if set(copied)!=set(files):raise ValueError('Object-cache file membership changed')
    for relative,entry in files.items():
        path=mirror/relative
        if (copied[relative]['sha256']!=entry['sha256'] or copied[relative]['bytes']!=entry['signature']['size']
                or path.is_symlink() or digest(path,check)!=entry['sha256']):
            raise ValueError('Object-cache bytes differ from sealed source objects')
    def stable():
        object_members(source,expected,check)
        warnings=[]
        if (history_state(source,check,warning_sink=warnings)!=(record['refs'],record['head_state'])
                or warnings!=record['source_ref_warnings']
                or history_state(mirror,check,isolated=True)!=(record['refs'],record['head_state'])):
            raise ValueError('Source or mirror tips changed before history verification')
    stable()
    output=root/('benchmark-'+uuid.uuid4().hex);output.mkdir()
    bundle=output/'history.bundle';began=time.monotonic()
    progress('Creating history bundle from the verified local object mirror')
    git(mirror,'bundle','create',str(bundle),'--stdin',input_text='\n'.join(record['refs'])+'\n',check=check,isolated=True)
    bundle_seconds=time.monotonic()-began
    tips={}
    for line in git(mirror,'bundle','list-heads',str(bundle),check=check,isolated=True).splitlines():
        oid,name=line.split(' ',1);tips[name]=oid
    if tips!=record['refs']:raise ValueError('Local bundle did not preserve the exact recorded tips')
    parent=store.state/'workspace-restore-checks';parent.mkdir(exist_ok=True)
    if shutil.disk_usage(parent).free<int(store.setting('reserve'))+2*bundle.stat().st_size+256*1024**2:
        raise ValueError('Independent bundle restoration needs more local capacity')
    began=time.monotonic();progress('Independently restoring and checking the locally generated history bundle')
    with tempfile.TemporaryDirectory(prefix='object-cache-',dir=parent) as temporary:
        base=Path(temporary);restore=base/'restore.git';template=base/'empty-template';template.mkdir()
        command(['git','init','--bare','--template='+str(template),'--object-format='+record['object_format'],str(restore)],check=check,isolated=True)
        git(restore,'bundle','verify',str(bundle),check=check,isolated=True)
        git(restore,'bundle','unbundle',str(bundle),check=check,isolated=True)
        updates=''.join('update '+name+' '+oid+'\n' for name,oid in tips.items() if name!='HEAD')
        git(restore,'update-ref','--no-deref','--stdin',input_text=updates,check=check,isolated=True)
        if record['head_state']['symbolic_ref']:git(restore,'symbolic-ref','HEAD',record['head_state']['symbolic_ref'],check=check,isolated=True)
        else:git(restore,'update-ref','--no-deref','HEAD',tips['HEAD'],check=check,isolated=True)
        git(restore,'fsck','--full','--no-reflogs',check=check,isolated=True)
        if history_state(restore,check,isolated=True)!=(record['refs'],record['head_state']):
            raise ValueError('Independent restoration changed readable tips or HEAD semantics')
    restore_seconds=time.monotonic()-began;stable();sha=digest(bundle,check)
    proof=dict(source=str(source),cache=str(root),manifest=record['manifest'],manifest_sha256=record['manifest_sha256'],
               bundle=str(bundle),sha256=sha,bytes=bundle.stat().st_size,refs=tips,head_state=record['head_state'],
               object_format=record['object_format'],source_ref_warnings=record['source_ref_warnings'],
               bundle_seconds=bundle_seconds,independent_restore_seconds=restore_seconds,
               restored_and_fsck_verified=True,source_retained=True,verified_at=time.time(),
               scope='git-history-only',published=False,retirement_authorized=False)
    store.write_receipt(output/'verified.json',proof)
    return proof


def handoff(store, job_id, proof):
    """Publish a verified artifact for the daemon's existing history reconciliation.

    The original job is held non-runnable during preparation. This function never
    executes a production worker or marks a history job complete itself.
    """
    import fcntl
    if not isinstance(job_id,str) or len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Choose a valid history job identifier')
    directory=store.state/'workspace-history-imports';directory.mkdir(exist_ok=True)
    with (directory/(job_id+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _handoff(store,job_id,proof,directory/(job_id+'.json'))


def _handoff(store,job_id,proof,journal):
    from .core import digest
    from .workspaces import publish_directory,ref_digest
    bundle=Path(proof['bundle']);cache=Path(proof['cache'])
    if (cache.parent!=store.state/'git-object-caches' or cache.resolve()!=cache
            or bundle.resolve()!=bundle or bundle.parent.parent!=cache
            or json.loads((bundle.parent/'verified.json').read_text())!=proof
            or proof.get('restored_and_fsck_verified') is not True or proof.get('scope')!='git-history-only'):
        raise ValueError('History artifact lacks matching private recovery verification')
    record=json.loads((cache/'ready.json').read_text())
    if any(record.get(key)!=proof.get(key) for key in ('source','manifest','manifest_sha256','refs','head_state','object_format','source_ref_warnings')):
        raise ValueError('History artifact differs from its object-cache capture')
    source,_=workspace_source(store,proof['source'])
    result,database=load_manifest(store,proof['manifest'])
    if result['source']!=str(source) or result['sha256']!=proof['manifest_sha256']:
        raise ValueError('History artifact source-manifest binding changed')
    expected={}
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
        for relative,raw,signature,sha in db.execute("SELECT relative,native,signature,sha256 FROM entries WHERE relative='objects' OR relative LIKE 'objects/%'"):
            expected[relative]=dict(kind=json.loads(raw)['kind'],signature=json.loads(signature),sha256=sha)
    def stable():
        object_members(source,expected,lambda:None);warnings=[]
        if history_state(source,warning_sink=warnings)!=(proof['refs'],proof['head_state']) or warnings!=proof['source_ref_warnings']:
            raise ValueError('Source tips changed since local history verification')
    stable()
    if digest(bundle)!=proof['sha256'] or bundle.stat().st_size!=proof['bytes']:
        raise ValueError('Verified local history bundle changed')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if row is None or row['kind']!='workspace_history' or row['path']!=str(source):
            raise ValueError('Choose the original source history job for artifact reconciliation')
        payload=json.loads(row['payload']);destination,_=store.safe_path(payload['destination'],True)
        if row['status']=='preparing' and journal.exists():
            operation=json.loads(journal.read_text())
            if (operation['token']!=payload.get('artifact_preparation') or operation['proof']!=str(bundle.parent/'verified.json')):
                raise ValueError('Another artifact preparation owns this job')
            original_payload=operation['original_payload'];original_status=operation['original_status'];token=operation['token']
        else:
            prior=json.loads(journal.read_text()) if journal.exists() else {}
            retry_hold=(row['status']=='paused' and row['message'].startswith('Local-object artifact preparation held;')
                        and prior.get('original_status')=='paused' and prior.get('phase')=='held'
                        and prior.get('proof')==str(bundle.parent/'verified.json'))
            allowed=(row['status']=='blocked' or retry_hold or (row['status']=='paused' and row['message'].startswith('Held pending large-repository export optimization')))
            if not allowed:raise ValueError('Active, cancelled or explicitly user-paused jobs cannot be replaced')
            original_payload=row['payload'];original_status=row['status'];token=uuid.uuid4().hex
            operation=dict(job=job_id,token=token,proof=str(bundle.parent/'verified.json'),source=str(source),destination=str(destination),
                           original_payload=original_payload,original_status=original_status,phase='preparing',source_retained=True)
            store.write_receipt(journal,operation)
            payload['artifact_preparation']=token
            db.execute("UPDATE jobs SET status='preparing',payload=?,message='Preparing independently verified local-object history artifact',updated=? WHERE id=?",
                       (json.dumps(payload),time.time(),job_id))
            db.execute('INSERT INTO events(at,job_id,message) VALUES(?,?,?)',(time.time(),job_id,'Goal-authorized verified local-object history artifact preparation; source retained'))
    def check():
        with store.db() as db:current=db.execute('SELECT status,payload FROM jobs WHERE id=?',(job_id,)).fetchone()
        if current['status']!='preparing' or json.loads(current['payload']).get('artifact_preparation')!=token:
            raise ValueError('Artifact preparation cancelled or changed; generated data retained')
    try:
        check();private=store.state/'workspace-history-intents'/(job_id+'.json')
        if destination.exists():
            receipt=json.loads((destination/'receipt.json').read_text());intent=json.loads(private.read_text())
            if (receipt.get('job')!=job_id or receipt.get('source')!=str(source) or receipt.get('destination')!=str(destination)
                    or receipt.get('sha256')!=proof['sha256'] or intent.get('verified_bundle_sha256')!=proof['sha256']
                    or any(receipt.get(k)!=proof.get(k) for k in ('refs','head_state','source_ref_warnings','object_format'))
                    or digest(destination/'history.bundle',check)!=proof['sha256']):
                raise ValueError('Existing destination differs from the verified artifact; nothing overwritten')
        else:
            destination.parent.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(destination.parent).free<int(store.setting('reserve'))+proof['bytes']+256*1024**2:
                raise ValueError('History publication needs more archive capacity above reserve')
            staging=destination.parent/('.pending-'+job_id)
            if staging.is_symlink():raise ValueError('History staging was redirected')
            if staging.exists():
                if private.exists():store.write_receipt(staging/'capture-intent.json',json.loads(private.read_text()))
                retained=destination.parent/('.retained-attempt-'+job_id+'-'+uuid.uuid4().hex[:12])
                publish_directory(staging,retained);store.event('Previous history attempt retained before local-object handoff: '+str(retained),job_id)
            staging.mkdir(mode=0o700)
            with bundle.open('rb') as original,(staging/'history.bundle').open('xb') as target:
                while True:
                    check();block=original.read(1024*1024)
                    if not block:break
                    if shutil.disk_usage(destination.parent).free<int(store.setting('reserve'))+64*1024**2:
                        raise ValueError('History publication reached archive capacity reserve')
                    target.write(block)
                target.flush();os.fsync(target.fileno())
            if digest(staging/'history.bundle',check)!=proof['sha256']:
                raise ValueError('Archive copy differs from the independently restored history artifact')
            stable();check()
            intent=dict(job=job_id,source=str(source),destination=str(destination),object_format=proof['object_format'],refs=proof['refs'],
                        head_state=proof['head_state'],source_ref_warnings=proof['source_ref_warnings'],
                        verified_bundle_sha256=proof['sha256'],verified_at=proof['verified_at'],capture_method='verified-local-object-mirror',
                        object_manifest=proof['manifest'],object_manifest_sha256=proof['manifest_sha256'],verification_proof=str(bundle.parent/'verified.json'))
            receipt=dict(job=job_id,source=str(source),destination=str(destination),scope='git-history-only',object_format=proof['object_format'],
                         source_retained=True,space_reclaimed=0,sha256=proof['sha256'],bytes=proof['bytes'],refs=proof['refs'],
                         head_state=proof['head_state'],source_ref_warnings=proof['source_ref_warnings'],bundle_refs=proof['refs'],
                         ref_digest=ref_digest(proof['refs']),restored_and_fsck_verified=True,verified_at=proof['verified_at'],
                         capture_method='verified-local-object-mirror',not_preserved=['working-tree files','ignored and untracked files',
                         'malformed or unreadable raw ref metadata (source unchanged)','LFS object payloads','reflog-only and dangling objects',
                         'hooks and repository configuration','submodule repositories (each requires its own snapshot)'])
            store.write_receipt(private,intent);store.write_receipt(staging/'receipt.json',receipt)
            check();publish_directory(staging,destination)
        operation.update(phase='published',sha256=proof['sha256'],at=time.time());store.write_receipt(journal,operation)
        check()
        with store.db() as db:
            changed=db.execute("UPDATE jobs SET status='pending',payload=?,message='Verified local-object artifact ready for daemon reconciliation',updated=? WHERE id=? AND status='preparing' AND payload=?",
                               (original_payload,time.time(),job_id,json.dumps(payload))).rowcount
            if changed!=1:raise ValueError('Job changed before daemon reconciliation; artifact retained')
            db.execute('INSERT INTO events(at,job_id,message) VALUES(?,?,?)',(time.time(),job_id,'Independent local-object history proof published; daemon reconciliation queued'))
        return str(destination)
    except BaseException as error:
        with store.db() as db:
            row=db.execute('SELECT status,payload FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row['status']=='preparing' and json.loads(row['payload']).get('artifact_preparation')==token:
                db.execute('UPDATE jobs SET status=?,payload=?,message=?,updated=? WHERE id=?',
                           (original_status,original_payload,'Local-object artifact preparation held; source retained: '+str(error),time.time(),job_id))
        operation.update(phase='held',error=str(error),at=time.time());store.write_receipt(journal,operation)
        raise
