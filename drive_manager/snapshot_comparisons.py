"""Digest-bound comparison of complete recorded trees; never retirement authority."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .manifests import canonical


def named_stream_scope(result):
    value=result.get('named_stream_scope')
    if value in ('files-and-directories','posix-xattrs-and-links'):return value
    if result.get('native_metadata') is True:return 'legacy-file-streams'
    if result.get('native_metadata') is False:return 'posix-xattrs-and-links'
    return 'unrecorded'


def compare(store,left,right):
    if left==right:raise ValueError('Choose two different manifests')
    inputs=[]
    with store.db() as db:
        for ident in (left,right):
            row=db.execute('SELECT a.*,j.status FROM workspace_manifests a JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?',(ident,)).fetchone()
            if row is None or row['status']!='completed' or not row['result']:raise ValueError('Both manifests must have completed verification')
            result=json.loads(row['result'])
            if result.get('job')!=ident or result.get('source')!=row['source'] or result.get('scope')!='full-visible-tree-manifest':
                raise ValueError('Manifest receipt does not belong to this complete source tree')
            inputs.append(dict(row,result=result))
    connections=[]
    def entries(item):
        path=store.state/'workspace-manifests'/item['job_id']/'manifest.sqlite3'
        db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);connections.append(db)
        digest=hashlib.sha256();count=0;root_seen=False
        for rel,raw,sig,sha in db.execute('SELECT relative,native,signature,sha256 FROM entries ORDER BY relative'):
            native=json.loads(raw);signature=json.loads(sig) if sig else None
            if Path(rel).is_absolute() or '..' in Path(rel).parts or native.get('relative')!=rel:
                raise ValueError('Invalid manifest-relative path')
            if native['kind'] not in ('file','dir','link') or not signature:
                raise ValueError('Incomplete or unsupported entry in the full-tree comparison')
            if native['kind']=='file' and (not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha)):
                raise ValueError('Full-tree manifest contains an unhashed regular file')
            digest.update(canonical(dict(relative=rel,native=native,signature=signature,sha256=sha)).encode()+b'\n')
            count+=1;root_seen|=rel=='.'
            yield rel,native,signature,sha
        if not root_seen or count!=item['result']['entries'] or digest.hexdigest()!=item['result']['sha256']:
            raise ValueError('Manifest database differs from its completed verification receipt')
    def streams(native):return sorted(native.get('streams',[]),key=lambda s:s['name'])
    def payload(entry):
        _,native,_,sha=entry
        if native['kind']=='file':return canonical([sha,native['size'],streams(native)])
        if native['kind']=='dir':return canonical(streams(native))
        return canonical(native.get('target'))
    def metadata(entry):
        _,native,sig,_=entry
        fields={k:v for k,v in native.items() if k not in ('relative','target','streams')}
        if 'streams' in native:fields['streams']=[{k:v for k,v in s.items() if k!='sha256'} for s in streams(native)]
        # Device/inode and ctime describe the particular copy, not portable
        # permissions. All remaining recorded fields are compared, including root.
        fields['permissions']={k:sig[k] for k in ('mode','uid','gid','nlink')}
        return canonical(fields)
    keys=('same_payload','different_payload','same_directory','different_kind','only_left','only_right','same_recorded_metadata','different_recorded_metadata')
    counts=dict.fromkeys(keys,0);samples={k:[] for k in keys}
    def note(kind,path):
        counts[kind]+=1
        if len(samples[kind])<50:samples[kind].append(path)
    try:
        a,b=entries(inputs[0]),entries(inputs[1]);x,y=next(a,None),next(b,None)
        while x is not None or y is not None:
            if y is None or (x is not None and x[0]<y[0]):note('only_left',x[0]);x=next(a,None)
            elif x is None or y[0]<x[0]:note('only_right',y[0]);y=next(b,None)
            else:
                if x[1]['kind']!=y[1]['kind']:note('different_kind',x[0])
                else:
                    if x[1]['kind']=='dir':note('same_directory',x[0])
                    if x[1]['kind']!='dir' or streams(x[1]) or streams(y[1]):
                        note('same_payload' if payload(x)==payload(y) else 'different_payload',x[0])
                    note('same_recorded_metadata' if metadata(x)==metadata(y) else 'different_recorded_metadata',x[0])
                x,y=next(a,None),next(b,None)
    finally:
        for db in connections:db.close()
    membership_equal=not any(counts[k] for k in ('only_left','only_right','different_kind'))
    payloads_equal=membership_equal and counts['different_payload']==0
    models=[item['result'].get('native_metadata') for item in inputs]
    compatible=all(isinstance(value,bool) for value in models) and models[0]==models[1]
    stream_scopes=[named_stream_scope(item['result']) for item in inputs]
    result=dict(left=inputs[0]['source'],right=inputs[1]['source'],left_manifest=left,right_manifest=right,
                left_manifest_sha256=inputs[0]['result']['sha256'],right_manifest_sha256=inputs[1]['result']['sha256'],
                left_verified_at=inputs[0]['result'].get('verified_at'),right_verified_at=inputs[1]['result'].get('verified_at'),
                counts=counts,samples=samples,checked_at=time.time(),comparison_kind='full-tree',scope='Full recorded trees, including Git internals, ignored files, directories and named streams',
                manifest_digests_verified=True,membership_equal=membership_equal,all_recorded_payloads_equal=payloads_equal,
                metadata_models_compatible=compatible,compared_metadata_equal=compatible and membership_equal and counts['different_recorded_metadata']==0,
                named_stream_capture_scopes=stream_scopes,
                directory_stream_capture_complete=all(value in ('files-and-directories','posix-xattrs-and-links') for value in stream_scopes),
                metadata_equivalence_proven=False,retirement_authorized=False,
                limitations=['Only payloads and metadata recorded by the manifests are compared. Unrecorded data remains outside proof.',
                             'File identity (device/inode/ctime) is excluded from portable metadata comparison; recorded permissions, xattrs, NTFS attributes/DACL and mtime are included.',
                             'Hard-link relationships, unrecorded NTFS streams/metadata and external link targets are not established by this comparison.',
                             'Input stream capture scopes: '+', '.join(stream_scopes)+'. Legacy native inputs need fresh manifests before complete NTFS stream retention decisions.',
                             'Manifest points in time are compared, not current source files. Dependency closure, independent backup and recovery still require verification.',
                             'Equal recorded payloads or metadata do not grant permission to retire either source.'])
    store.write_receipt(store.state/'workspace-comparisons'/(uuid.uuid4().hex+'.json'),result)
    return result
