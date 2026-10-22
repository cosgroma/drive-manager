from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from drive_manager.core import Store, sqlite_busy


class WorkerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir();self.target=self.root/'target';self.target.mkdir()
        self.store=Store(self.root/'state',[self.source,self.target],reserve=0);self.workers=[]
        self.original_db=self.store.db

    def tearDown(self):
        self.store.stop.set()
        for worker in self.workers:worker.join(5)
        self.temp.cleanup()

    @contextmanager
    def short_db(self):
        with self.original_db() as db:
            db.execute('PRAGMA busy_timeout=30')
            yield db

    def worker(self,lane,root=None):
        thread=threading.Thread(target=self.store.worker,args=(lane,root));self.workers.append(thread);thread.start();return thread

    def test_idle_worker_does_not_require_writer_lock(self):
        with patch.object(self.store,'db',self.short_db):
            with self.original_db() as writer:
                writer.execute('BEGIN IMMEDIATE')
                thread=self.worker('transfer');time.sleep(.7)
                self.assertTrue(thread.is_alive())
                self.assertIsNone(self.store.claim_job('transfer'))

    def test_busy_pending_claim_retries_and_completes_after_lock_release(self):
        (self.source/'unique.bin').write_bytes(b'unchanged source')
        ident=self.store.scan(str(self.source));busy=[];original_claim=self.store.claim_job
        def claim(*args):
            try:return original_claim(*args)
            except sqlite3.OperationalError as error:busy.append(error);raise
        with patch.object(self.store,'db',self.short_db),patch.object(self.store,'claim_job',side_effect=claim):
            with self.original_db() as writer:
                writer.execute('BEGIN IMMEDIATE');thread=self.worker('scan',self.source)
                deadline=time.monotonic()+5
                while not busy and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(busy);self.assertTrue(thread.is_alive())
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                with self.original_db() as db:row=db.execute('SELECT status,message FROM jobs WHERE id=?',(ident,)).fetchone()
                if row['status'] in ('completed','blocked'):break
                time.sleep(.05)
            self.assertEqual(row['status'],'completed',row['message']);self.assertTrue(thread.is_alive())

    def test_competing_claims_assign_the_pending_job_once(self):
        ident=self.store.scan(str(self.source));barrier=threading.Barrier(3);claimed=[];errors=[]
        def compete():
            barrier.wait()
            try:
                row=self.store.claim_job('scan',self.source)
                if row:claimed.append(row['id'])
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=compete) for _ in range(2)]
        for thread in threads:thread.start()
        barrier.wait()
        for thread in threads:thread.join(5)
        self.assertFalse(errors);self.assertEqual(claimed,[ident])

    def test_subtree_cleanup_preserves_prefix_siblings_and_uses_index(self):
        source=self.source/'sub';source.mkdir();(source/'original').write_text('retained source')
        destination=self.target/'moved';destination.mkdir();(destination/'original').write_text('retained source')
        paths=[source,source/'original',self.source/'sub0/keep',self.source/'sub-other/keep',self.source/'sub%/keep']
        rows=[(str(path),str(self.source),str(path.parent),path.name,'file',1,0,'fixture',0) for path in paths]
        rows.extend((str(self.source/'unrelated'/str(i)),str(self.source),str(self.source/'unrelated'),str(i),'file',1,0,'fixture',0) for i in range(5000))
        with self.original_db() as db:db.executemany('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?)',rows)
        statements=[]
        @contextmanager
        def traced():
            with self.original_db() as db:
                db.set_trace_callback(statements.append);yield db
        with patch.object(self.store,'db',traced):self.store.index_transfer(source,destination,'fixture',remove_source=True,directory=True)
        with self.original_db() as db:
            for path in paths[:2]:self.assertIsNone(db.execute('SELECT 1 FROM entries WHERE path=?',(str(path),)).fetchone())
            for path in paths[2:]:self.assertIsNotNone(db.execute('SELECT 1 FROM entries WHERE path=?',(str(path),)).fetchone())
            self.assertIsNotNone(db.execute('SELECT 1 FROM entries WHERE path=?',(str(destination/'original'),)).fetchone())
            actual_delete=next(sql for sql in statements if sql.startswith('DELETE FROM entries WHERE path='))
            plans=[r[3] for r in db.execute('EXPLAIN QUERY PLAN '+actual_delete)]
            self.assertFalse(any('SCAN entries' in detail for detail in plans),plans)
            self.assertTrue(any('SEARCH entries' in detail for detail in plans),plans)

    def test_busy_classification_includes_extended_snapshot_code(self):
        error=sqlite3.OperationalError('database is locked');error.sqlite_errorcode=sqlite3.SQLITE_BUSY | (2<<8)
        self.assertTrue(sqlite_busy(error));self.assertFalse(sqlite_busy(sqlite3.OperationalError('no such table')))

    def test_progress_write_retries_actual_writer_lock(self):
        ident=self.store.enqueue('fixture',self.source)
        lock=sqlite3.connect(self.store.dbpath);lock.execute('BEGIN IMMEDIATE')
        error=[]
        def update():
            try:self.store.progress(ident,3,7,'progress preserved')
            except Exception as exc:error.append(exc)
        with patch.object(self.store,'db',self.short_db):
            thread=threading.Thread(target=update);thread.start();time.sleep(.1);self.assertTrue(thread.is_alive());lock.rollback();lock.close();thread.join(5)
        self.assertFalse(error)
        with self.original_db() as db:self.assertEqual(tuple(db.execute('SELECT files,bytes,message FROM jobs WHERE id=?',(ident,)).fetchone()),(3,7,'progress preserved'))

    def test_operation_busy_requeues_same_job_and_worker_survives(self):
        left=self.source/'one';right=self.target/'two';left.write_bytes(b'preserve');right.write_bytes(b'preserve');ident=self.store.compare(str(left),str(right));run=self.store.run_compare;calls=[]
        def operation(job):
            calls.append(job['id'])
            if len(calls)==1:raise sqlite3.OperationalError('database is locked')
            run(job)
        with patch.object(self.store,'run_compare',side_effect=operation):
            thread=threading.Thread(target=self.store.worker,args=('transfer',));thread.start()
            try:
                until=time.monotonic()+8
                while time.monotonic()<until:
                    with self.original_db() as db:status=db.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0]
                    if status=='completed':break
                    time.sleep(.05)
                self.assertEqual(status,'completed');self.assertTrue(thread.is_alive());self.assertEqual(calls,[ident,ident])
            finally:self.store.stop.set();thread.join(5)

    def test_error_recording_busy_does_not_kill_worker(self):
        left=self.source/'one';right=self.target/'two';left.write_bytes(b'a');right.write_bytes(b'a');ident=self.store.compare(str(left),str(right));entered=threading.Event();lock=sqlite3.connect(self.store.dbpath,check_same_thread=False)
        def operation(job):
            lock.execute('BEGIN IMMEDIATE');entered.set();raise ValueError('real validation failure')
        with patch.object(self.store,'db',self.short_db),patch.object(self.store,'run_compare',side_effect=operation):
            thread=threading.Thread(target=self.store.worker,args=('transfer',));thread.start()
            try:
                self.assertTrue(entered.wait(5));time.sleep(.1);self.assertTrue(thread.is_alive());lock.rollback()
                until=time.monotonic()+5
                while time.monotonic()<until:
                    with self.original_db() as db:row=db.execute('SELECT status,message FROM jobs WHERE id=?',(ident,)).fetchone()
                    if row[0]=='blocked':break
                    time.sleep(.05)
                self.assertEqual(tuple(row),('blocked','real validation failure'));self.assertTrue(thread.is_alive())
            finally:lock.rollback();lock.close();self.store.stop.set();thread.join(5)

    def test_busy_retry_preserves_user_pause_and_cancel(self):
        for action,expected in [('pause','paused'),('cancel','cancelled')]:
            self.store.stop.clear();left=self.source/('one-'+action);right=self.target/('two-'+action);left.write_bytes(b'a');right.write_bytes(b'a');ident=self.store.compare(str(left),str(right));done=threading.Event()
            def operation(job):
                self.store.control(job['id'],action);done.set();raise sqlite3.OperationalError('database is locked')
            with patch.object(self.store,'run_compare',side_effect=operation):
                thread=threading.Thread(target=self.store.worker,args=('transfer',));thread.start()
                try:
                    self.assertTrue(done.wait(5));time.sleep(.2)
                    with self.original_db() as db:self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0],expected)
                    self.assertTrue(thread.is_alive())
                finally:self.store.stop.set();thread.join(5)
