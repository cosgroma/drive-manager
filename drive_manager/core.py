from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import threading
import time
import uuid

GIB = 1024**3
SKIP = {"$RECYCLE.BIN", "System Volume Information", ".drive-manager-recovery"}
GENERATED = {"node_modules", ".pytest_cache", "__pycache__", ".cache"}
PROTECTED = {".vhd", ".vhdx", ".vmdk"}


def sqlite_busy(error):
    if not isinstance(error,sqlite3.OperationalError):return False
    code=getattr(error,'sqlite_errorcode',None)
    return ((code&255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) if code is not None
            else 'locked' in str(error).lower() or 'busy' in str(error).lower())


class Deferred(Exception):
    pass


def signature(path):
    s = Path(path).lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        raise ValueError("Only regular files with one hard link can be transferred")
    return {"size": s.st_size, "mtime_ns": s.st_mtime_ns, "device": s.st_dev,
            "inode": s.st_ino}


def digest(path, check=lambda: None):
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('Hashing requires a regular file')
        while chunk := f.read(8 * 1024**2):
            check()
            h.update(chunk)
    return h.hexdigest()


class Store:
    def __init__(self, state, roots=None, reserve=100 * GIB):
        self.state = Path(state).resolve()
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.dbpath = self.state / "index.sqlite3"
        with self.db() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL, bytes INTEGER DEFAULT 0,
                files INTEGER DEFAULT 0, message TEXT DEFAULT '', created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS directories(
                job_id TEXT, path TEXT, depth INTEGER, done INTEGER DEFAULT 0,
                PRIMARY KEY(job_id,path));
            CREATE TABLE IF NOT EXISTS entries(
                path TEXT PRIMARY KEY, root TEXT, parent TEXT, name TEXT, kind TEXT,
                size INTEGER, mtime_ns INTEGER, job_id TEXT, seen REAL);
            CREATE INDEX IF NOT EXISTS entry_parent ON entries(parent);
            CREATE INDEX IF NOT EXISTS entry_size ON entries(size,name);
            CREATE TABLE IF NOT EXISTS candidates(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
                destination TEXT, snapshot TEXT, size INTEGER DEFAULT 0,
                reason TEXT, confidence TEXT DEFAULT 'review', status TEXT DEFAULT 'review',
                job_id TEXT, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS policies(
                id TEXT PRIMARY KEY, source TEXT, destination TEXT, action TEXT,
                automatic INTEGER, references_confirmed INTEGER, created REAL);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, job_id TEXT,
                message TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS errors(
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, path TEXT,
                message TEXT, at REAL);
            CREATE TABLE IF NOT EXISTS schedules(
                path TEXT PRIMARY KEY, depth INTEGER, interval INTEGER, next_run REAL);
            CREATE TABLE IF NOT EXISTS workspace_archives(
                job_id TEXT PRIMARY KEY, source TEXT NOT NULL, destination TEXT NOT NULL,
                receipt TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS workspace_manifests(
                job_id TEXT PRIMARY KEY, source TEXT NOT NULL, result TEXT, updated REAL);
            """)
            if roots is not None:
                db.execute("INSERT OR REPLACE INTO settings VALUES('roots',?)",
                           (json.dumps([str(Path(p).resolve()) for p in roots]),))
            db.execute("INSERT OR IGNORE INTO settings VALUES('roots',?)",
                       (json.dumps(["/mnt/d", "/mnt/e", "/mnt/f", "/mnt/h"]),))
            db.execute("INSERT OR IGNORE INTO settings VALUES('reserve',?)", (str(reserve),))
        self.stop = threading.Event()
        self.drive_locks = {}
        self.lock_guard = threading.Lock()
        self.threads = []
        self.inventory_lock = threading.Lock()
        self.inventory_cache = None
        self.inventory_at = 0

    @contextlib.contextmanager
    def db(self):
        conn = sqlite3.connect(self.dbpath, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def write_retry(self,operation):
        """Retry a short rolled-back metadata transaction, respecting service stop."""
        while not self.stop.is_set():
            try:
                with self.db() as db:return operation(db)
            except sqlite3.OperationalError as error:
                if not sqlite_busy(error):raise
                if self.stop.wait(0.1):break
        raise Deferred('Service is stopping; metadata write remains checkpointed')

    def setting(self, key):
        with self.db() as db:
            return db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0]

    @property
    def roots(self):
        return [Path(p) for p in json.loads(self.setting("roots"))]

    def safe_path(self, value, destination=False):
        p = Path(value)
        if not p.is_absolute() or ".." in p.parts:
            raise ValueError("Use an absolute path without '..'")
        root = next((r for r in self.roots if p == r or r in p.parents), None)
        if root is None:
            raise ValueError("Path is outside the configured drives")
        if any(x in SKIP for x in p.parts):
            raise ValueError("System folders and recovery storage are excluded")
        current = root
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Drive is unavailable or redirected")
        if str(root).startswith('/mnt/') and not os.path.ismount(root):
            raise ValueError("Drive is not mounted")
        for part in p.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symbolic links cannot be transfer or scan paths")
        # resolve catches mount aliases and other filesystem redirections.
        if p.resolve(strict=False) != p:
            raise ValueError("Redirected paths are excluded")
        if not destination and not p.exists():
            raise ValueError("Path no longer exists")
        return p, root

    def event(self, message, job_id=None):
        self.write_retry(lambda db:db.execute("INSERT INTO events(at,job_id,message) VALUES(?,?,?)",
                       (time.time(),job_id,message)))

    def enqueue(self, kind, path, payload=None, key=None):
        ident = key or uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO jobs(id,kind,path,status,payload,created,updated) "
                       "VALUES(?,?,?,'pending',?,?,?)",
                       (ident, kind, str(path), json.dumps(payload or {}), time.time(), time.time()))
        return ident

    def scan(self, path, depth=-1):
        p, _ = self.safe_path(path)
        if not p.is_dir():
            raise ValueError("Scan path must be a directory")
        if not isinstance(depth, int) or depth < -1 or depth > 100:
            raise ValueError("Depth must be -1 (recursive) or 0–100")
        with self.db() as db:
            existing = db.execute("SELECT id,payload,status FROM jobs WHERE kind='scan' AND path=? "
                                  "AND status IN ('running','pending','paused')", (str(p),)).fetchone()
        if existing:
            previous_depth = json.loads(existing['payload'])['depth']
            if previous_depth == -1 or (depth >= 0 and previous_depth >= depth):
                return existing['id']
            if existing['status'] == 'pending':
                with self.db() as db:
                    db.execute("UPDATE jobs SET payload=? WHERE id=? AND status='pending'",
                               (json.dumps({'depth': depth}), existing['id']))
                return existing['id']
        ident = self.enqueue("scan", p, {"depth": depth})
        with self.db() as db:
            db.execute("INSERT INTO directories(job_id,path,depth) VALUES(?,?,0)", (ident, str(p)))
        self.event(f"Scan queued: {p}", ident)
        return ident

    def propose(self, source, destination, action="copy", reason="Requested transfer", automatic=False, policy_id=None):
        if action == 'model_route':
            from .models import propose
            return propose(self, source, destination, automatic, reason)
        if action not in ("copy", "move"):
            raise ValueError("Only copy and recoverable move are supported")
        src, _ = self.safe_path(source)
        dst, _ = self.safe_path(destination, True)
        snap = signature(src)
        if src.suffix.lower() in PROTECTED:
            raise ValueError("Virtual disks require a dedicated offline WSL/VM workflow")
        if dst.exists() or src == dst:
            raise ValueError("Destination already exists; it will never be overwritten")
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute("SELECT id FROM candidates WHERE source=? AND destination=? "
                                  "AND status IN ('review','queued')",
                                  (str(src), str(dst))).fetchone()
            if existing:
                return existing[0]
            ident = uuid.uuid4().hex
            db.execute("INSERT INTO candidates(id,kind,source,destination,snapshot,size,reason,"
                       "confidence,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (ident, action, str(src), str(dst), json.dumps(snap), snap["size"], reason,
                        "policy" if automatic else "review", time.time(), time.time()))
        self.event(f"Transfer proposed: {src} → {dst}")
        if automatic:
            self.approve([ident], policy=True, policy_id=policy_id)
        return ident

    def approve(self, ids, policy=False, policy_id=None):
        if not ids or len(ids) > 100:
            raise ValueError("Select 1–100 proposals")
        # Validate the whole batch before committing any approval.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = []
            for ident in dict.fromkeys(ids):
                row = db.execute("SELECT * FROM candidates WHERE id=?", (ident,)).fetchone()
                if not row or row["status"] != "review" or row["kind"] not in ("copy", "move", "purge", "model_route", "workspace_archive", "workspace_restore_review", "registry_remove", "git_object_repair"):
                    raise ValueError("Proposal is not an actionable pending transfer")
                if row['kind'] == 'git_object_repair':
                    if policy:raise ValueError('Git object repair requires checkbox review')
                    from .object_repairs import validate
                    validate(self,row)
                    rows.append(row)
                    continue
                if row['kind'] == 'workspace_restore_review':
                    if policy:raise ValueError('Fresh-baseline restoration requires checkbox review')
                    from .relocations import validate_reviewed_restore
                    validate_reviewed_restore(self,row)
                    rows.append(row)
                    continue
                if row['kind'] == 'registry_remove':
                    if policy:
                        raise ValueError('Registry decisions require checkbox review')
                    from .registry import validate
                    validate(self, row)
                    rows.append(row)
                    continue
                if row['kind'] == 'workspace_archive':
                    if policy:
                        raise ValueError('Workspace relocation is not covered by file transfer policies')
                    from .relocations import validate
                    validate(self, row)
                    rows.append(row)
                    continue
                if row['kind'] == 'model_route':
                    from .models import validate
                    validate(self, row)
                    rows.append(row)
                    continue
                if row['kind'] == 'purge':
                    if policy:
                        raise ValueError('Permanent removal always requires an individual review')
                    self.validate_purge(row)
                    rows.append(row)
                    continue
                src, _ = self.safe_path(row["source"])
                dst, _ = self.safe_path(row["destination"], True)
                if signature(src) != json.loads(row["snapshot"]):
                    raise ValueError("Source changed; reject this proposal and create a fresh one")
                if dst.exists():
                    raise ValueError("Destination exists; approval requires a new proposal")
                rows.append(row)
            if policy and (not policy_id or not db.execute('SELECT id FROM policies WHERE id=?', (policy_id,)).fetchone()):
                raise ValueError('Standing permission was removed; automatic execution requires fresh review')
            for row in rows:
                job = uuid.uuid4().hex
                kind = 'registry' if row['kind']=='registry_remove' else 'transfer'
                db.execute("INSERT INTO jobs(id,kind,path,status,payload,created,updated) "
                           "VALUES(?,?,?,'pending',?,?,?)",
                           (job, kind, row["source"], json.dumps({"candidate": row["id"]}),
                            time.time(), time.time()))
                db.execute("UPDATE candidates SET status='queued',job_id=?,updated=? WHERE id=?",
                           (job, time.time(), row["id"]))
                db.execute("INSERT INTO events(at,job_id,message) VALUES(?,?,?)",
                           (time.time(), job, ("Policy authorized" if policy else "User approved") +
                            f": {row['kind']} {row['source']} → {row['destination']}"))

    def reject(self, ids):
        with self.db() as db:
            for ident in ids:
                db.execute("UPDATE candidates SET status='rejected',updated=? "
                           "WHERE id=? AND status='review'", (time.time(), ident))

    def control(self, ident, action):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
            if not row:
                raise ValueError("Unknown job")
            if action == "pause" and row["status"] in ("pending", "running"):
                state = "paused"
            elif action == "resume" and row["status"] in ("paused", "blocked", "failed"):
                state = "pending"
            elif action == "cancel" and row["status"] not in ("completed", "cancelled"):
                state = "cancelled"
            else:
                raise ValueError("That operation is unavailable for this job state")
            db.execute("UPDATE jobs SET status=?,updated=? WHERE id=?", (state, time.time(), ident))
            if state == 'cancelled':
                db.execute("UPDATE candidates SET status='cancelled',updated=? WHERE job_id=? AND status='queued'", (time.time(), ident))
        self.event(f"Job {action}", ident)

    def check(self, job):
        if self.stop.is_set():
            raise Deferred("Service is stopping; work is checkpointed")
        with self.db() as db:
            state = db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()[0]
        if state != "running":
            raise Deferred(state)

    def progress(self, job, count, size, message):
        self.write_retry(lambda db:db.execute("UPDATE jobs SET bytes=?,files=?,message=?,updated=? WHERE id=?",
                       (size,count,message,time.time(),job)))

    def run_scan(self, job):
        payload = json.loads(job["payload"])
        _, root = self.safe_path(job["path"])
        while True:
            self.check(job["id"])
            with self.db() as db:
                todo = db.execute("SELECT * FROM directories WHERE job_id=? AND done=0 "
                                  "ORDER BY depth,path LIMIT 1", (job["id"],)).fetchone()
            if todo is None:
                return
            with self.drive_lock(root):
                self.check(job['id'])
                self._scan_directory(job, todo, root, payload)
            self.stop.wait(0.01)

    def drive_lock(self, root):
        with self.lock_guard:
            return self.drive_locks.setdefault(str(root), threading.Lock())

    def _scan_directory(self, job, todo, root, payload):
        path = Path(todo["path"])
        rows, children = [], []
        try:
            self.safe_path(str(path))
            with os.scandir(path) as items:
                for entry in items:
                    if entry.name in SKIP or entry.is_symlink():
                        continue
                    try:
                        s = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        self.record_error(job["id"], entry.path, str(exc))
                        continue
                    kind = "dir" if stat.S_ISDIR(s.st_mode) else "file"
                    if kind == "file" and not stat.S_ISREG(s.st_mode):
                        continue
                    rows.append((entry.path, str(root), str(path), entry.name, kind,
                                 s.st_size if kind == "file" else 0, s.st_mtime_ns,
                                 job["id"], time.time()))
                    if kind == "dir" and (payload["depth"] == -1 or todo["depth"] < payload["depth"]):
                        children.append((job["id"], entry.path, todo["depth"] + 1))
                    if len(rows) % 500 == 0:
                        self.check(job["id"])
        except (OSError, ValueError) as exc:
            self.record_error(job["id"], str(path), str(exc))
            with self.db() as db:
                db.execute("UPDATE directories SET done=2 WHERE job_id=? AND path=?",
                           (job["id"], str(path)))
            return
        self.check(job["id"])
        with self.db() as db:
            # Reserve the writer before reading its snapshot; deferred read/write
            # upgrades can fail immediately with SQLITE_BUSY_SNAPSHOT.
            db.execute('BEGIN IMMEDIATE')
            old_dirs = [r[0] for r in db.execute("SELECT path FROM entries WHERE parent=? AND kind='dir'", (str(path),))]
            present = {r[0] for r in rows}
            for missing in set(old_dirs) - present:
                # '/' sorts immediately before '0'. This indexed interval covers
                # descendants exactly without scanning every inventory row.
                db.execute("DELETE FROM entries WHERE path=? OR (path>=? AND path<?)", (missing, missing+'/', missing+'0'))
            db.execute("DELETE FROM entries WHERE parent=?", (str(path),))
            db.executemany("INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?,?,?,?)", rows)
            db.executemany("INSERT OR IGNORE INTO directories(job_id,path,depth) VALUES(?,?,?)", children)
            db.execute("UPDATE directories SET done=1 WHERE job_id=? AND path=?", (job["id"], str(path)))
            files = [r for r in rows if r[4] == 'file']
            db.execute("UPDATE jobs SET files=files+?,bytes=bytes+?,message=?,updated=? WHERE id=?",
                       (len(files), sum(r[5] for r in files), str(path), time.time(), job["id"]))

    def record_error(self, job, path, message):
        with self.db() as db:
            db.execute("INSERT INTO errors(job_id,path,message,at) VALUES(?,?,?,?)",
                       (job, path, message, time.time()))

    def schedule(self, path, depth=-1, interval=86400):
        folder, _ = self.safe_path(path)
        if not folder.is_dir() or not isinstance(interval, int) or interval < 3600:
            raise ValueError('Recurring scans require a folder and an interval of at least one hour')
        if not isinstance(depth, int) or depth < -1 or depth > 100:
            raise ValueError('Invalid scan depth')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO schedules VALUES(?,?,?,?)',
                       (str(folder), depth, interval, time.time() + interval))
        self.event('Recurring inventory enabled: ' + str(folder))

    def compare(self, source, other):
        a, _ = self.safe_path(source)
        b, _ = self.safe_path(other)
        sa, sb = signature(a), signature(b)
        if a == b or sa['size'] != sb['size']:
            raise ValueError('Choose different regular files of equal size')
        return self.enqueue('compare', str(a), {'other': str(b), 'source': sa, 'destination': sb})

    def run_compare(self, job):
        payload = json.loads(job['payload'])
        source, _ = self.safe_path(job['path'])
        other, _ = self.safe_path(payload['other'])
        if signature(source) != payload['source'] or signature(other) != payload['destination']:
            raise ValueError('Files changed since the comparison was queued')
        self.progress(job['id'], 0, 0, 'Comparing SHA-256; original files remain untouched')
        hashes = []
        for path in [source, other]:
            hashes.append(digest(path, lambda: self.check(job['id'])))
        if signature(source) != payload['source'] or signature(other) != payload['destination']:
            raise ValueError('Files changed during comparison')
        outcome = 'Identical contents verified' if hashes[0] == hashes[1] else 'Different contents; preserve both'
        self.progress(job['id'], 2, payload['source']['size'] * 2, outcome)
        self.event(outcome + ': ' + str(source) + ' ↔ ' + str(other), job['id'])
        receipt = {'job': job['id'], 'source': str(source), 'other': str(other),
                   'source_snapshot': payload['source'], 'other_snapshot': payload['destination'],
                   'source_sha256': hashes[0], 'other_sha256': hashes[1],
                   'identical': hashes[0] == hashes[1], 'at': time.time()}
        self.write_receipt(self.state / 'comparisons' / (job['id'] + '.json'), receipt)

    def maintenance(self):
        while not self.stop.wait(30):
            try:
                with self.db() as db:
                    due = db.execute('SELECT * FROM schedules WHERE next_run<=?', (time.time(),)).fetchall()
                for schedule in due:
                    try:
                        self.scan(schedule['path'], schedule['depth'])
                    except (OSError, ValueError) as exc:
                        self.record_error(None, schedule['path'], str(exc))
                    with self.db() as db:
                        db.execute('UPDATE schedules SET next_run=? WHERE path=?',
                                   (time.time() + schedule['interval'], schedule['path']))
                self.apply_policies()
            except Exception as exc:
                self.event('Maintenance needs attention: ' + str(exc))

    def ensure_capacity(self, dst, needed):
        parent = dst.parent
        while not parent.exists():
            parent = parent.parent
        free = shutil.disk_usage(parent).free
        reserve = int(self.setting("reserve"))
        if free - needed < reserve:
            raise ValueError(f"Capacity hold: requires {needed / GIB:.1f} GiB plus "
                             f"{reserve / GIB:.0f} GiB headroom; {free / GIB:.1f} GiB free")

    def in_use(self, source):
        """Exclude open Linux files. Windows files get an exclusive access probe too."""
        target = str(source)
        for process in Path("/proc").iterdir():
            if not process.name.isdigit() or int(process.name) == os.getpid():
                continue
            try:
                for fd in (process / "fd").iterdir():
                    try:
                        if os.readlink(fd) == target:
                            return True
                    except OSError:
                        pass
            except OSError:
                pass
        if target.startswith("/mnt/"):
            import subprocess
            ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
            if not Path(ps).exists():
                raise ValueError("Cannot establish Windows file availability")
            windows = subprocess.run(["wslpath", "-w", target], capture_output=True, text=True, check=True).stdout.strip()
            script = "$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
            import base64
            script += base64.b64encode(windows.encode()).decode() + "')); try {$item=Get-Item -LiteralPath $p -Force -ErrorAction Stop; if(([int]$item.Attributes -band 21504) -ne 0){exit 3}; $streams=@(Get-Item -LiteralPath $p -Stream * -ErrorAction Stop | Where-Object {$_.Stream -notin @(':$DATA','::$DATA','$DATA')}); if($streams.Count -gt 0){exit 4}; $f=[IO.File]::Open($p,'Open','Read','None'); $f.Dispose(); exit 0} catch {exit 1}"
            result = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", script],
                                    capture_output=True, timeout=30)
            if result.returncode == 3:
                raise ValueError('Encrypted, offline or reparse-point files require a native Windows workflow')
            if result.returncode == 4:
                raise ValueError('File has alternate NTFS data streams; keep the original and use a native Windows workflow')
            return result.returncode != 0
        return False

    def run_transfer(self, job):
        with self.db() as db:
            c = dict(db.execute("SELECT * FROM candidates WHERE id=?",
                               (json.loads(job["payload"])["candidate"],)).fetchone())
        if c['kind'] == 'registry_remove':
            from .registry import run
            run(self, job, c)
            return
        if c['kind'] == 'model_route':
            from .models import run
            run(self, job, c)
            return
        if c['kind'] == 'workspace_archive':
            from .relocations import run
            run(self, job, c)
            return
        if c['kind'] == 'git_object_repair':
            from .object_repairs import run
            run(self,job,c)
            return
        if c['kind'] == 'workspace_restore_review':
            from .relocations import run_reviewed_restore
            run_reviewed_restore(self,job,c)
            return
        if c['kind'] == 'purge':
            self.run_purge(job, c)
            return
        src, source_root = self.safe_path(c["source"], True)
        dst, _ = self.safe_path(c["destination"], True)
        original = json.loads(c["snapshot"])
        partial = dst.parent / (".drive-manager-" + job["id"] + ".part")
        receipt = self.state / "receipts" / (job["id"] + ".json")
        quarantine = source_root / ".drive-manager-recovery" / job["id"] / src.name
        # After a crash in the finalization window, reconcile from verified files.
        if dst.exists():
            if partial.exists() and not partial.is_symlink() and receipt.exists() and os.path.samefile(partial, dst):
                partial.unlink()
            self.finish_existing(job, c, src, dst, original, quarantine, receipt)
            return
        if signature(src) != original:
            raise ValueError("Source changed since approval; review a new proposal")
        if self.in_use(src):
            raise ValueError("Source is in use; close the app before resuming")
        if partial.is_symlink():
            raise ValueError("Partial transfer path is redirected")
        partial_present = partial.exists()
        offset = signature(partial)['size'] if partial_present else 0
        if offset > original["size"]:
            raise ValueError("Partial file is larger than the approved source")
        self.ensure_capacity(dst, original["size"] - offset)
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.safe_path(str(dst), True)
        # Validate every existing byte before resuming; never trust a partial solely by length.
        with os.fdopen(os.open(src, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
            opened = os.fstat(source.fileno())
            if {'size': opened.st_size, 'mtime_ns': opened.st_mtime_ns,
                'device': opened.st_dev, 'inode': opened.st_ino} != original:
                raise ValueError('Source changed immediately before opening')
            if offset:
                with open(partial, "rb") as previous:
                    while chunk := previous.read(8 * 1024**2):
                        self.check(job["id"])
                        if chunk != source.read(len(chunk)):
                            raise ValueError("Partial file differs from source; retained for investigation")
            self.check(job["id"])
            flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
            if not partial_present:
                flags |= os.O_CREAT | os.O_EXCL
            with os.fdopen(os.open(partial, flags, 0o600), 'ab') as output:
                last = 0
                while chunk := source.read(8 * 1024**2):
                    self.check(job["id"])
                    self.ensure_capacity(dst, len(chunk))
                    output.write(chunk)
                    offset += len(chunk)
                    if time.monotonic() - last > 1:
                        output.flush()
                        self.progress(job["id"], 0, offset, "Copying; source retained")
                        last = time.monotonic()
                output.flush()
                os.fsync(output.fileno())
        self.progress(job["id"], 0, offset, "Verifying source and destination with SHA-256")
        source_hash = digest(src, lambda: self.check(job["id"]))
        copied_hash = digest(partial, lambda: self.check(job["id"]))
        if signature(src) != original or source_hash != copied_hash:
            raise ValueError("Verification failed or source changed; original and partial retained")
        self.check(job["id"])
        # A durable intent receipt allows restart recovery before publishing/removing anything.
        data = {"job": job["id"], "source": str(src), "destination": str(dst),
                "sha256": source_hash, "snapshot": original, "action": c["kind"],
                "recovery": str(quarantine) if c["kind"] == "move" else None,
                "phase": "verified", "at": time.time()}
        self.write_receipt(receipt, data)
        shutil.copystat(src, partial, follow_symlinks=False)
        # Hard link publishes atomically without overwriting a competing destination.
        os.link(partial, dst, follow_symlinks=False)
        partial.unlink()
        self.finish_existing(job, c, src, dst, original, quarantine, receipt)

    def write_receipt(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with open(temp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def finish_existing(self, job, c, src, dst, original, quarantine, receipt):
        if not receipt.exists():
            raise ValueError("Destination exists without this job's receipt; refusing to alter it")
        data = json.loads(receipt.read_text())
        self.safe_path(str(dst))
        if signature(dst)["size"] != original["size"] or digest(dst, lambda: self.check(job["id"])) != data["sha256"]:
            raise ValueError("Published destination does not match the verified receipt")
        if c["kind"] == "move":
            if src.exists():
                if signature(src) != original or digest(src, lambda: self.check(job["id"])) != data["sha256"]:
                    raise ValueError("Source changed; verified destination retained and source untouched")
                if self.in_use(src):
                    raise ValueError("Source is in use; verified copy retained; original not moved")
                self.check(job["id"])
                self.safe_path(str(src))
                if signature(src) != original:
                    raise ValueError('Source changed immediately before finalization')
                if quarantine.exists():
                    raise ValueError("Recovery path already exists; manual review required")
                self.recovery_path(data)
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                self.recovery_path(data)
                # Same-volume rename retains the original intact for recovery.
                os.rename(src, quarantine)
                self.event(f"Original retained for recovery: {quarantine}", job["id"])
            elif not quarantine.exists() or digest(quarantine, lambda: self.check(job["id"])) != data["sha256"]:
                raise ValueError("Cannot locate a verified recoverable original")
        elif not src.exists() or signature(src) != original:
            raise ValueError("Source changed or vanished; published copy retained for review")
        data["phase"] = "completed"
        self.write_receipt(receipt, data)
        self.index_transfer(src, dst, job['id'], remove_source=c['kind'] == 'move')
        self.progress(job["id"], 1, original["size"], "Verified; recoverable original retained" if c["kind"] == "move" else "Verified copy; source retained")
        with self.db() as db:
            db.execute("UPDATE candidates SET status='completed',updated=? WHERE id=?", (time.time(), c["id"]))

    def index_transfer(self, source, destination, job, remove_source=False, directory=False):
        destination, root = self.safe_path(str(destination))
        paths = [p for p in destination.rglob('*') if p.is_file() and not p.is_symlink()] if directory else [destination]
        rows = []
        for path in paths:
            info = path.stat()
            rows.append((str(path), str(root), str(path.parent), path.name, 'file',
                         info.st_size, info.st_mtime_ns, job, time.time()))
        with self.db() as db:
            if remove_source:
                source_text=str(source)
                db.execute('DELETE FROM entries WHERE path=? OR (path>=? AND path<?)', (source_text, source_text+'/', source_text+'0'))
            db.executemany('INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?,?,?,?)', rows)
        with self.inventory_lock:
            self.inventory_at = 0

    def propose_purge(self, transfer_job):
        receipt = self.state / 'receipts' / (transfer_job + '.json')
        if len(transfer_job) != 32 or not all(x in '0123456789abcdef' for x in transfer_job):
            raise ValueError('Invalid transfer ID')
        data = json.loads(receipt.read_text())
        if data['phase'] != 'completed' or data['action'] != 'move':
            raise ValueError('Only completed recoverable moves can release their recovery copy')
        recovery = self.recovery_path(data)
        snap = {'transfer': transfer_job, 'signature': signature(recovery), 'sha256': data['sha256']}
        with self.db() as db:
            existing = db.execute("SELECT id FROM candidates WHERE kind='purge' AND source=? "
                                  "AND status IN ('review','queued','completed')", (str(recovery),)).fetchone()
            if existing:
                return existing[0]
            ident = uuid.uuid4().hex
            db.execute("INSERT INTO candidates(id,kind,source,destination,snapshot,size,reason,created,updated) "
                       "VALUES(?,'purge',?,?,?,?,?,?,?)",
                       (ident, str(recovery), data['destination'], json.dumps(snap), snap['signature']['size'],
                        'Permanently remove the recovery original after re-verifying the destination. '
                        'This reclaims source space and ends rollback for this move.', time.time(), time.time()))
        return ident

    def recovery_path(self, receipt):
        source, root = self.safe_path(receipt['source'], True)
        expected = root / '.drive-manager-recovery' / receipt['job'] / source.name
        if str(expected) != receipt['recovery']:
            raise ValueError('Recovery receipt path is inconsistent')
        current = expected
        while current != root:
            if current.is_symlink():
                raise ValueError('Recovery storage is redirected')
            current = current.parent
        return expected

    def validate_purge(self, candidate, missing_ok=False):
        snap = json.loads(candidate['snapshot'])
        receipt_path = self.state / 'receipts' / (snap['transfer'] + '.json')
        data = json.loads(receipt_path.read_text())
        recovery = self.recovery_path(data)
        if str(recovery) != candidate['source'] or data['destination'] != candidate['destination'] or data['sha256'] != snap['sha256']:
            raise ValueError('Recovery proposal no longer matches its receipt')
        destination, _ = self.safe_path(candidate['destination'])
        signature(destination)
        if recovery.exists():
            if signature(recovery) != snap['signature']:
                raise ValueError('Recovery original changed; removal requires fresh review')
        elif not missing_ok:
            raise ValueError('Recovery original is no longer present')
        return receipt_path, data, recovery, destination

    def run_purge(self, job, candidate):
        receipt_path, data, recovery, destination = self.validate_purge(candidate, missing_ok=True)
        if not recovery.exists():
            if data.get('purge_job') != job['id']:
                raise ValueError('Recovery original vanished without this removal job')
        else:
            self.progress(job['id'], 0, 0, 'Re-verifying destination before permanent recovery removal')
            check = lambda: self.check(job['id'])
            destination_before = signature(destination)
            if digest(destination, check) != data['sha256'] or signature(destination) != destination_before:
                raise ValueError('Destination changed; recovery copy will not be removed')
            if digest(recovery, check) != data['sha256']:
                raise ValueError('Recovery contents changed; refusing removal')
            self.validate_purge(candidate)
            if self.in_use(recovery):
                raise ValueError('Recovery file is in use')
            check()
            if signature(destination) != destination_before:
                raise ValueError('Destination changed immediately before removal; recovery copy retained')
            data['purge_job'] = job['id']
            data['phase'] = 'purging'
            self.write_receipt(receipt_path, data)
            recovery.unlink()
        data['phase'] = 'purged'
        self.write_receipt(receipt_path, data)
        self.progress(job['id'], 1, candidate['size'], 'Recovery copy permanently removed; source space reclaimed')
        with self.db() as db:
            db.execute("UPDATE candidates SET status='completed',updated=? WHERE id=?", (time.time(), candidate['id']))
        self.event(f"Permanently removed approved recovery copy: {recovery}", job['id'])

    def policy(self, source, destination, action, references_confirmed, automatic=True):
        src, _ = self.safe_path(source)
        dst, _ = self.safe_path(destination, True)
        if not src.is_dir() or src == dst or src in dst.parents or dst in src.parents:
            raise ValueError("Policy directories must be separate, non-overlapping locations")
        if action not in ("copy", "move") or (action == "move" and references_confirmed is not True):
            raise ValueError("Moves require confirmation that applications use the destination")
        ident = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO policies VALUES(?,?,?,?,?,?,?)",
                       (ident, str(src), str(dst), action, bool(automatic), bool(references_confirmed), time.time()))
        self.event(f"Standing policy created: {action} {src} → {dst}; automatic={automatic}")
        self.apply_policies()
        return ident

    def apply_policies(self):
        with self.db() as db:
            policies = [dict(x) for x in db.execute("SELECT * FROM policies")]
        for p in policies:
            if p['action'] == 'model_route':
                from .models import propose_used, propose_missing
                propose_used(self)
                propose_missing(self)
                continue
            source = Path(p["source"])
            with self.db() as db:
                rows = db.execute("SELECT e.path FROM entries e WHERE e.kind='file' AND "
                                  "substr(e.path,1,?)=? AND NOT EXISTS (SELECT 1 FROM candidates c "
                                  "WHERE c.source=e.path AND c.destination=? || substr(e.path,?)) LIMIT 1000",
                                  (len(str(source)) + 1, str(source) + "/", p['destination'], len(str(source)) + 1)).fetchall()
            for row in rows:
                with self.db() as db:
                    if not db.execute('SELECT id FROM policies WHERE id=?', (p['id'],)).fetchone():
                        break
                path = Path(row["path"])
                dst = Path(p["destination"]) / path.relative_to(source)
                if dst.exists() or path.suffix.lower() in PROTECTED:
                    with self.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        existing = db.execute('SELECT id FROM candidates WHERE source=? AND destination=?',
                                              (str(path), str(dst))).fetchone()
                        if existing is None:
                            db.execute("INSERT INTO candidates(id,kind,source,destination,reason,status,created,updated) "
                                       "VALUES(?,'inspect',?,?,?,'skipped',?,?)",
                                       (uuid.uuid4().hex, str(path), str(dst),
                                        'Policy skipped: existing destination or protected virtual disk', time.time(), time.time()))
                    continue
                try:
                    self.propose(str(path), str(dst), p["action"],
                                 "Matches your standing policy " + p["id"], bool(p["automatic"]), policy_id=p['id'])
                except (ValueError, OSError) as exc:
                    self.record_error(None, str(path), str(exc))

    def claim_job(self,lane,scan_root=None):
        if lane=='registry':
            query="SELECT * FROM jobs WHERE status='pending' AND kind='registry' ORDER BY created LIMIT 1";params=()
        elif lane=='workspace':
            query="SELECT * FROM jobs WHERE status='pending' AND kind IN ('workspace_manifest','workspace_snapshot') ORDER BY created LIMIT 1";params=()
        elif scan_root is None:
            query="SELECT * FROM jobs WHERE status='pending' AND kind IN ('transfer','compare','workspace_history','workspace_restore') ORDER BY created LIMIT 1";params=()
        else:
            base=str(scan_root)
            query="SELECT * FROM jobs WHERE status='pending' AND kind='scan' AND (path=? OR (path>=? AND path<?)) ORDER BY created LIMIT 1"
            params=(base,base+'/',base+'0')
        with self.db() as db:
            # Idle workers need no writer lock. Recheck after taking the short
            # claim transaction so competing workers cannot claim the same job.
            if db.execute(query,params).fetchone() is None:return None
            db.execute('BEGIN IMMEDIATE')
            job=db.execute(query,params).fetchone()
            if job is None:return None
            db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?",(time.time(),job['id']))
            return job

    def worker(self, lane, scan_root=None):
        while not self.stop.wait(0.5):
            try:
                job=self.claim_job(lane,scan_root)
            except sqlite3.OperationalError as error:
                if sqlite_busy(error):
                    continue  # Retry the same pending queue; do not lose its worker.
                raise
            if job is None:continue
            try:
                # Recovery jobs and interrupted moves may no longer have an original path.
                if job['kind'] in ('transfer','registry'):
                    with self.db() as db:
                        candidate = db.execute('SELECT * FROM candidates WHERE job_id=?', (job['id'],)).fetchone()
                    original_path = candidate['source'].split('/.drive-manager-recovery/', 1)[0] if candidate['kind'] == 'purge' else str(Path(candidate['source']).parent) if candidate['kind'] in ('model_route','workspace_archive') else job['path']
                    if candidate['kind'] == 'registry_remove':
                        original_path = str(Path.home() / 'workspace')
                else:
                    original_path = job['path']
                if job['kind'] in ('workspace_history','workspace_manifest','workspace_snapshot','registry'):
                    from .workspaces import workspace_source
                    roots = {str(workspace_source(self, original_path)[1])}
                else:
                    roots = {str(self.safe_path(original_path, True)[1])}
                if job['kind'] == 'transfer':
                    with self.db() as db:
                        c = db.execute("SELECT destination,kind FROM candidates WHERE job_id=?", (job["id"],)).fetchone()
                    target = str(Path(c[0]).parent) if c['kind'] in ('workspace_archive','workspace_restore_review') else c[0]
                    if c['kind']!='registry_remove':
                        roots.add(str(self.safe_path(target, True)[1]))
                elif job['kind'] == 'compare':
                    roots.add(str(self.safe_path(json.loads(job['payload'])['other'])[1]))
                elif job['kind'] in ('workspace_history','workspace_snapshot'):
                    roots.add(str(self.safe_path(json.loads(job['payload'])['destination'], True)[1]))
                # Scans release their drive after each directory; transfers reserve their drives.
                # Other drives and the review page keep making progress.
                with contextlib.ExitStack() as stack:
                    for root in ([] if job['kind'] in ('scan','workspace_manifest','registry') else sorted(roots)):
                        with self.lock_guard:
                            lock = self.drive_locks.setdefault(root, threading.Lock())
                        stack.enter_context(lock)
                    self.check(job["id"])
                    if job['kind'] == "scan":
                        self.run_scan(job)
                    elif job['kind'] == 'compare':
                        self.run_compare(job)
                    elif job['kind'] == 'workspace_history':
                        from .workspaces import run_history
                        run_history(self, job)
                    elif job['kind'] == 'workspace_manifest':
                        from .manifests import run_manifest
                        run_manifest(self, job)
                    elif job['kind'] == 'workspace_snapshot':
                        from .snapshots import run
                        run(self, job)
                    elif job['kind'] == 'workspace_restore':
                        from .relocations import run_restore
                        run_restore(self, job)
                    else:
                        self.run_transfer(job)
                self.write_retry(lambda db:db.execute("UPDATE jobs SET status='completed',updated=? WHERE id=? AND status='running'",
                               (time.time(),job['id'])))
                self.event("Job completed", job["id"])
                if lane == "scan":
                    self.apply_policies()
            except Deferred:
                pass
            except Exception as exc:
                try:
                    if sqlite_busy(exc):
                        self.write_retry(lambda db:db.execute("UPDATE jobs SET status='pending',message=?,updated=? WHERE id=? AND status='running'",
                            ('Retrying checkpoint after transient database writer contention',time.time(),job['id'])))
                        self.event('Transient database contention; same checkpoint retained for retry',job['id'])
                    else:
                        self.write_retry(lambda db:db.execute("UPDATE jobs SET status='blocked',message=?,updated=? WHERE id=? AND status='running'",
                            (str(exc),time.time(),job['id'])))
                        self.event('Job needs attention: '+str(exc),job['id'])
                except Deferred:
                    pass

    def start(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET status='pending',message='Resuming after service restart' WHERE status='running'")
        for lane, root in [('scan', root) for root in self.roots] + [('transfer', None),('workspace',None),('registry',None)]:
            name = 'scan-' + root.name if root is not None else lane
            thread = threading.Thread(target=self.worker, args=(lane, root), daemon=True, name=name)
            thread.start()
            self.threads.append(thread)
        thread = threading.Thread(target=self.maintenance, daemon=True, name='maintenance')
        thread.start()
        self.threads.append(thread)

    def inventory_summary(self):
        # Inventory aggregates are heavier than live job state. Share a short cache
        # across browser polls and never send unbounded duplicate path lists.
        with self.inventory_lock:
            if self.inventory_cache is not None and time.monotonic() - self.inventory_at < 15:
                return self.inventory_cache
            with self.db() as db:
                totals = dict(db.execute("SELECT count(*) entries,coalesce(sum(size),0) bytes FROM entries WHERE kind='file'").fetchone())
                largest = [dict(r) for r in db.execute("SELECT path,size,seen FROM entries WHERE kind='file' ORDER BY size DESC LIMIT 30")]
                parents = db.execute("SELECT root,parent,sum(size) size,count(*) files FROM entries WHERE kind='file' GROUP BY root,parent").fetchall()
                groups = db.execute("SELECT name,size,count(*) copies FROM entries WHERE kind='file' AND size>0 GROUP BY name,size HAVING count(*)>1 ORDER BY size*(count(*)-1) DESC LIMIT 40").fetchall()
                duplicates = []
                for row in groups:
                    item = dict(row)
                    item['sample_paths'] = [r[0] for r in db.execute('SELECT path FROM entries WHERE name=? AND size=? ORDER BY path LIMIT 6', (row['name'], row['size']))]
                    item['paths'] = '\n'.join(item['sample_paths'])
                    duplicates.append(item)
            rollup = {}
            for row in parents:
                folder, root = Path(row['parent']), Path(row['root'])
                while folder != root and root in folder.parents:
                    item = rollup.setdefault(str(folder), {'path': str(folder), 'size': 0, 'files': 0})
                    item['size'] += row['size']; item['files'] += row['files']
                    folder = folder.parent
            result = {'totals': totals, 'largest': largest, 'folders': sorted(rollup.values(), key=lambda x: x['size'], reverse=True)[:30], 'duplicates': duplicates}
            self.inventory_cache = result
            self.inventory_at = time.monotonic()
            return result

    def snapshot(self,include_inventory=True):
        inventory = self.inventory_summary() if include_inventory else self.inventory_cache
        inventory_loading = inventory is None
        if inventory is None:inventory={'totals':{'entries':0,'bytes':0},'largest':[],'folders':[],'duplicates':[]}
        drives = []
        for root in self.roots:
            try:
                if not root.is_dir() or (str(root).startswith('/mnt/') and not os.path.ismount(root)):
                    drives.append({'path': str(root), 'available': False})
                    continue
                usage = shutil.disk_usage(root)
                drives.append({"path": str(root), "total": usage.total, "used": usage.used,
                               "free": usage.free, "reserve": int(self.setting("reserve")),
                               "available": root.is_dir()})
            except OSError:
                drives.append({"path": str(root), "available": False})
        with self.db() as db:
            result = {"drives": drives, "jobs": [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'blocked' THEN 1 WHEN 'paused' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,created DESC LIMIT 150")],
                      "candidates": [dict(r) for r in db.execute("SELECT * FROM candidates ORDER BY status='review' DESC,created DESC LIMIT 500")],
                      "policies": [dict(r) for r in db.execute("SELECT * FROM policies")],
                      'schedules': [dict(r) for r in db.execute('SELECT * FROM schedules')],
                      "events": [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 60")],
                      "errors": [dict(r) for r in db.execute("SELECT * FROM errors ORDER BY id DESC LIMIT 30")],
                      **inventory}
        result["inventory_loading"] = inventory_loading
        result["model_profile"] = str(self.state / "profiles" / "comfyui-f-first.yaml")
        with self.db() as db:
            routing = db.execute("SELECT value FROM settings WHERE key='model_routing'").fetchone()
        result['model_routing'] = json.loads(routing[0]) if routing else None
        return result
