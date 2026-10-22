"""Checkbox-reviewed restoration of exact manifest-bound Git object bytes."""
from pathlib import Path
import hashlib,json,os,re,shutil,sqlite3,stat,tempfile,time,uuid,zlib
from . import manifests
from .core import digest
from .models import powershell,windows_path
from .relocations import load_manifest,dependency_gate
from .workspaces import history_state,git,publish_directory


def metadata(path,check=lambda:None):
    with tempfile.TemporaryDirectory() as tmp:
        output=Path(tmp)/'metadata.jsonl';manifests.enumerate_tree(path,output,check)
        rows=list(manifests.entries(output))
    if len(rows)!=1 or rows[0][1]['kind']!='file':raise ValueError('Only a regular native file can be repaired')
    return rows[0][1]


def identity(path):
    value=manifests.file_signature(path)
    if not stat.S_ISREG(value['mode']) or value['nlink']!=1:raise ValueError('Repair requires a regular file with one hard link')
    return value


def same_file(path,signature):
    actual=identity(path)
    return all(actual[k]==signature[k] for k in ('device','inode'))


def propose(store,manifest,relative,artifact,reason,replacement_preview=None):
    result,database=load_manifest(store,manifest);repository=Path(result['source'])
    if not dependency_gate(repository)['bare']:raise ValueError('Object repair currently requires a standalone bare repository')
    if not re.fullmatch(r'objects/[0-9a-f]{2}/[0-9a-f]{38}',relative):raise ValueError('Choose one SHA-1 loose object')
    src,_=store.safe_path(str(repository/relative));replacement,_=store.safe_path(str(artifact))
    if src==replacement:raise ValueError('Recovery artifact must be independent')
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:row=db.execute('SELECT sha256,native FROM entries WHERE relative=?',(relative,)).fetchone()
    if not row or not row[0] or json.loads(row[1])['kind']!='file':raise ValueError('Original object must be bound to a completed manifest')
    if digest(replacement)!=row[0]:raise ValueError('Replacement differs from original sealed manifest')
    if replacement.stat().st_size>512*1024**2:raise ValueError('Recovered object exceeds bounded review scope')
    compressed=replacement.read_bytes()
    decoder=zlib.decompressobj();raw=decoder.decompress(compressed,512*1024*1024)
    if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data or hashlib.sha1(raw).hexdigest()!=relative.replace('objects/','').replace('/',''):
        raise ValueError('Recovered loose object does not match its Git identity')
    bad=digest(src)
    if bad==row[0]:raise ValueError('Source is already correct; no repair required')
    if src.stat().st_size!=replacement.stat().st_size:raise ValueError('Exact original object length required')
    refs,head=history_state(repository)
    snapshot=dict(repository=str(repository),manifest=manifest,manifest_sha256=result['sha256'],relative=relative,
                  source_signature=identity(src),artifact_signature=identity(replacement),damaged_sha256=bad,recovered_sha256=row[0],
                  native=metadata(src),refs=refs,head_state=head)
    if replacement_preview is not None:
        preview,_=store.safe_path(str(replacement_preview))
        if digest(preview)!=row[0]:raise ValueError('Security preview differs from exact recovered payload')
        replacement_native=metadata(preview)
        differences={k for k in snapshot['native'] if snapshot['native'][k]!=replacement_native.get(k)}
        if not differences<= {'sddl'} or 'sddl' not in replacement_native:raise ValueError('Only an explicit native security descriptor difference can be reviewed')
        snapshot['replacement_native']=replacement_native
        snapshot['security_change_reviewed']=True
    ident=uuid.uuid4().hex
    with store.db() as db:
        previous=db.execute("SELECT id FROM candidates WHERE kind='git_object_repair' AND source=? AND status IN ('review','queued')",(str(src),)).fetchone()
        if previous:return previous['id']
        db.execute("INSERT INTO candidates(id,kind,source,destination,snapshot,size,reason,confidence,status,created,updated) VALUES(?,'git_object_repair',?,?,?,?,?,'review','review',?,?)",
                   (ident,str(src),str(replacement),json.dumps(snapshot),src.stat().st_size,reason,time.time(),time.time()))
    store.event('Exact Git object repair proposed for checkbox review; damaged original will be retained: '+str(src))
    return ident


def validate(store,candidate):
    snap=json.loads(candidate['snapshot']);src,_=store.safe_path(candidate['source']);artifact,_=store.safe_path(candidate['destination'])
    result,database=load_manifest(store,snap['manifest'])
    if result['source']!=snap['repository'] or result['sha256']!=snap['manifest_sha256'] or src!=Path(snap['repository'])/snap['relative']:
        raise ValueError('Repair manifest or source binding changed')
    with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:row=db.execute('SELECT sha256 FROM entries WHERE relative=?',(snap['relative'],)).fetchone()
    if row!=(snap['recovered_sha256'],):raise ValueError('Recovery digest differs from sealed original object')
    if identity(src)!=snap['source_signature'] or digest(src)!=snap['damaged_sha256'] or metadata(src)!=snap['native']:
        raise ValueError('Damaged source changed since review')
    if identity(artifact)!=snap['artifact_signature'] or digest(artifact)!=snap['recovered_sha256']:raise ValueError('Recovered artifact changed since review')
    if history_state(Path(snap['repository']))!=(snap['refs'],snap['head_state']):raise ValueError('Repository refs changed since review')
    dependency_gate(Path(snap['repository']))
    return snap


def stage_copy(src,artifact,stage,snap):
    if str(src).startswith('/mnt/'):
        powershell(r'''
$source=Get-Item -LiteralPath $x.source -Force -ErrorAction Stop
$acl=Get-Acl -LiteralPath $x.source -ErrorAction Stop
$attrs=$source.Attributes;$written=$source.LastWriteTimeUtc;$created=$source.CreationTimeUtc
[IO.File]::Copy($x.source,$x.stage,$false)
[IO.File]::SetAttributes($x.stage,([int64]$attrs -band (-bnot 1)))
$artifactStream=[IO.File]::OpenRead($x.artifact)
try {$stagedStream=[IO.File]::Open($x.stage,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None)
try {$stagedStream.SetLength(0);$artifactStream.CopyTo($stagedStream);$stagedStream.Flush($true)}finally{$stagedStream.Dispose()}}finally{$artifactStream.Dispose()}
if(-not $x.reviewedSecurityChange){Set-Acl -LiteralPath $x.stage -AclObject $acl -ErrorAction Stop}
[IO.File]::SetCreationTimeUtc($x.stage,$created);[IO.File]::SetLastWriteTimeUtc($x.stage,$written)
[IO.File]::SetAttributes($x.stage,$attrs)
''',dict(source=windows_path(src),artifact=windows_path(artifact),stage=windows_path(stage),reviewedSecurityChange=snap.get('security_change_reviewed',False)))
    else:
        shutil.copy2(src,stage);mode=stat.S_IMODE(src.stat().st_mode);os.chmod(stage,mode|stat.S_IWUSR)
        with artifact.open('rb') as a,stage.open('r+b') as b:shutil.copyfileobj(a,b);b.truncate();b.flush();os.fsync(b.fileno())
        shutil.copystat(src,stage);os.chmod(stage,mode)


def run(store,job,candidate):
    if candidate['status'] not in ('queued','completed') or candidate['job_id']!=job['id']:raise ValueError('Repair requires its explicit checkbox authorization')
    snap=json.loads(candidate['snapshot']);expected_native=snap.get('replacement_native',snap['native']);src=Path(candidate['source']);artifact=Path(candidate['destination']);check=lambda:store.check(job['id'])
    root=store.safe_path(str(src))[1]
    folder=root/'archive/workspaces/git-object-repairs'/job['id'];quarantine=folder/'damaged-loose-object';stage=folder/'recovered-staging-object'
    journal=store.state/'git-object-repairs'/(job['id']+'.json');binding=hashlib.sha256(candidate['snapshot'].encode()).hexdigest()
    record=json.loads(journal.read_text()) if journal.exists() else None
    def save(phase):
        record.update(phase=phase,updated_at=time.time());store.write_receipt(journal,record)
    if record and (record['candidate']!=candidate['id'] or record['snapshot_sha256']!=binding or record['job']!=job['id']):raise ValueError('Repair authorization receipt changed')
    def finish():
        if not record.get('post_repair_manifest'):
            record['post_repair_manifest']=manifests.enqueue_manifest(store,snap['repository']);save('verified')
        with store.db() as db:db.execute("UPDATE candidates SET status='completed',updated=? WHERE id=?",(time.time(),candidate['id']))
        store.progress(job['id'],1,src.stat().st_size,'Exact Git object restored; full repository fsck passed; damaged native original retained')
    if record and record['phase']=='verified':
        if digest(src,check)!=snap['recovered_sha256'] or digest(quarantine,check)!=snap['damaged_sha256'] or not same_file(src,record['staged_signature']):raise ValueError('Completed repair paths changed; preserve all versions')
        finish();return
    if candidate['status']=='completed':raise ValueError('Completed candidate lacks a verified recovery receipt')
    if record is None:
        validate(store,candidate)
        if shutil.disk_usage(root).free<int(store.setting('reserve'))+src.stat().st_size*2:raise ValueError('Native recovery staging would cross the drive reserve')
        folder.mkdir(parents=True,exist_ok=False)
        record=dict(job=job['id'],candidate=candidate['id'],snapshot_sha256=binding,source=str(src),artifact=str(artifact),quarantine=str(quarantine),stage=str(stage),original_signature=snap['source_signature'],source_data_retained=True,space_reclaimed=0)
        save('intent')
    try:
        check()
        if not quarantine.exists():
            if not same_file(src,snap['source_signature']) or digest(src,check)!=snap['damaged_sha256'] or metadata(src,check)!=snap['native']:raise ValueError('Original source changed; repair held')
            if not stage.exists():stage_copy(src,artifact,stage,snap)
            if digest(stage,check)!=snap['recovered_sha256'] or metadata(stage,check)!=expected_native:raise ValueError('Staged recovery payload or native metadata differs')
            record['staged_signature']=identity(stage);save('prepared');check()
            if digest(src,check)!=snap['damaged_sha256'] or history_state(Path(snap['repository']),check)!=(snap['refs'],snap['head_state']):raise ValueError('Source or refs changed before quarantine')
            publish_directory(src,quarantine);save('quarantined')
        if digest(quarantine,check)!=snap['damaged_sha256'] or not same_file(quarantine,snap['source_signature']) or metadata(quarantine,check)!=snap['native']:raise ValueError('Quarantine integrity differs; preserve all versions')
        if not src.exists():
            if not record.get('staged_signature') or not same_file(stage,record['staged_signature']) or digest(stage,check)!=snap['recovered_sha256']:raise ValueError('Verified staging object is missing or changed')
            publish_directory(stage,src);save('installed')
        if not same_file(src,record['staged_signature']) or digest(src,check)!=snap['recovered_sha256'] or metadata(src,check)!=expected_native:raise ValueError('Installed object changed; preserve all versions')
        if history_state(Path(snap['repository']),check)!=(snap['refs'],snap['head_state']):raise ValueError('Repository refs changed during repair')
        git(Path(snap['repository']),'fsck','--full','--no-reflogs',check=check)
        if history_state(Path(snap['repository']),check)!=(snap['refs'],snap['head_state']) or not same_file(src,record['staged_signature']) or digest(src,check)!=snap['recovered_sha256']:
            raise ValueError('Repository changed during final verification')
        record.update(repository_fsck_verified=True,original_native_metadata_retained=True,replacement_security_change_approved=snap.get('security_change_reviewed',False),manifest=snap['manifest'],recovered_sha256=snap['recovered_sha256']);save('verified')
        finish()
        store.event('Reviewed Git object repair verified; damaged original retained at '+str(quarantine),job['id'])
    except BaseException:
        if record.get('phase')=='verified':raise
        if quarantine.exists():
            try:
                if src.exists():
                    if not record.get('staged_signature') or not same_file(src,record['staged_signature']) or digest(src)!=snap['recovered_sha256']:raise ValueError('New source work retained; automatic rollback cannot overwrite it')
                    publish_directory(src,stage)
                publish_directory(quarantine,src);save('rolled-back')
            except Exception as rollback_error:
                record['rollback_error']=str(rollback_error);save('needs-attention')
        raise
