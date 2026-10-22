"""Additive cold PostgreSQL archives with privileged, exact-owner verification.

This mode never starts PostgreSQL, changes source permissions or retires data.
A separately audited activation of a copy is still required for runtime proof.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time
import uuid

from .workspaces import command, publish_directory, workspace_source


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def load_seal(store, path, expected, cluster_relative='.'):
    path = Path(path)
    base = store.state / 'validation' / 'protected-cluster'
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
        raise ValueError('Choose a private protected-cluster seal')
    if path.stat().st_size > 8 * 1024**2 or sha(path) != expected:
        raise ValueError('Protected seal digest differs or exceeds bounded metadata capacity')
    document = json.loads(path.read_text())
    if document.get('scope') != 'full-protected-posix-tree' or document.get('source_written') is not False:
        raise ValueError('Protected full-tree seal required')
    source, _ = workspace_source(store, document['source'])
    if str(source).startswith('/mnt/') or str(source) != document['source']:
        raise ValueError('Protected archives require a canonical Linux workspace source')
    records = document['records']; seen = set()
    if not isinstance(records, list) or not records:
        raise ValueError('Empty protected seal')
    for r in records:
        rel = r['relative']; sig = r['signature']; kind = r['kind']
        if not isinstance(rel, str) or Path(rel).is_absolute() or '..' in Path(rel).parts or rel in seen:
            raise ValueError('Invalid or repeated sealed path')
        if rel != '.' and (str(Path(rel)) != rel or not rel):
            raise ValueError('Noncanonical sealed path')
        if kind not in ('file', 'dir') or not isinstance(r['xattrs'], dict):
            raise ValueError('Protected links or special entries are unsupported')
        if (kind == 'file' and (not stat.S_ISREG(sig['mode']) or sig['nlink'] != 1)) or (kind == 'dir' and not stat.S_ISDIR(sig['mode'])):
            raise ValueError('Invalid protected entry type or hardlink')
        if sig['mode'] & (stat.S_ISUID | stat.S_ISGID) or 'security.capability' in r['xattrs']:
            raise ValueError('Privileged executable metadata is unsupported')
        if kind == 'file' and (not isinstance(r['sha256'], str) or len(r['sha256']) != 64 or any(c not in '0123456789abcdef' for c in r['sha256'])):
            raise ValueError('Protected file payload lacks a SHA-256 seal')
        seen.add(rel)
    indexed = {r['relative']: r for r in records}
    if '.' not in indexed or indexed['.']['kind'] != 'dir' or records[0]['relative'] != '.':
        raise ValueError('Root-first protected inventory required')
    for rel in seen - {'.'}:
        parent = str(Path(rel).parent)
        if parent not in indexed or indexed[parent]['kind'] != 'dir':
            raise ValueError('Protected inventory omitted a parent directory')
    if not isinstance(cluster_relative,str) or Path(cluster_relative).is_absolute() or '..' in Path(cluster_relative).parts or str(Path(cluster_relative))!=cluster_relative:
        raise ValueError('Choose a canonical relative cluster directory')
    cluster_prefix = '' if cluster_relative=='.' else cluster_relative+'/'
    if cluster_relative not in indexed or indexed[cluster_relative]['kind']!='dir':
        raise ValueError('Protected inventory lacks the selected cluster directory')
    if {cluster_prefix+n for n in ('postmaster.pid','standby.signal','recovery.signal')} & seen:
        raise ValueError('Active or recovery-mode PostgreSQL sources require a separate plan')
    if indexed.get(cluster_prefix+'PG_VERSION', {}).get('sha256') != hashlib.sha256(b'15\n').hexdigest() or indexed.get(cluster_prefix+'global/pg_control', {}).get('kind') != 'file':
        raise ValueError('A complete PostgreSQL 15 cluster seal is required')
    return document


def tools(store):
    proof_path = store.state / 'workspace-review' / 'pg15-recovery-tools-build.json'
    proof = json.loads(proof_path.read_text())
    if proof.get('phase') != 'verified':
        raise ValueError('Verified matching PostgreSQL tools required')
    reader = next(r for r in proof['binaries'] if r['name'] == 'pg_controldata')
    binary = Path(reader['path'])
    if not binary.resolve().is_relative_to((store.state / 'tools').resolve()) or sha(binary) != reader['sha256']:
        raise ValueError('Pinned PostgreSQL control-reader binary changed')
    helper = Path(__file__).with_name('protected_tree.py')
    return {'reader': str(binary), 'reader_sha256': reader['sha256'], 'helper_sha256': sha(helper)}


def enqueue(store, seal_path, seal_sha256, archive_root=None, cluster_relative='.'):
    document = load_seal(store, seal_path, seal_sha256, cluster_relative); pinned = tools(store)
    command(['sudo', '-n', '--', 'true'], timeout=10)
    root, _ = store.safe_path(archive_root or '/mnt/h/archive/workspaces', True)
    source = Path(document['source'])
    if source == root or source in root.parents or root in source.parents:
        raise ValueError('Archive and source must be separate')
    ident = uuid.uuid4().hex
    destination = root / 'protected-postgres-snapshots' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + ident[:12])
    payload = dict(protected_postgres=True, cluster_relative=cluster_relative, manifests=[], source=str(source), seal_path=str(Path(seal_path)), seal_sha256=seal_sha256, destination=str(destination), tools=pinned)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute("SELECT id,payload FROM jobs WHERE kind='workspace_snapshot' AND status IN ('pending','running','paused')"):
            old = json.loads(row['payload'])
            if old.get('protected_postgres') and old.get('source') == str(source) and old.get('seal_sha256') == seal_sha256 and old.get('cluster_relative','.') == cluster_relative and Path(old['destination']).parent == destination.parent:
                return row['id']
        db.execute("INSERT INTO jobs(id,kind,path,status,payload,created,updated) VALUES(?,'workspace_snapshot',?,'pending',?,?,?)", (ident, str(source), json.dumps(payload), time.time(), time.time()))
    store.event('Protected PostgreSQL cold snapshot queued; original cluster retained and never started', ident)
    return ident


def verify_restored(expected, restored):
    left = {r['relative']: r for r in expected['records']}
    right = {r['relative']: r for r in restored['records']}
    if left.keys() != right.keys():
        raise ValueError('Protected restore membership differs')
    for rel, a in left.items():
        b = right[rel]
        if any(a[k] != b[k] for k in ('kind', 'xattrs', 'sha256')):
            raise ValueError('Protected restored payload or metadata differs: ' + rel)
        keys = ('mode', 'uid', 'gid', 'nlink', 'mtime_ns') + (('size',) if a['kind'] == 'file' else ())
        if any(a['signature'][k] != b['signature'][k] for k in keys):
            raise ValueError('Protected restored ownership or permissions differ: ' + rel)


def protect_staging(path):
    """Protect newly created archive data before any cluster payload is written."""
    if str(path).startswith('/mnt/'):
        from .models import powershell, windows_path
        powershell(r"""
$acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
$principals=@([Security.Principal.WindowsIdentity]::GetCurrent().User,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach($principal in $principals){$rule=[Security.AccessControl.FileSystemAccessRule]::new($principal,'FullControl','ContainerInherit,ObjectInherit','None','Allow');$acl.AddAccessRule($rule)}
Set-Acl -LiteralPath $x.path -AclObject $acl -ErrorAction Stop
$actual=Get-Acl -LiteralPath $x.path -ErrorAction Stop
if(-not $actual.AreAccessRulesProtected){throw 'Archive ACL inheritance was not protected'}
$allowed=@($principals | ForEach-Object {$_.Value})
foreach($rule in $actual.Access){$sid=$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value;if($sid -notin $allowed -or $rule.AccessControlType -ne 'Allow'){throw 'Unexpected archive ACL principal or rule'}}
""", {'path': windows_path(path)})
        return True
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ValueError('Private archive staging permissions differ')
    return False


def run(store, job):
    from .core import digest
    from .snapshots import audit_tar
    payload = json.loads(job['payload'])
    cluster_relative=payload.get('cluster_relative','.')
    document = load_seal(store, payload['seal_path'], payload['seal_sha256'], cluster_relative)
    if document['source'] != job['path'] or document['source'] != payload['source'] or tools(store) != payload['tools']:
        raise ValueError('Queued protected source or recovery tools changed')
    source = Path(document['source']); check = lambda: store.check(job['id'])
    destination, _ = store.safe_path(payload['destination'], True)
    private = store.state / 'workspace-snapshots' / job['id']; private.mkdir(parents=True, exist_ok=True)
    intent_path = private / 'intent.json'
    if destination.exists():
        receipt = json.loads((destination / 'receipt.json').read_text())
        if not intent_path.exists() or json.loads(intent_path.read_text()).get('verified_receipt') != receipt:
            raise ValueError('Published protected archive lacks private verification evidence')
        if digest(destination / 'cluster.tar', check) != receipt['sha256'] or sha(destination / 'source-seal.json') != payload['seal_sha256']:
            raise ValueError('Published protected archive changed')
        store.write_receipt(private / 'result.json', receipt)
        return
    amount = sum(r['signature']['size'] for r in document['records'] if r['kind'] == 'file')
    destination.parent.mkdir(parents=True, exist_ok=True)
    restore_parent = store.state / 'protected-snapshot-restore-checks'; restore_parent.mkdir(mode=0o700, exist_ok=True)
    for location in (destination.parent, restore_parent):
        if shutil.disk_usage(location).free < int(store.setting('reserve')) + amount + 256 * 1024**2:
            raise ValueError('Protected capture requires archive and restore capacity above reserve')
    staging = destination.parent / ('.pending-' + job['id'])
    if staging.is_symlink():raise ValueError('Protected snapshot staging was redirected')
    if staging.exists():publish_directory(staging, destination.parent / ('.retained-attempt-' + job['id'] + '-' + uuid.uuid4().hex[:12]))
    staging.mkdir(mode=0o700)
    windows_acl_protected = protect_staging(staging)
    restore = restore_parent / (job['id'] + '-' + uuid.uuid4().hex[:12]); restore.mkdir(mode=0o700)
    intent = dict(job=job['id'], sources=[str(source)], destination=str(destination), manifests=[], manifest_seals=[payload['seal_sha256']], restore_check=str(restore), tools=payload['tools'])
    store.write_receipt(intent_path, intent)
    prefix = ['sudo', '-n', '--']; helper = Path(__file__).with_name('protected_tree.py')
    def capacity_check():
        check()
        if any(shutil.disk_usage(p).free < int(store.setting('reserve')) + 64 * 1024**2 for p in (destination.parent, restore_parent)):
            raise ValueError('Protected archive reserve reached; partial attempt retained')
    def read_tree(path):
        return json.loads(command(prefix + ['/usr/bin/python3', str(helper), str(path)], check=capacity_check, timeout=1800))
    def progress(message):store.progress(job['id'], 0, 0, message)
    progress('Revalidating protected PostgreSQL full-file seal before capture')
    if read_tree(source) != document:raise ValueError('Protected source changed since full-file sealing')
    shutil.copyfile(payload['seal_path'], staging / 'source-seal.json')
    if sha(staging / 'source-seal.json') != payload['seal_sha256']:raise ValueError('Protected source seal changed')
    listing = private / 'members.list'
    listing.write_bytes(b''.join(os.fsencode(source.name if r['relative'] == '.' else source.name + '/' + r['relative']) + b'\0' for r in document['records']))
    archive = staging / 'cluster.tar'; archive.touch(mode=0o600, exist_ok=False)
    progress('Capturing protected cluster with exact numeric directory and file ownership')
    command(prefix + ['tar', '--create', '--file=' + str(archive), '--format=pax', '--numeric-owner', '--acls', '--xattrs', '--xattrs-include=*', '--atime-preserve=system', '--no-recursion', '--directory=' + str(source.parent), '--null', '--verbatim-files-from', '--files-from=' + str(listing)], check=capacity_check, timeout=14400)
    archive_sha = digest(archive, check)
    entries = {r['relative']: ({'kind': r['kind'], 'size': r['signature']['size']}, r['signature'], r['sha256']) for r in document['records']}
    progress('Auditing every protected archive payload and member before extraction')
    audit_tar(archive, [{'source': source, 'entries': entries}], check)
    command(prefix + ['tar', '--extract', '--file=' + str(archive), '--directory=' + str(restore), '--numeric-owner', '--same-owner', '--same-permissions', '--acls', '--xattrs', '--xattrs-include=*', '--delay-directory-restore', '--keep-old-files'], check=capacity_check, timeout=14400)
    progress('Verifying every restored protected file and directory without changing source permissions')
    verify_restored(document, read_tree(restore / source.name))
    warnings = []
    try:
        control = command(prefix + [payload['tools']['reader'], '--pgdata=' + str(restore / source.name / cluster_relative)], check=check, timeout=60, warning_sink=warnings)
    except ValueError as error:
        raise ValueError('Restored PostgreSQL control state could not be verified') from error
    values = {line.split(':', 1)[0].strip(): line.split(':', 1)[1].strip() for line in control.splitlines() if ':' in line}
    if warnings or values.get('Database cluster state') != 'shut down' or values.get('Catalog version number') != '202209061':
        raise ValueError('Restored PostgreSQL cluster is not a verified cleanly shut-down version-15 cluster')
    (private / 'restored-control.log').write_text(control)
    progress('Rechecking complete protected source and archive before publication')
    if read_tree(source) != document or digest(archive, check) != archive_sha:
        raise ValueError('Protected source or archive changed during independent verification')
    receipt = dict(intent, scope='protected-postgres15-cold-cluster' if cluster_relative=='.' else 'protected-posix-tree-with-postgres15-cold-cluster', cluster_relative=cluster_relative, sha256=archive_sha, archive_bytes=archive.stat().st_size, files=sum(r['kind'] == 'file' for r in document['records']), bytes=amount, source_retained=True, restored_and_verified=True, clean_shutdown_verified=True, runtime_activation_verified=False, verified_at=time.time(), retirement_authorized=False, space_reclaimed=0, protected_windows_archive_acl=windows_acl_protected, preserve_mixed_ownership=True, ownership_method='privileged exact-owner directory and file capture/restore', limitations=['Clean shutdown verification applies only to the selected PostgreSQL subtree; other application services have not been activated.', 'No original database was started or modified.', 'Raw restored cluster retained for separate isolated-copy recovery testing.', 'Runtime, extension, locale and logical recovery remain unverified.', 'Access times, change times, filesystem flags and dependencies outside this complete cluster are not recovery guarantees.'])
    intent['verified_receipt'] = receipt; store.write_receipt(intent_path, intent)
    with archive.open('rb') as f:os.fsync(f.fileno())
    store.write_receipt(staging / 'receipt.json', receipt)
    check(); publish_directory(staging, destination)
    store.write_receipt(private / 'result.json', receipt)
    store.progress(job['id'], receipt['files'], amount, 'Cold cluster archive independently restored with exact ownership; original cluster retained; runtime trial remains pending')
