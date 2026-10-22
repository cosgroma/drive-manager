"""Additive Windows file payload recovery with sealed native metadata retained as data.

This format never claims native ACL/owner activation or SACL capture. It refuses
streams, hardlinks and reparse points rather than silently dropping them.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import time
import uuid
from . import manifests
from .workspaces import workspace_source, publish_directory
from .protected_snapshots import protect_staging

SCOPE = 'full-visible-windows-file-payloads-and-native-inventory'
LINK_SCOPE = 'full-visible-windows-file-payloads-wsl-file-links-and-native-inventory'

RECORD_SCOPE = 'full-visible-windows-file-payloads-inert-link-records-and-native-inventory'

def scope(item):return RECORD_SCOPE if item.get('preserve_native_link_records') else LINK_SCOPE if item.get('preserve_wsl_file_links') else SCOPE

def link_record(relative,entry):
    if 'link_backup_streams' in entry['native']:
        from .native_link_records import decode_streams
        return decode_streams(entry['native']['link_backup_streams'],relative)['link']
    from .native_reparse import decode_relative_file_link
    return decode_relative_file_link(entry['native'].get('reparse_buffer_base64'),relative)

def document(item):
    result=dict(format=1, scope=scope(item), source=str(item['source']), manifest=item['manifest'],
                manifest_seal=item['receipt']['sha256'], entries=item['entries'],
                native_metadata_activation_verified=False, sacl_captured=False)
    if item.get('preserve_wsl_file_links'):result.update(link_security_metadata_captured=False,wsl_file_links=sum(x['native']['kind']=='reparse' for x in item['entries'].values()))
    if item.get('preserve_native_link_records'):result.update(format=2,links_materialized=False,link_security_metadata_captured=False,link_records=sum(x['native']['kind']=='reparse' for x in item['entries'].values()))
    return result

def encoded_document(item):
    encoded=(manifests.canonical(document(item))+'\n').encode()
    if item.get('preserve_native_link_records'):
        from .native_link_records import MAX_INVENTORY_BYTES
        if len(encoded)>MAX_INVENTORY_BYTES:raise ValueError('Native recovery inventory exceeds metadata size budget')
    return encoded

def validate_records(records,preserve_wsl_file_links=False,preserve_native_link_records=False):
    if not isinstance(preserve_native_link_records,bool) or (preserve_native_link_records and preserve_wsl_file_links):raise ValueError('Choose one explicit link format')
    if not isinstance(preserve_wsl_file_links,bool):raise ValueError('Link preservation must be boolean')
    from .native_link_records import MAX_RECORDS
    if not records or len(records)>(MAX_RECORDS if preserve_native_link_records else 100000):raise ValueError('Use a bounded nonempty native inventory')
    for rel,entry in records.items():
        native=entry['native'];sig=entry['signature']
        if (not isinstance(rel,str) or Path(rel).is_absolute() or '..' in Path(rel).parts
                or str(Path(rel))!=rel or ':' in rel or '\\' in rel):
            raise ValueError('Noncanonical native inventory path')
        if native.get('kind')=='reparse' and preserve_native_link_records:
            from .native_link_records import decode_streams
            decoded=decode_streams(native.get('link_backup_streams'),rel);link=decoded['link'];linux=decoded['linux_metadata']
            if native.get('relative')!=rel or native.get('streams')!=[] or not native.get('attributes',0)&1024 or native.get('attributes',0)&20480:raise ValueError('Unsupported inert link metadata')
            if not isinstance(sig,dict) or not stat.S_ISLNK(sig['mode']) or sig['nlink']!=1 or entry['sha256']!=link['raw_sha256']:raise ValueError('Inert link identity differs')
            if (sig['uid'],sig['gid'],sig['mode'])!=(linux['uid'],linux['gid'],linux['mode']):raise ValueError('WSL EA and Linux identity disagree')
            if not link['external']:
                target=records.get(link['resolved_relative'])
                if target is None or target['native']['kind'] not in ('file','dir'):raise ValueError('Internal link target must be a sealed direct file or directory')
            continue
        if native.get('kind')=='reparse' and preserve_wsl_file_links:
            link=link_record(rel,entry)
            if native.get('relative')!=rel or native.get('reparse_additional_streams_absent') is not True or not native.get('attributes',0)&1024 or native.get('streams')!=[] or native.get('attributes',0)&20480 or native.get('attributes',0)&16:raise ValueError('Unsupported reparse metadata')
            if not isinstance(sig,dict) or not stat.S_ISLNK(sig['mode']) or sig['nlink']!=1 or entry['sha256']!=link['raw_sha256']:raise ValueError('WSL link identity or raw digest differs')
            target=records.get(link['resolved_relative'])
            if target is None or target['native']['kind']!='file':raise ValueError('WSL link must target a sealed internal regular file directly')
            continue
        if native.get('relative')!=rel or native.get('kind') not in ('file','dir'):
            raise ValueError('Links, reparse points and special files require another recovery format')
        if native.get('streams')!=[] or not isinstance(native.get('sddl'),str) or not native['sddl']:
            raise ValueError('Named streams or missing native security metadata require another recovery format')
        if native.get('attributes',0)&(1024|20480):raise ValueError('Protected or reparse attributes require another recovery format')
        if not isinstance(sig,dict):raise ValueError('Native file identities are required')
        if native['kind']=='file':
            if not stat.S_ISREG(sig['mode']) or sig['nlink']!=1:raise ValueError('Hardlinks or changed file types require another recovery format')
            digest=entry['sha256']
            if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('A sealed file payload digest is required')
            if sig['size']!=native['size'] or sig['mtime_ns']!=native['mtime_ns']:raise ValueError('Native file metadata disagrees with its identity')
        elif not stat.S_ISDIR(sig['mode']):raise ValueError('Native directory identity changed')
    if '.' not in records or records['.']['native']['kind']!='dir':raise ValueError('Native inventory root must be a directory')
    for rel in records:
        if rel!='.' and (str(Path(rel).parent) not in records or records[str(Path(rel).parent)]['native']['kind']!='dir'):
            raise ValueError('Native inventory omitted a parent directory')

def load(store,ident,preserve_wsl_file_links=False,preserve_native_link_records=False):
    with store.db() as db:
        row=db.execute('select m.*,j.status from workspace_manifests m join jobs j on j.id=m.job_id where m.job_id=?',(ident,)).fetchone()
    if row is None or row['status']!='completed' or not row['result']:raise ValueError('A completed native manifest is required')
    receipt=json.loads(row['result']);source,_=workspace_source(store,row['source'])
    if not str(source).startswith('/mnt/') or receipt.get('native_metadata') is not True:
        raise ValueError('This format requires a native Windows source')
    if receipt.get('job')!=ident or receipt.get('source')!=str(source) or receipt.get('scope')!='full-visible-tree-manifest':
        raise ValueError('Native manifest receipt binding differs')
    from .native_link_records import MAX_RECORDS, MAX_INVENTORY_BYTES
    limit=MAX_RECORDS if preserve_native_link_records else 100000
    if type(receipt.get('entries')) is not int or not 0<receipt['entries']<=limit:raise ValueError('Native manifest exceeds entry budget')
    records={};h=hashlib.sha256();metadata_bytes=0
    with sqlite3.connect('file:'+str(store.state/'workspace-manifests'/ident/'manifest.sqlite3')+'?mode=ro',uri=True) as db:
        for rel,native,sig,digest in db.execute('select relative,native,signature,sha256 from entries order by relative'):
            metadata_bytes+=len(rel.encode())+len(native.encode())+len((sig or '').encode())+128
            if len(records)>=limit or (preserve_native_link_records and metadata_bytes>MAX_INVENTORY_BYTES):raise ValueError('Native manifest exceeds bounded inventory budget')
            native=json.loads(native);sig=json.loads(sig) if sig else None
            h.update(manifests.canonical(dict(relative=rel,native=native,signature=sig,sha256=digest)).encode()+b'\n')
            records[rel]=dict(native=native,signature=sig,sha256=digest)
    if h.hexdigest()!=receipt['sha256'] or len(records)!=receipt['entries']:raise ValueError('Native manifest seal differs')
    if preserve_wsl_file_links and receipt.get('preserve_wsl_file_links') is not True:raise ValueError('A link-preserving sealed manifest is required')
    if preserve_native_link_records and receipt.get('preserve_native_link_records') is not True:raise ValueError('An inert-link sealed manifest is required')
    validate_records(records,preserve_wsl_file_links,preserve_native_link_records)
    if preserve_native_link_records and sum(e['native']['kind']=='reparse' for e in records.values())!=receipt.get('link_records'):raise ValueError('Sealed link record count differs')
    if preserve_wsl_file_links and sum(e['native']['kind']=='reparse' for e in records.values())!=receipt.get('wsl_file_links'):raise ValueError('Sealed link count differs')
    if sum(e['native']['kind']=='file' for e in records.values())!=receipt['files'] or sum(e['native']['size'] for e in records.values() if e['native']['kind']=='file')!=receipt['bytes']:
        raise ValueError('Native manifest totals differ')
    return dict(manifest=ident,receipt=receipt,source=source,entries=records,preserve_wsl_file_links=preserve_wsl_file_links,preserve_native_link_records=preserve_native_link_records)

def enqueue(store,ident,archive_root=None,preserve_wsl_file_links=False,preserve_native_link_records=False):
    item=load(store,ident,preserve_wsl_file_links,preserve_native_link_records);root,_=store.safe_path(archive_root or '/mnt/h/archive/workspaces',True)
    if root==item['source'] or item['source'] in root.parents or root in item['source'].parents:raise ValueError('Recovery archive must be separate from its source')
    with store.db() as db:
        for row in db.execute("select id,payload from jobs where kind='workspace_snapshot' and status in ('pending','running','paused')"):
            old=json.loads(row['payload'])
            if old.get('native_windows_files') is True and old.get('manifests')==[ident] and old.get('preserve_wsl_file_links',False)==preserve_wsl_file_links and old.get('preserve_native_link_records',False)==preserve_native_link_records and Path(old['destination']).parent.parent==root:return row['id']
        job=uuid.uuid4().hex;destination=root/'native-file-snapshots'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+job[:12])
        payload=dict(native_windows_files=True,manifests=[ident],manifest_seals=[item['receipt']['sha256']],destination=str(destination))
        if preserve_wsl_file_links:payload['preserve_wsl_file_links']=True
        if preserve_native_link_records:payload['preserve_native_link_records']=True
        db.execute("insert into jobs(id,kind,path,status,payload,created,updated) values(?,'workspace_snapshot',?,'pending',?,?,?)",(job,str(item['source']),json.dumps(payload),time.time(),time.time()))
    store.event('Native file recovery queued; original files retained and native metadata activation remains separate',job)
    return job

def verify_source(item,output,check):
    if item.get('preserve_native_link_records'):manifests.enumerate_tree(item['source'],output,check,True)
    else:manifests.enumerate_tree(item['source'],output,check)
    seen=set()
    for rel,native in manifests.entries(output):
        check()
        if rel in seen or rel not in item['entries'] or native!=item['entries'][rel]['native']:raise ValueError('Native tree membership or metadata changed: '+rel)
        if native['kind']=='reparse' and os.readlink(item['source']/rel)!=link_record(rel,item['entries'][rel])['target']:raise ValueError('Source link target changed')
        if manifests.file_signature(item['source']/rel)!=item['entries'][rel]['signature']:raise ValueError('Source identity changed: '+rel)
        seen.add(rel)
    if seen!=set(item['entries']):raise ValueError('Native tree membership changed')

class CheckedReader:
    def __init__(self,handle,check):self.handle=handle;self.check=check;self.sha=hashlib.sha256();self.since=0
    def read(self,size=-1):
        data=self.handle.read(size);self.sha.update(data);self.since+=len(data)
        if self.since>=1024**2:self.check();self.since=0
        return data

def write_tar(item,path,check):
    with tarfile.open(path,'x',format=tarfile.PAX_FORMAT) as tar:
        for rel,entry in sorted(item['entries'].items()):
            check();source=item['source']/rel;expected=entry['signature']
            if manifests.file_signature(source)!=expected:raise ValueError('Source identity changed before capture: '+rel)
            info=tarfile.TarInfo('tree' if rel=='.' else 'tree/'+rel);info.mode=0o700 if entry['native']['kind']=='dir' else 0o600
            if entry['native']['kind']=='dir':info.type=tarfile.DIRTYPE;tar.addfile(info);continue
            if entry['native']['kind']=='reparse':
                if item.get('preserve_native_link_records'):
                    link=link_record(rel,entry)
                    if os.readlink(source)!=link['target'] or manifests.file_signature(source)!=expected:raise ValueError('Source inert link changed')
                    continue
                if not item.get('preserve_wsl_file_links'):raise ValueError('Explicit link capture mode required')
                link=link_record(rel,entry)
                if os.readlink(source)!=link['target'] or manifests.file_signature(source)!=expected:raise ValueError('Source link target or identity changed')
                info.type=tarfile.SYMTYPE;info.linkname=link['target'];tar.addfile(info);continue
            info.size=expected['size'];fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as handle:
                value=os.fstat(handle.fileno())
                if (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)!=(expected['device'],expected['inode'],expected['size'],expected['mtime_ns'],expected['ctime_ns']):
                    raise ValueError('Source file changed when opened: '+rel)
                reader=CheckedReader(handle,check);tar.addfile(info,reader)
                if reader.sha.hexdigest()!=entry['sha256'] or manifests.file_signature(source)!=expected:raise ValueError('Source payload or identity changed during capture: '+rel)
        metadata=encoded_document(item);info=tarfile.TarInfo('native-inventory.json');info.mode=0o600;info.size=len(metadata);tar.addfile(info,io.BytesIO(metadata))
    with path.open('rb') as handle:os.fsync(handle.fileno())

def audit_tar(item,path,check):
    expected={'tree' if r=='.' else 'tree/'+r:e for r,e in item['entries'].items() if not (item.get('preserve_native_link_records') and e['native']['kind']=='reparse')};seen=set()
    with tarfile.open(path,'r') as tar:
        for member in tar:
            check()
            if member.name in seen:raise ValueError('Duplicate archive member')
            seen.add(member.name)
            if member.name=='native-inventory.json':
                if not member.isfile() or member.size!=len(encoded_document(item)) or tar.extractfile(member).read()!=encoded_document(item):raise ValueError('Archived native inventory differs')
                continue
            if member.name not in expected:raise ValueError('Unexpected archive member')
            entry=expected[member.name]
            if entry['native']['kind']=='dir':
                if not member.isdir():raise ValueError('Archive directory type differs')
            elif entry['native']['kind']=='reparse':
                if not item.get('preserve_wsl_file_links') or not member.issym() or member.linkname!=link_record(member.name.removeprefix('tree/'),entry)['target'] or member.size!=0:raise ValueError('Archived link differs')
            else:
                if not member.isfile() or member.size!=entry['native']['size']:raise ValueError('Archive file type or size differs')
                h=hashlib.sha256()
                with tar.extractfile(member) as handle:
                    while True:
                        data=handle.read(1024**2)
                        if not data:break
                        check();h.update(data)
                if h.hexdigest()!=entry['sha256']:raise ValueError('Archived file payload differs')
    if seen!=set(expected)|{'native-inventory.json'}:raise ValueError('Archive membership differs')

def verify_restored(item,restore,check):
    tree=restore/'tree';seen=set()
    if {p.name for p in restore.iterdir()}!={'tree','native-inventory.json'} or tree.is_symlink() or (restore/'native-inventory.json').is_symlink():raise ValueError('Unexpected restored root or link')
    for base,dirs,files in os.walk(tree,followlinks=False):
        for path in [Path(base),*[Path(base)/n for n in files]]:
            check();rel=str(path.relative_to(tree));seen.add(rel)
            if rel not in item['entries']:raise ValueError('Unexpected restored member')
            expected=item['entries'][rel];value=path.lstat()
            if expected['native']['kind']=='dir':
                if not stat.S_ISDIR(value.st_mode):raise ValueError('Restored directory type differs')
            elif expected['native']['kind']=='reparse':
                if not item.get('preserve_wsl_file_links') or not stat.S_ISLNK(value.st_mode) or value.st_nlink!=1 or os.readlink(path)!=link_record(rel,expected)['target']:raise ValueError('Restored link target or type differs')
            else:
                if not stat.S_ISREG(value.st_mode) or value.st_nlink!=1 or value.st_size!=expected['native']['size']:raise ValueError('Restored file type or size differs')
                with path.open('rb') as handle:h=hashlib.file_digest(handle,'sha256').hexdigest()
                if h!=expected['sha256']:raise ValueError('Restored file payload differs')
        if any((Path(base)/n).is_symlink() for n in dirs):raise ValueError('Restored directory link is unsupported')
    expected_members={r for r,e in item['entries'].items() if not (item.get('preserve_native_link_records') and e['native']['kind']=='reparse')}
    if seen!=expected_members or (restore/'native-inventory.json').read_bytes()!=encoded_document(item):raise ValueError('Restored tree or native inventory differs')

def run(store,job):
    from .core import digest
    payload=json.loads(job['payload']);item=load(store,payload['manifests'][0],payload.get('preserve_wsl_file_links',False),payload.get('preserve_native_link_records',False));ident=job['id'];check=lambda:store.check(ident)
    if payload.get('native_windows_files') is not True or payload.get('manifests')!=[item['manifest']] or payload.get('manifest_seals')!=[item['receipt']['sha256']] or job['path']!=str(item['source']):raise ValueError('Native snapshot intent differs')
    destination,_=store.safe_path(payload['destination'],True)
    if destination==item['source'] or item['source'] in destination.parents or destination in item['source'].parents:raise ValueError('Recovery destination overlaps source')
    private=store.state/'workspace-snapshots'/ident;private.mkdir(parents=True,exist_ok=True)
    intent=dict(job=ident,sources=[str(item['source'])],destination=str(destination),manifests=payload['manifests'],manifest_seals=payload['manifest_seals'],scope=scope(item))
    if item.get('preserve_native_link_records'):intent.update(link_records=item['receipt']['link_records'],links_materialized=False,link_security_metadata_captured=False)
    if item.get('preserve_wsl_file_links'):intent.update(wsl_file_links=item['receipt']['wsl_file_links'],link_security_metadata_captured=False)
    if destination.exists():
        receipt=json.loads((destination/'receipt.json').read_text());prior=json.loads((private/'intent.json').read_text())
        if {k:v for k,v in prior.items() if k!='verified_receipt'}!=intent or prior.get('verified_receipt')!=receipt or any(receipt.get(k)!=v for k,v in intent.items()) or not receipt.get('restored_and_verified') or receipt.get('native_metadata_activation_verified') is not False or receipt.get('source_retained') is not True or receipt.get('retirement_authorized') is not False or receipt.get('sacl_captured') is not False or receipt.get('protected_windows_archive_acl') is not True or receipt.get('archive_bytes')!=(destination/'native-tree.tar').stat().st_size or digest(destination/'native-tree.tar',check)!=receipt['sha256']:raise ValueError('Published native recovery archive differs')
        store.write_receipt(private/'result.json',receipt);return
    destination.parent.mkdir(parents=True,exist_ok=True);restore_parent=store.state/'snapshot-restore-checks';restore_parent.mkdir(mode=0o700,exist_ok=True)
    amount=item['receipt']['bytes']+len(encoded_document(item))+len(item['entries'])*2048
    for path in (destination.parent,restore_parent):
        if shutil.disk_usage(path).free<int(store.setting('reserve'))+amount+256*1024**2:raise ValueError('Native archive and independent restore require capacity above reserve')
    staging=destination.parent/('.pending-'+ident)
    if staging.is_symlink():raise ValueError('Native recovery staging was redirected')
    if staging.exists():publish_directory(staging,destination.parent/('.retained-attempt-'+ident+'-'+uuid.uuid4().hex[:12]))
    staging.mkdir(mode=0o700);protected=protect_staging(staging)
    if not protected:raise ValueError('Native recovery archive needs a protected Windows ACL')
    store.write_receipt(private/'intent.json',intent)
    store.progress(ident,0,0,'Checking sealed native source before additive capture')
    verify_source(item,private/'native-before.jsonl',check)
    archive=staging/'native-tree.tar';write_tar(item,archive,check)
    store.progress(ident,item['receipt']['files'],item['receipt']['bytes'],'Auditing native file payloads and independently restoring archive')
    audit_tar(item,archive,check)
    with tempfile.TemporaryDirectory(prefix='native-recovery-',dir=restore_parent) as temp:
        restore=Path(temp)
        with tarfile.open(archive,'r') as tar:tar.extractall(restore,filter='data')
        verify_restored(item,restore,check)
    sha=digest(archive,check);verify_source(item,private/'native-after.jsonl',check)
    receipt=dict(intent,sha256=sha,archive_bytes=archive.stat().st_size,files=item['receipt']['files'],bytes=item['receipt']['bytes'],source_retained=True,restored_and_verified=True,native_metadata_activation_verified=False,sacl_captured=False,protected_windows_archive_acl=True,space_reclaimed=0,retirement_authorized=False,verified_at=time.time(),limitations=['Native metadata is retained verbatim as sealed data; owner/ACL activation on Windows is not tested.','Windows SACL audit rules are outside the source inventory.','Original sources must remain until full native recovery and dependency requirements are separately satisfied.'])
    if item.get('preserve_native_link_records'):receipt['limitations'].append('Links, raw reparse buffers and WSL EA records are retained as inert sealed data. Links are not materialized in the independent restore; external dependencies and Windows owner/ACL activation remain unverified.')
    if item.get('preserve_wsl_file_links'):receipt['limitations'].append('WSL relative file links and raw reparse buffers are verified; native link security metadata and owner/ACL activation are not captured or verified.')
    store.write_receipt(private/'intent.json',dict(intent,verified_receipt=receipt))
    store.write_receipt(staging/'receipt.json',receipt);check();publish_directory(staging,destination);store.write_receipt(private/'result.json',receipt)
    store.progress(ident,receipt['files'],receipt['bytes'],'File payloads independently restored; native metadata retained as sealed data; source retained')
