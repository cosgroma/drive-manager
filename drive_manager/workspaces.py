"""Additive history safeguards. Full working-tree retirement is a separate workflow."""
from __future__ import annotations
import ctypes
import base64
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid


def command(args, check=lambda: None, timeout=1800, input_text=None, isolated=False, warning_sink=None):
    """Bound output and terminate the entire Git process group on pause/stop."""
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_LAZY_FETCH': '1',
           'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_TERMINAL_PROMPT': '0'}
    if isolated:
        for key in list(env):
            if key.startswith('GIT_CONFIG') or key in ('GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_NAMESPACE','GIT_TEMPLATE_DIR'):
                env.pop(key)
        env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if input_text is not None:
            inp.write(input_text.encode()); inp.seek(0)
        proc = subprocess.Popen(args, stdin=inp, stdout=out, stderr=err, env=env,
                                start_new_session=True)
        began = time.monotonic()
        try:
            while proc.poll() is None:
                check()
                if time.monotonic() - began > timeout:
                    raise ValueError('Git operation timed out; source preserved')
                time.sleep(.25)
            check()
            if out.seek(0, os.SEEK_END) > 8 * 1024**2:
                raise ValueError('Git metadata output exceeded the bounded capture; snapshot not published')
            out.seek(0); err.seek(0)
            if warning_sink is not None:
                if err.seek(0,os.SEEK_END)>8*1024**2:raise ValueError('Git warning output exceeded bounded capture; source retained')
                err.seek(0)
            stdout, stderr = out.read(8 * 1024**2).decode(errors='replace'), err.read(8*1024**2 if warning_sink is not None else 8192).decode(errors='replace')
            if proc.returncode:
                raise ValueError('Git operation failed: ' + stderr[-2000:].strip())
            if warning_sink is not None:warning_sink.extend(sorted(line for line in stderr.splitlines() if line.strip()))
            return stdout
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()


def git(path, *args, **kwargs):
    hooks=['-c','core.hooksPath='+os.devnull] if kwargs.get('isolated') else []
    return command(['git', '-c', 'safe.directory=' + str(path), '-c', 'core.fsmonitor=false',
                    *hooks,'-C', str(path), *args], **kwargs)


def refs(path, check=lambda: None):
    values = {}
    for line in git(path, 'for-each-ref', '--format=%(objectname) %(refname)', check=check).splitlines():
        oid, name = line.split(' ', 1)
        values[name] = oid
    values['HEAD'] = git(path, 'rev-parse', '--verify', 'HEAD', check=check).strip()
    if not values['HEAD']:
        raise ValueError('Repository has no readable HEAD')
    return values


def ref_digest(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def history_state(path,check=lambda:None,isolated=False,warning_sink=None):
    """Record readable ref tips and HEAD's meaning without repairing the source."""
    values={}
    for line in git(path,'for-each-ref','--format=%(objectname) %(refname)',check=check,isolated=isolated,warning_sink=warning_sink).splitlines():
        oid,name=line.split(' ',1);values[name]=oid
    try:symbolic=git(path,'symbolic-ref','--quiet','--no-recurse','HEAD',check=check,isolated=isolated).strip()
    except ValueError:symbolic=None  # Detached HEAD is legitimate.
    try:head=git(path,'rev-parse','--verify','HEAD',check=check,isolated=isolated).strip()
    except ValueError:
        if not values or not symbolic:raise ValueError('No readable HEAD, or an invalid HEAD with no preservable symbolic state; full-file preservation remains required')
        return values,{'kind':'unresolved','symbolic_ref':symbolic}
    if not head:raise ValueError('Repository has no readable HEAD')
    values['HEAD']=head
    return values,{'kind':'resolved','oid':head,'symbolic_ref':symbolic}


def workspace_source(store, source):
    """Allow canonical workspace roots and narrowly derived read-only dependencies."""
    path = Path(source)
    primary = Path.home() / 'workspace'
    if path == primary or primary in path.parents:
        if not path.is_absolute() or '..' in path.parts or path.resolve() != path:
            raise ValueError('Workspace source is redirected or invalid')
        if not path.is_dir():
            raise ValueError('Workspace source no longer exists')
        return path, Path.home()
    try:
        return store.safe_path(source)
    except ValueError:
        pass
    # Registry-active external home checkouts are read-only sources only.
    # This does not add destinations or permit generic transfers under HOME.
    if Path.home() in path.parents:
        from .registry import read_registry
        try:
            _, _, metadata = read_registry()
        except (OSError, ValueError) as error:
            raise ValueError('An original valid registry is required for an external home source') from error
        allowed = any(project.get('status') == 'active' and
                      any(w.get('status') == 'active' and w.get('path') == str(path)
                          for w in project.get('worktrees', []))
                      for project in metadata.get('externalProjects', []))
        if allowed:
            if not path.is_absolute() or '..' in path.parts or path.resolve() != path or not path.is_dir():
                raise ValueError('Registered external workspace source is redirected or invalid')
            gitdir = path / '.git'
            if gitdir.is_symlink() or not gitdir.is_dir():
                raise ValueError('External shared or redirected Git storage needs a coordinated preservation plan')
            if (gitdir / 'objects/info/alternates').exists():
                raise ValueError('External Git alternates need a dependency preservation plan')
            if Path(git(path, 'rev-parse', '--show-toplevel', isolated=True).strip()) != path:
                raise ValueError('External source must be its own Git worktree root')
            if Path(git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir', isolated=True).strip()) != gitdir:
                raise ValueError('External Git storage is not self-contained')
            return path, Path.home()
        # A versioned pyenv prefix is a read-only dependency only while an
        # active registered external checkout directly references its Python.
        # Never admit all of .pyenv, neighboring versions, or child paths.
        import re
        versions = Path.home() / '.pyenv/versions'
        if path.parent == versions and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', path.name):
            if path.resolve() != path or not path.is_dir():
                raise ValueError('Python runtime prefix is redirected or missing')
            version = '.'.join(path.name.split('.')[:2])
            binary = path / 'bin' / ('python' + version)
            stdlib = path / 'lib' / ('python' + version) / 'os.py'
            if binary.resolve() != binary or not binary.is_file() or stdlib.resolve() != stdlib or not stdlib.is_file():
                raise ValueError('A self-contained Python runtime layout is required')
            with binary.open('rb') as handle:
                if handle.read(4) != b'\x7fELF':
                    raise ValueError('A native Python interpreter is required')
            for project in metadata.get('externalProjects', []):
                if project.get('status') != 'active': continue
                for worktree in project.get('worktrees', []):
                    if worktree.get('status') != 'active': continue
                    checkout = Path(worktree.get('path', ''))
                    if checkout == path or Path.home() not in checkout.parents: continue
                    # Require the existing exact-root source gate first. An
                    # unregistered or redirected checkout cannot grant access.
                    try: workspace_source(store, str(checkout))
                    except (OSError, ValueError): continue
                    link = checkout / '.venv/bin/python'
                    if link.parent.resolve() == link.parent and link.is_symlink() and link.resolve() == binary:
                        return path, Path.home()
    return store.safe_path(source)


def enqueue_history(store, source, archive_root=None):
    src, root = workspace_source(store, source)
    if not src.is_dir(): raise ValueError('Choose a repository directory')
    # Confirm a real repository boundary rather than inheriting a parent checkout.
    bare = git(src, 'rev-parse', '--is-bare-repository', timeout=30).strip() == 'true'
    if not bare and Path(git(src, 'rev-parse', '--show-toplevel', timeout=30).strip()) != src:
        raise ValueError('Choose the repository root')
    if bare and Path(git(src, 'rev-parse', '--absolute-git-dir', timeout=30).strip()) != src:
        raise ValueError('Choose the bare repository root')
    target_root = Path(archive_root) if archive_root else store.roots[0] / 'archive/workspaces'
    target_root, _ = store.safe_path(str(target_root), True)
    if src == target_root or src in target_root.parents or target_root in src.parents:
        raise ValueError('Archive and source trees must be independent')
    # Repeated queue requests do not generate redundant pending snapshots.
    with store.db() as db:
        row = db.execute("SELECT id FROM jobs WHERE kind='workspace_history' AND path=? AND status IN ('pending','running','paused')", (str(src),)).fetchone()
        if row: return row[0]
    ident = uuid.uuid4().hex
    origin = Path('home') / src.relative_to(root) if root == Path.home() else Path(root.name) / src.relative_to(root)
    destination = target_root / origin / 'history' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + ident[:12])
    with store.db() as db:
        db.execute("INSERT INTO jobs(id,kind,path,status,payload,created,updated) VALUES(?,'workspace_history',?,'pending',?,?,?)",
                   (ident, str(src), json.dumps({'destination': str(destination)}), time.time(), time.time()))
        db.execute('INSERT INTO workspace_archives(job_id,source,destination,updated) VALUES(?,?,?,?)',
                   (ident, str(src), str(destination), time.time()))
    store.event('Additive Git history safeguard queued; original workspace stays in place: ' + str(src), ident)
    return ident


def publish_directory(staging, destination):
    # Linux renameat2 gives an atomic publish that refuses even an empty destination.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        if code in (errno.EINVAL, errno.ENOTSUP) and str(staging).startswith('/mnt/'):
            # WSL's 9P mount does not implement RENAME_NOREPLACE. Native Windows
            # Directory.Move is a same-volume, atomic rename that refuses collisions.
            from .models import windows_path
            payload = base64.b64encode(json.dumps({'source': windows_path(staging),
                                                  'destination': windows_path(destination)}).encode()).decode()
            script = "$p=([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "')) | ConvertFrom-Json); try {[IO.Directory]::Move($p.source,$p.destination);exit 0} catch {if([IO.Directory]::Exists($p.destination) -or [IO.File]::Exists($p.destination)){exit 17};exit 1}"
            result = subprocess.run(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
                                     '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, timeout=30)
            if result.returncode == 0: return
            if result.returncode == 17: raise FileExistsError(str(destination))
        raise OSError(code, os.strerror(code), str(destination))


def catalog(store):
    with store.db() as db:
        rows = db.execute('SELECT a.*,j.status,j.message FROM workspace_archives a JOIN jobs j ON j.id=a.job_id ORDER BY a.updated DESC').fetchall()
    return [dict(r, receipt=json.loads(r['receipt']) if r['receipt'] else None) for r in rows]


def run_history(store, job):
    from .core import digest
    source, _ = workspace_source(store, job['path'])
    destination, _ = store.safe_path(json.loads(job['payload'])['destination'], True)
    last_capacity = [0.0]
    def check():
        store.check(job['id'])
        if destination.parent.exists() and time.monotonic() - last_capacity[0] > 5:
            last_capacity[0] = time.monotonic()
            if shutil.disk_usage(destination.parent).free < int(store.setting('reserve')) + 256 * 1024**2:
                raise ValueError('Archive staging reached the capacity reserve; original source preserved')
    def progress(message): store.progress(job['id'], 0, 0, message)
    def record(receipt):
        with store.db() as db:
            db.execute('UPDATE workspace_archives SET receipt=?,updated=? WHERE job_id=?',
                       (json.dumps(receipt), time.time(), job['id']))
        store.write_receipt(store.state / 'workspace-receipts' / (job['id'] + '.json'), receipt)
        store.progress(job['id'], len(receipt['refs']), receipt['bytes'],
                       'History restored and verified; working files, ignored data, LFS and reflogs still require archival')
    if destination.exists():
        # Reconcile a crash after atomic publication and before the catalog commit.
        receipt = json.loads((destination / 'receipt.json').read_text())
        if (receipt['job'] != job['id'] or receipt['source'] != str(source) or
            receipt['destination'] != str(destination) or receipt['scope'] != 'git-history-only' or
            digest(destination / 'history.bundle', check) != receipt['sha256']):
            raise ValueError('Existing archive does not match this job; nothing overwritten')
        if receipt.get('head_state'):
            intent_path=store.state/'workspace-history-intents'/(job['id']+'.json')
            if not intent_path.exists():raise ValueError('Published HEAD metadata lacks its private capture intent; archive retained')
            intent=json.loads(intent_path.read_text())
            if any(intent.get(key)!=receipt.get(key) for key in ('job','source','destination','object_format','refs','head_state','source_ref_warnings')):
                raise ValueError('Published history metadata differs from its private capture intent; archive retained')
            if intent.get('verified_bundle_sha256')!=receipt['sha256']:
                raise ValueError('Published bundle differs from its private verified digest; archive retained')
        record(receipt); return
    check()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < int(store.setting('reserve')) + 4 * 1024**3:
        raise ValueError('Archive drive needs reserve plus 4 GiB staging headroom')
    staging = destination.parent / ('.pending-' + job['id'])
    if staging.is_symlink(): raise ValueError('Staging directory was redirected')
    if staging.exists():
        # A failed bundle can contain an older source version. Retain it rather
        # than assume a later source still has every captured object.
        intent_path=store.state/'workspace-history-intents'/(job['id']+'.json')
        if intent_path.exists():
            store.write_receipt(staging/'capture-intent.json',json.loads(intent_path.read_text()))
        previous=destination.parent/('.retained-attempt-'+job['id']+'-'+uuid.uuid4().hex[:12])
        publish_directory(staging,previous)
        store.event('Previous unverified history attempt retained: '+str(previous),job['id'])
    staging.mkdir(mode=0o700)
    try:
        progress('Reading historical refs; originals remain untouched')
        source_warnings=[]
        before,head_state = history_state(source, check,warning_sink=source_warnings)
        object_format = git(source, 'rev-parse', '--show-object-format', check=check).strip()
        store.write_receipt(store.state/'workspace-history-intents'/(job['id']+'.json'),
                            {'job':job['id'],'source':str(source),'destination':str(destination),'object_format':object_format,
                             'refs':before,'head_state':head_state,'source_ref_warnings':source_warnings,'captured_at':time.time()})
        bundle = staging / 'history.bundle'
        progress('Creating self-contained Git history bundle')
        git(source, 'bundle', 'create', str(bundle), '--stdin',input_text='\n'.join(before)+'\n',check=check)
        after_warnings=[]
        if history_state(source, check,warning_sink=after_warnings) != (before,head_state) or after_warnings!=source_warnings:
            raise ValueError('Repository refs changed during snapshot; retry when stable')
        bundle_refs = {}
        for line in git(source, 'bundle', 'list-heads', str(bundle), check=check).splitlines():
            oid, name = line.split(' ', 1); bundle_refs[name] = oid
        if any(bundle_refs.get(name) != oid for name, oid in before.items()):
            raise ValueError('Bundle did not retain every recorded ref and HEAD')
        progress('Restoring archive into an independent empty repository')
        restore_parent=store.state/'workspace-restore-checks';restore_parent.mkdir(mode=0o700,exist_ok=True)
        if shutil.disk_usage(restore_parent).free < int(store.setting('reserve'))+2*bundle.stat().st_size+256*1024**2:
            raise ValueError('Local independent restore check needs additional staging headroom; source retained')
        with tempfile.TemporaryDirectory(prefix='history-',dir=restore_parent) as temporary:
            restore=Path(temporary)/'restore.git';template=Path(temporary)/'empty-template';template.mkdir()
            command(['git','init','--bare','--template='+str(template),'--object-format='+object_format,str(restore)],check=check,isolated=True)
            git(restore, 'bundle', 'verify', str(bundle), check=check,isolated=True)
            git(restore, 'bundle', 'unbundle', str(bundle), check=check,isolated=True)
            updates = ''.join('update ' + name + ' ' + oid + '\n' for name, oid in bundle_refs.items() if name != 'HEAD')
            git(restore, 'update-ref', '--no-deref', '--stdin', input_text=updates, check=check,isolated=True)
            if head_state['symbolic_ref']:
                git(restore,'symbolic-ref','HEAD',head_state['symbolic_ref'],check=check,isolated=True)
            else:git(restore,'update-ref','--no-deref','HEAD',before['HEAD'],check=check,isolated=True)
            git(restore, 'fsck', '--full', '--no-reflogs', check=check,isolated=True)
            if history_state(restore,check,isolated=True)!=(before,head_state):
                raise ValueError('Restored refs or symbolic HEAD differ from the source snapshot')
        progress('Verifying bundle SHA-256 and final source-ref stability')
        sha = digest(bundle, check)
        after_warnings=[]
        if history_state(source, check,warning_sink=after_warnings) != (before,head_state) or after_warnings!=source_warnings:
            raise ValueError('Repository refs changed during verification; retry when stable')
        intent_path=store.state/'workspace-history-intents'/(job['id']+'.json')
        intent=json.loads(intent_path.read_text());intent['verified_bundle_sha256']=sha;intent['verified_at']=time.time()
        store.write_receipt(intent_path,intent)
        receipt = {'job': job['id'], 'source': str(source), 'destination': str(destination),
                   'scope': 'git-history-only', 'object_format': object_format, 'source_retained': True, 'space_reclaimed': 0,
                   'sha256': sha, 'bytes': bundle.stat().st_size, 'refs': before,'head_state':head_state,'source_ref_warnings':source_warnings,
                   'bundle_refs': bundle_refs, 'ref_digest': ref_digest(before), 'restored_and_fsck_verified': True,
                   'verified_at': time.time(), 'not_preserved': ['working-tree files', 'ignored and untracked files','malformed or unreadable raw ref metadata (source unchanged)',
                   'LFS object payloads', 'reflog-only and dangling objects', 'hooks and repository configuration',
                   'submodule repositories (each requires its own snapshot)']}
        with bundle.open('rb') as handle: os.fsync(handle.fileno())
        store.write_receipt(staging / 'receipt.json', receipt)
        check()
        publish_directory(staging, destination)
        record(receipt)
    except BaseException:
        # Retain generated partial artifacts for inspection; retry recreates its own staging tree.
        raise
