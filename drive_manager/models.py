"""Verified model routing: existing references stay valid, existing SSD copies serve reads."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from .core import digest, signature


def powershell(script, data):
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    prefix = "$ErrorActionPreference='Stop'; $x=ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'))); "
    result = subprocess.run(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
                             '-NoProfile', '-NonInteractive', '-Command', prefix + script],
                            capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise ValueError('Windows model routing failed: ' + result.stderr.strip()[:400])
    return result.stdout.strip()


def windows_path(path):
    # wslpath follows junctions. Native reparse-point operations must address the
    # original lexical path, otherwise they would inspect/remove the SSD target.
    text = str(path)
    if len(text) >= 6 and text.startswith('/mnt/') and text[5].isalpha() and (len(text) == 6 or text[6] == '/'):
        return text[5].upper() + ':\\' + text[7:].replace('/', '\\')
    return subprocess.run(['wslpath', '-w', str(path)], capture_output=True, text=True, check=True).stdout.strip()


def manifest(path):
    path = Path(path)
    if not path.is_dir() or path.is_symlink():
        raise ValueError('Model routing requires a real model folder')
    result = {}
    for base, dirs, files in os.walk(path, followlinks=False):
        for directory in dirs:
            if directory == '.drive-manager-recovery' or (Path(base) / directory).is_symlink():
                raise ValueError('Nested links and recovery folders cannot be routed')
        for name in files:
            p = Path(base) / name
            result[str(p.relative_to(path))] = signature(p)
    if not result or not any(name.lower().endswith('.gguf') for name in result):
        raise ValueError('Only complete GGUF model repositories are eligible for this routing policy')
    return result


def compatible(source, destination):
    return source.keys() == destination.keys() and all(source[k]['size'] == destination[k]['size'] for k in source)


def roots(store):
    with store.db() as db:
        row = db.execute("SELECT value FROM settings WHERE key='model_roots'").fetchone()
    return [Path(p) for p in json.loads(row[0])] if row else [Path('/mnt/d/models'), Path('/mnt/f/models')]


def validate_paths(store, source, destination):
    a, b = roots(store)
    src, dst = Path(source), Path(destination)
    # One publisher/repository mapping. Preserve all existing relative file references.
    if a not in src.parents or b not in dst.parents or src.relative_to(a) != dst.relative_to(b) or len(src.relative_to(a).parts) != 2:
        raise ValueError('Model routing must map the same publisher/repository from HDD to SSD')
    store.safe_path(str(src.parent))
    store.safe_path(str(dst))
    return src, dst


def propose(store, source, destination, automatic=False, reason='Prefer verified SSD model files while preserving existing application paths'):
    src, dst = validate_paths(store, source, destination)
    store.safe_path(str(src))
    left, right = manifest(src), manifest(dst)
    if not compatible(left, right):
        raise ValueError('Model folders have different contents or file sizes; preserve both for review')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute("SELECT id FROM candidates WHERE source=? AND destination=? "
                              "AND status IN ('review','queued')", (str(src), str(dst))).fetchone()
        if existing:
            return existing[0]
        ident = uuid.uuid4().hex
        db.execute("INSERT INTO candidates(id,kind,source,destination,snapshot,size,reason,confidence,created,updated) "
                   "VALUES(?,'model_route',?,?,?,?,?,?,?,?)",
                   (ident, str(src), str(dst), json.dumps({'source': left, 'destination': right}),
                    sum(x['size'] for x in left.values()), reason,
                    'policy' if automatic else 'review', time.time(), time.time()))
    if automatic:
        store.approve([ident], policy=True, policy_id='existing-model-ssd-route')
    return ident


def validate(store, candidate):
    src, dst = validate_paths(store, candidate['source'], candidate['destination'])
    store.safe_path(str(src))
    snap = json.loads(candidate['snapshot'])
    if manifest(src) != snap['source'] or manifest(dst) != snap['destination']:
        raise ValueError('Model folder changed since proposal; create a fresh review')


def create_junction(source, destination):
    if str(source).startswith('/mnt/'):
        powershell('New-Item -ItemType Junction -Path $x.source -Target $x.destination | Out-Null',
                   {'source': windows_path(source), 'destination': windows_path(destination)})
    else:
        source.symlink_to(destination, target_is_directory=True)


def is_junction(source, destination):
    if str(source).startswith('/mnt/'):
        target = powershell("$p=Get-Item -LiteralPath $x.source -Force; if($p.LinkType -ne 'Junction'){exit 2}; $p.Target | Select-Object -First 1",
                            {'source': windows_path(source)})
        return target.replace('\\', '/').rstrip('/').casefold() == windows_path(destination).replace('\\', '/').rstrip('/').casefold()
    return source.is_symlink() and source.resolve() == destination.resolve()


def app_idle():
    lms = '/mnt/c/Users/cosgroma/.cache/lm-studio/bin/lms.exe'
    result = subprocess.run([lms, 'ps', '--json'], capture_output=True, text=True, timeout=40)
    if result.returncode or json.loads(result.stdout):
        raise ValueError('Model routing is held until LM Studio has no loaded models')
    count = powershell("@(Get-CimInstance Win32_Process | Where-Object {$_.Name -match 'ComfyUI' -or ($_.Name -match 'python' -and $_.CommandLine -match 'ComfyUI')}).Count", {})
    if count != '0':
        raise ValueError('Close ComfyUI before changing shared model folder routing')


def recovery_location(store, source, job):
    root = store.safe_path(str(source.parent))[1]
    result = root / '.drive-manager-recovery' / 'model-routes' / job / source.relative_to(roots(store)[0])
    current = result
    while current != root:
        if current.is_symlink():
            raise ValueError('Model recovery storage is redirected')
        current = current.parent
    return result


def run(store, job, candidate):
    src, dst = validate_paths(store, candidate['source'], candidate['destination'])
    snap = json.loads(candidate['snapshot'])
    recovery = recovery_location(store, src, job['id'])
    receipt = store.state / 'model-routes' / (job['id'] + '.json')
    data = json.loads(receipt.read_text()) if receipt.exists() else None
    check = lambda: store.check(job['id'])
    # Reconcile a crash after creating the junction, before the DB commit.
    if recovery.exists() and src.exists():
        if not data or not is_junction(src, dst):
            raise ValueError('Model route recovery found an unexpected existing source')
        left = recovery
    elif recovery.exists() and not src.exists():
        if not data:
            raise ValueError('Model recovery has no durable receipt')
        left = recovery
    else:
        validate(store, candidate)
        left = src
    if manifest(left) != snap['source'] or manifest(dst) != snap['destination']:
        raise ValueError('Model contents changed; routing stopped with originals retained')
    hashes = {}
    for index, name in enumerate(sorted(snap['source'])):
        check()
        store.progress(job['id'], index, sum(snap['source'][n]['size'] for n in hashes), 'Verifying identical HDD and SSD model files: ' + name)
        a, b = left / name, dst / name
        if store.in_use(a):
            raise ValueError('Model file is in use; routing held')
        h = digest(a, check)
        if digest(b, check) != h:
            raise ValueError('Model file contents differ; both versions preserved for review')
        hashes[name] = h
    if manifest(left) != snap['source'] or manifest(dst) != snap['destination']:
        raise ValueError('Model folder changed during verification')
    if str(src).startswith('/mnt/'):
        app_idle()
    for name in hashes:
        if store.in_use(left / name) or store.in_use(dst / name):
            raise ValueError('Model file became active; routing held')
    check()
    if manifest(left) != snap['source'] or manifest(dst) != snap['destination']:
        raise ValueError('Model folder changed immediately before routing')
    if not data:
        data = {'job': job['id'], 'source': str(src), 'destination': str(dst),
                'recovery': str(recovery), 'hashes': hashes, 'snapshot': snap,
                'phase': 'verified', 'at': time.time()}
        store.write_receipt(receipt, data)
    if left == src:
        recovery.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, recovery)
    if not src.exists():
        try:
            create_junction(src, dst)
        except Exception:
            if not src.exists():
                os.rename(recovery, src)
            raise
    if not is_junction(src, dst):
        raise ValueError('New model junction target could not be verified; recovery original retained')
    # Read via the original application path to prove the SSD junction actually serves it.
    for name, expected in hashes.items():
        if digest(src / name, check) != expected:
            raise ValueError('Model read through the application path failed verification')
    data['phase'] = 'routed'
    store.write_receipt(receipt, data)
    store.index_transfer(src, dst, job['id'], remove_source=True, directory=True)
    store.progress(job['id'], len(hashes), candidate['size'], 'Applications keep their existing path; verified model bytes now come from F:')
    with store.db() as db:
        db.execute("UPDATE candidates SET status='completed',updated=? WHERE id=?", (time.time(), candidate['id']))
    store.event(f'Verified SSD model route active: {src} → {dst}; original retained at {recovery}', job['id'])


def migrate_recovery(store):
    """Keep early-version model recovery folders out of applications' recursive indexes."""
    moved = 0
    for receipt in (store.state / 'model-routes').glob('*.json'):
        data = json.loads(receipt.read_text())
        src, _ = validate_paths(store, data['source'], data['destination'])
        old = src.parent / '.drive-manager-recovery' / data['job'] / src.name
        new = recovery_location(store, src, data['job'])
        if data['recovery'] == str(new):
            for empty in [old.parent, old.parent.parent]:
                try:
                    empty.rmdir()
                except OSError:
                    pass
            continue
        if data['recovery'] != str(old) or data['phase'] != 'routed':
            raise ValueError('Unexpected legacy model recovery receipt')
        existing = old if old.exists() else new
        if manifest(existing) != data['snapshot']['source']:
            raise ValueError('Legacy model recovery changed; retained for review')
        for name, expected in data['hashes'].items():
            if store.in_use(existing / name) or digest(existing / name) != expected:
                raise ValueError('Legacy recovery is active or changed; retained for review')
        data['recovery_next'] = str(new)
        store.write_receipt(receipt, data)
        if old.exists():
            if new.exists():
                raise ValueError('Both legacy and new recovery paths exist')
            new.parent.mkdir(parents=True, exist_ok=True)
            os.rename(old, new)
        data['recovery'] = str(new)
        del data['recovery_next']
        store.write_receipt(receipt, data)
        store.event('Model recovery retained outside the application model library: ' + str(new), data['job'])
        moved += 1
    return moved


def propose_used(store, automatic_limit=2 * 1024**3):
    history = Path('/mnt/c/Users/cosgroma/.cache/lm-studio/.internal/model-data.json')
    if not history.exists():
        return []
    data = json.loads(history.read_text()).get('json', [])
    a, b = roots(store)
    results = []
    seen = set()
    for name, info in sorted(data, key=lambda item: item[1].get('lastLoadedTimestamp', 0), reverse=True):
        relative = Path(name)
        if not info.get('lastLoadedTimestamp') or not name.lower().endswith('.gguf') or len(relative.parts) != 3:
            continue
        repo = relative.parent
        with store.db() as db:
            existing = db.execute("SELECT id FROM candidates WHERE source=? AND destination=?",
                                  (str(a / repo), str(b / repo))).fetchone()
        if existing:
            continue
        if repo in seen or not (a / repo).is_dir() or not (b / repo).is_dir() or (a / repo).is_symlink():
            continue
        seen.add(repo)
        try:
            total = sum(s['size'] for s in manifest(a / repo).values())
            results.append(propose(store, str(a / repo), str(b / repo), total <= automatic_limit,
                                   'LM Studio load history confirms this model was used. Verify both existing copies, '
                                   'then route the original path to F: while retaining the HDD original. '
                                   + ('Small-repository automatic policy.' if total <= automatic_limit else 'Large-model verification requires your approval.')))
        except (OSError, ValueError) as exc:
            store.record_error(None, str(a / repo), str(exc))
    return results


def propose_missing(store, history=None):
    """Prepare reviewed copies for used models absent from the SSD; never auto-copy."""
    history = Path(history or '/mnt/c/Users/cosgroma/.cache/lm-studio/.internal/model-data.json')
    if not history.exists():
        return []
    a, b = roots(store)
    results, seen = [], set()
    for name, info in json.loads(history.read_text()).get('json', []):
        relative = Path(name)
        if not info.get('lastLoadedTimestamp') or not name.lower().endswith('.gguf') or len(relative.parts) != 3:
            continue
        repo = relative.parent
        if repo in seen or not (a / repo).is_dir() or (a / repo).is_symlink():
            continue
        seen.add(repo)
        try:
            for child in manifest(a / repo):
                source, target = a / repo / child, b / repo / child
                if target.exists():
                    continue
                with store.db() as db:
                    existing = db.execute('SELECT id FROM candidates WHERE source=? AND destination=?',
                                          (str(source), str(target))).fetchone()
                if existing:
                    continue
                results.append(store.propose(str(source), str(target), 'copy',
                    'Used model file is missing on F:. Copy and verify it while retaining the HDD source. '
                    'Execution waits for 100 GiB of SSD headroom; complete repository copies can later '
                    'be routed through the existing application path.'))
        except (OSError, ValueError) as exc:
            store.record_error(None, str(a / repo), str(exc))
    return results
