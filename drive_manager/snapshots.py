"""Additive POSIX full-file archives, verified by an independent restoration."""
from __future__ import annotations

import hashlib
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
from .workspaces import command, publish_directory, workspace_source


def inputs(store, identifiers, preserve_mixed_ownership=False, materialize_external_hardlinks=False):
    if type(materialize_external_hardlinks) is not bool:
        raise ValueError("External hardlink mode must be a boolean")
    if type(preserve_mixed_ownership) is not bool:
        raise ValueError("Mixed ownership mode must be a boolean")
    if preserve_mixed_ownership:
        command(["sudo", "-n", "--", "true"], timeout=10)
    if (not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 8
            or any(not isinstance(i, str) for i in identifiers) or len(set(identifiers)) != len(identifiers)):
        raise ValueError('Choose one to eight distinct completed manifests')
    result = []
    for ident in identifiers:
        with store.db() as db:
            row = db.execute('SELECT a.*,j.status FROM workspace_manifests a JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?', (ident,)).fetchone()
        if row is None or row['status'] != 'completed' or not row['result']:
            raise ValueError('Full-file archives require completed manifests')
        receipt = json.loads(row['result'])
        source, _ = workspace_source(store, row['source'])
        if str(source).startswith('/mnt/') or receipt.get('native_metadata') is not False:
            raise ValueError('This archive format supports Linux POSIX sources; Windows streams need a native backup plan')
        entries = {}
        sha = hashlib.sha256()
        path = store.state / 'workspace-manifests' / ident / 'manifest.sqlite3'
        with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
            for rel, raw, signature, digest in db.execute('SELECT relative,native,signature,sha256 FROM entries ORDER BY relative'):
                native = json.loads(raw); sig = json.loads(signature) if signature else None
                if Path(rel).is_absolute() or '..' in Path(rel).parts or native['kind'] not in ('file', 'dir', 'link') or not sig:
                    raise ValueError('Unsupported or invalid manifest entry; source retained')
                if native['kind'] == 'file' and (not digest or sig['nlink'] < 1 or (sig['nlink'] != 1 and not materialize_external_hardlinks)):
                    raise ValueError('Unhashed or hardlinked files need a separate preservation plan')
                if sig['uid'] != os.getuid() or sig['gid'] != os.getgid():
                    if not preserve_mixed_ownership:
                        raise ValueError('Mixed ownership needs a privileged preservation plan')
                    if native['kind'] != 'file':
                        raise ValueError('Mixed-owner directories or links need a separate preservation plan')
                if preserve_mixed_ownership and (sig['mode'] & (stat.S_ISUID | stat.S_ISGID) or 'security.capability' in native.get('xattrs', {})):
                    raise ValueError('Privileged executable metadata needs a separate preservation plan')
                sha.update(manifests.canonical(dict(relative=rel, native=native, signature=sig, sha256=digest)).encode() + b'\n')
                entries[rel] = (native, sig, digest)
        if (receipt.get('job') != ident or receipt.get('source') != str(source) or receipt.get('scope') != 'full-visible-tree-manifest'
                or len(entries) != receipt['entries'] or '.' not in entries or sha.hexdigest() != receipt['sha256']):
            raise ValueError('Manifest seal differs from its completed receipt')
        result.append(dict(job=ident, source=source, receipt=receipt, entries=entries, materialize_external_hardlinks=materialize_external_hardlinks))
    parents = {item['source'].parent for item in result}
    if len(parents) != 1 or len({item['source'].name for item in result}) != len(result):
        raise ValueError('Coordinated archives require sibling source folders')
    if materialize_external_hardlinks:
        seen={}
        for item in result:
            for rel,(native,sig,sha) in item['entries'].items():
                if native['kind']!='file' or sig['nlink']==1:continue
                key=(sig['device'],sig['inode'])
                if key in seen:raise ValueError('Internal hardlink groups need a topology-preserving plan')
                seen[key]=(str(item['source']),rel)
    return result


def verify_tree(item, base, check, *, restored=False):
    """Compare all members, metadata and identities; hash restored file payloads."""
    from .core import digest
    expected = item['entries']; seen = set()
    with tempfile.TemporaryDirectory() as temporary:
        listing = Path(temporary) / 'tree.jsonl'
        manifests.posix_tree(base, listing, check)
        for rel, native in manifests.entries(listing):
            check()
            if rel not in expected or native != expected[rel][0]:
                raise ValueError('Tree membership or metadata differs from the full-file manifest: ' + rel)
            sig = manifests.file_signature(base / rel); recorded = expected[rel][1]
            keys = ('mode', 'uid', 'gid', 'nlink', 'size', 'mtime_ns') if restored else tuple(recorded)
            # Directory size is a filesystem allocation detail, not portable metadata.
            if restored and native['kind'] == 'dir': keys = tuple(k for k in keys if k != 'size')
            if restored and item.get('materialize_external_hardlinks') and native['kind']=='file' and recorded['nlink']>1:
                recorded={**recorded,'nlink':1}
            if any(sig[k] != recorded[k] for k in keys):
                raise ValueError('File identity or permissions differ from the full-file manifest: ' + rel)
            if restored and native['kind'] == 'file' and digest(base / rel, check) != expected[rel][2]:
                raise ValueError('Restored file payload differs: ' + rel)
            seen.add(rel)
    if seen != set(expected): raise ValueError('Full-file snapshot omitted source entries')


def enqueue(store, identifiers, archive_root=None, preserve_mixed_ownership=False, materialize_external_hardlinks=False):
    items = inputs(store, identifiers, preserve_mixed_ownership, materialize_external_hardlinks)
    root, _ = store.safe_path(archive_root or '/mnt/h/archive/workspaces', True)
    if any(root == i['source'] or i['source'] in root.parents or root in i['source'].parents for i in items):
        raise ValueError('Archive and source trees must be separate')
    ident = uuid.uuid4().hex
    destination = root / 'posix-snapshots' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + ident[:12])
    payload = dict(manifests=identifiers, destination=str(destination), manifest_seals=[i['receipt']['sha256'] for i in items], preserve_mixed_ownership=preserve_mixed_ownership, materialize_external_hardlinks=materialize_external_hardlinks)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for previous in db.execute("SELECT id,payload FROM jobs WHERE kind='workspace_snapshot' AND status IN ('pending','running','paused')"):
            old=json.loads(previous['payload'])
            if set(old['manifests'])==set(identifiers) and Path(old['destination']).parent==destination.parent and old.get('preserve_mixed_ownership',False)==preserve_mixed_ownership and old.get('materialize_external_hardlinks',False)==materialize_external_hardlinks:
                return previous['id']
        db.execute("INSERT INTO jobs(id,kind,path,status,payload,created,updated) VALUES(?,'workspace_snapshot',?,'pending',?,?,?)",
                   (ident, str(items[0]['source']), json.dumps(payload), time.time(), time.time()))
    store.event('Additive full-file snapshot queued; all source folders stay in place: ' + ', '.join(str(i['source']) for i in items), ident)
    return ident


def catalog(store):
    with store.db() as db:
        rows = db.execute("SELECT * FROM jobs WHERE kind='workspace_snapshot' ORDER BY created DESC").fetchall()
    result = []
    for row in rows:
        path = store.state / 'workspace-snapshots' / row['id'] / 'result.json'
        payload = json.loads(row['payload'])
        with store.db() as db:
            sources = [r[0] for ident in payload['manifests'] for r in db.execute('SELECT source FROM workspace_manifests WHERE job_id=?', (ident,))]
        if payload.get('protected_postgres'): sources = [row['path']]
        result.append(dict(row, sources=sources, destination=payload['destination'], receipt=json.loads(path.read_text()) if path.exists() else None))
    return result


def audit_tar(path, items, check):
    """Reject extra members, traversal, devices and links absent from sealed input."""
    expected = {}
    for item in items:
        for rel, entry in item['entries'].items():
            name = item['source'].name if rel == '.' else item['source'].name + '/' + rel
            expected[name] = entry
    seen = set()
    with tarfile.open(path, 'r|') as archive:
        for member in archive:
            check(); name = member.name.rstrip('/')
            if name not in expected or name in seen or Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Unexpected or repeated archive member')
            native, sig, digest = expected[name]
            kind = 'file' if member.isfile() else 'dir' if member.isdir() else 'link' if member.issym() else 'unsupported'
            if kind != native['kind'] or member.uid != sig['uid'] or member.gid != sig['gid'] or member.mode != stat.S_IMODE(sig['mode']):
                raise ValueError('Archive member type or permissions differ: ' + name)
            if kind == 'file':
                if member.size != native['size']: raise ValueError('Archive member size differs: ' + name)
                sha = hashlib.sha256()
                with archive.extractfile(member) as handle:
                    while True:
                        check(); block = handle.read(1024 * 1024)
                        if not block: break
                        sha.update(block)
                if sha.hexdigest() != digest: raise ValueError('Archive file payload differs: ' + name)
            if kind == 'link' and member.linkname != native['target']:
                raise ValueError('Archive link target differs: ' + name)
            seen.add(name)
    if seen != set(expected): raise ValueError('Archive is missing required members')


def run(store, job):
    from .core import digest
    if json.loads(job['payload']).get('native_windows_files') is True:
        from .native_files import run as native_run
        return native_run(store, job)
    if json.loads(job['payload']).get('protected_postgres'):
        from .protected_snapshots import run as protected_run
        return protected_run(store, job)
    payload = json.loads(job['payload']); privileged = payload.get('preserve_mixed_ownership', False)
    materialize=payload.get('materialize_external_hardlinks',False)
    items = inputs(store, payload['manifests'], privileged, materialize)
    prefix = ['sudo', '-n', '--'] if privileged else []
    if payload['manifest_seals'] != [i['receipt']['sha256'] for i in items]:
        raise ValueError('Queued full-file manifest seals changed')
    destination, _ = store.safe_path(payload['destination'], True)
    private = store.state / 'workspace-snapshots' / job['id']; private.mkdir(parents=True, exist_ok=True)
    intent_path = private / 'intent.json'
    check = lambda: store.check(job['id'])
    progress = lambda message: store.progress(job['id'], 0, 0, message)
    if destination.exists():
        receipt = json.loads((destination / 'receipt.json').read_text())
        if not intent_path.exists() or receipt != json.loads(intent_path.read_text()).get('verified_receipt'):
            raise ValueError('Published full-file archive lacks matching private verification evidence')
        if digest(destination / 'trees.tar', check) != receipt['sha256']:
            raise ValueError('Published full-file archive digest changed; source retained')
        if receipt.get('materialize_external_hardlinks') and digest(destination/'external-hardlinks.json',check)!=receipt.get('external_hardlink_topology_sha256'):
            raise ValueError('Published external hardlink topology digest changed')
        store.write_receipt(private / 'result.json', receipt); return
    amount = sum(i['receipt']['bytes'] for i in items)
    destination.parent.mkdir(parents=True, exist_ok=True)
    restore_parent = store.state / 'snapshot-restore-checks'; restore_parent.mkdir(exist_ok=True)
    for location in (destination.parent, restore_parent):
        if shutil.disk_usage(location).free < int(store.setting('reserve')) + amount + max(256 * 1024**2, amount // 20):
            raise ValueError('Full-file archive and independent restore require additional capacity above reserve')
    staging = destination.parent / ('.pending-' + job['id'])
    if staging.is_symlink(): raise ValueError('Snapshot staging was redirected')
    if staging.exists():
        previous = destination.parent / ('.retained-attempt-' + job['id'] + '-' + uuid.uuid4().hex[:12])
        if intent_path.exists(): store.write_receipt(staging / 'capture-intent.json', json.loads(intent_path.read_text()))
        publish_directory(staging, previous); store.event('Previous unverified full-file attempt retained: ' + str(previous), job['id'])
    staging.mkdir(mode=0o700)
    from .protected_snapshots import protect_staging
    windows_acl_protected = protect_staging(staging)
    intent = dict(job=job['id'], sources=[str(i['source']) for i in items], destination=str(destination),
                  manifests=payload['manifests'], manifest_seals=payload['manifest_seals'])
    store.write_receipt(intent_path, intent)
    external_links=[];topology_sha=None
    if materialize:
        for item in items:
            for rel,(native,sig,sha) in item['entries'].items():
                if native['kind']=='file' and sig['nlink']>1:
                    external_links.append(dict(source=str(item['source']),relative=rel,device=sig['device'],inode=sig['inode'],original_nlink=sig['nlink'],sha256=sha))
        store.write_receipt(staging/'external-hardlinks.json',dict(files=external_links,scope='Original sharing recorded; outside aliases are not recreated; restored files are independent',source_retained=True))
        topology_sha=digest(staging/'external-hardlinks.json',check)
    progress('Checking sealed source membership and metadata before full-file archival')
    for item in items: verify_tree(item, item['source'], check)
    listing = private / 'members.list'
    with listing.open('wb') as handle:
        for item in items:
            # Punctuation-prefixed files can sort before "." in SQLite. Emit
            # the root directory first so tar can restore its metadata rather
            # than treat it as a pre-existing parent under --keep-old-files.
            for rel in sorted(item['entries'], key=lambda value: (value != '.', value)):
                name = item['source'].name if rel == '.' else item['source'].name + '/' + rel
                handle.write(os.fsencode(name) + b'\0')
    tar = staging / 'trees.tar'; last_capacity = [0.0]
    def capacity_check():
        check()
        if time.monotonic() - last_capacity[0] > 5:
            last_capacity[0] = time.monotonic()
            if any(shutil.disk_usage(location).free < int(store.setting('reserve')) + 64 * 1024**2
                   for location in (destination.parent, restore_parent)):
                raise ValueError('Archive or restore capacity reserve reached; partial attempt retained')
    progress('Copying every selected file, link, Git internal, ACL and extended attribute into a POSIX archive')
    command(prefix + ['tar', '--create', '--file=' + str(tar), '--format=pax', '--acls', '--xattrs', '--xattrs-include=*',
             '--numeric-owner', '--atime-preserve=system', '--no-recursion', '--directory=' + str(items[0]['source'].parent),
             '--null', '--files-from=' + str(listing)] + (['--hard-dereference'] if materialize else []), check=capacity_check, timeout=14400)
    sha = digest(tar, check)
    progress('Auditing archive membership and SHA-256 of every archived file')
    audit_tar(tar, items, check)
    progress('Independently extracting and verifying every file, link, permission and extended attribute')
    with tempfile.TemporaryDirectory(prefix=job['id'] + '-', dir=restore_parent) as temporary:
        restore = Path(temporary)
        command(prefix + ['tar', '--extract', '--file=' + str(tar), '--directory=' + str(restore), '--acls', '--xattrs',
                 '--xattrs-include=*', '--same-permissions', '--numeric-owner', '--keep-old-files', '--delay-directory-restore'] + (['--same-owner'] if privileged else []), check=capacity_check, timeout=14400)
        for item in items: verify_tree(item, restore / item['source'].name, check, restored=True)
    progress('Checking archive digest and final source stability before publication')
    if digest(tar, check) != sha: raise ValueError('Archive changed during recovery verification')
    for item in items: verify_tree(item, item['source'], check)
    if materialize and digest(staging/'external-hardlinks.json',check)!=topology_sha:
        raise ValueError('External hardlink topology changed before publication')
    receipt = dict(intent, scope='full-visible-posix-trees', sha256=sha, archive_bytes=tar.stat().st_size,
                   files=sum(i['receipt']['files'] for i in items), bytes=amount, source_retained=True,
                   restored_and_verified=True, verified_at=time.time(), retirement_authorized=False, space_reclaimed=0,
                   materialize_external_hardlinks=materialize, external_hardlink_files=len(external_links),
                   external_hardlink_aliases_not_recreated=sum(r['original_nlink']-1 for r in external_links), external_hardlink_topology_sha256=topology_sha,
                   protected_windows_archive_acl=windows_acl_protected, preserve_mixed_ownership=privileged, ownership_method='privileged capture and exact-owner restore' if privileged else 'current-user capture and restore',
                   limitations=['Symlink targets are preserved; external target data is not followed.',
                                'A coordinated Git worktree activation/repair may still be needed after recovery to a different location.',
                                'Filesystem flags, access times and change times are outside the recorded recovery comparison.',
                                'This archive does not prove a complete dependency closure or authorize retiring any source.'])
    if materialize:receipt['limitations'].append('External hardlink sharing is recorded but not recreated outside the selected source trees; restored files are independent and all original aliases must be retained.')
    intent['verified_receipt'] = receipt; store.write_receipt(intent_path, intent)
    with tar.open('rb') as handle: os.fsync(handle.fileno())
    store.write_receipt(staging / 'receipt.json', receipt)
    check(); publish_directory(staging, destination)
    store.write_receipt(private / 'result.json', receipt)
    store.progress(job['id'], receipt['files'], amount, 'Full-file archive independently restored and verified; all original sources retained')
