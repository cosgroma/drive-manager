import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from drive_manager.core import Deferred, Store, digest
from drive_manager.server import make_server


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.a, self.b = self.base / 'A', self.base / 'B'
        self.a.mkdir(); self.b.mkdir()
        self.store = Store(self.base / 'state', [self.a, self.b], reserve=0)

    def tearDown(self):
        self.store.stop.set()
        for thread in self.store.threads:
            thread.join(5)
        self.temp.cleanup()

    def file(self, name='sample.bin', data=b'valuable original\x00' * 1000):
        path = self.a / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def transfer(self, action='copy', source=None, destination=None):
        src = source or self.file()
        dst = destination or self.b / src.name
        candidate = self.store.propose(str(src), str(dst), action)
        self.store.approve([candidate])
        with self.store.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=(SELECT job_id FROM candidates WHERE id=?)', (candidate,)).fetchone()
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (row['id'],))
        return src, dst, dict(row)

    def complete(self, job):
        self.store.run_transfer(job)
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job['id'],))

    def test_verified_copy_and_receipt(self):
        src, dst, job = self.transfer()
        self.complete(job)
        self.assertEqual(src.read_bytes(), dst.read_bytes())
        receipt = json.loads((self.store.state / 'receipts' / (job['id'] + '.json')).read_text())
        self.assertEqual(receipt['sha256'], digest(src))
        self.assertEqual(receipt['phase'], 'completed')

    def test_approval_is_atomic_and_stale_source_rejected(self):
        src = self.file()
        first = self.store.propose(str(src), str(self.b / src.name))
        other = self.file('other', b'other')
        second = self.store.propose(str(other), str(self.b / 'other'))
        other.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            self.store.approve([first, second])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM candidates WHERE status='review'").fetchone()[0], 2)

    def test_source_change_after_approval_preserves_both_locations(self):
        src, dst, job = self.transfer()
        src.write_bytes(b'new content')
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            self.store.run_transfer(job)
        self.assertEqual(src.read_bytes(), b'new content')
        self.assertFalse(dst.exists())

    def test_destination_conflict_never_overwritten(self):
        src, dst, job = self.transfer()
        dst.write_bytes(b'existing valuable file')
        with self.assertRaisesRegex(ValueError, 'without this job'):
            self.store.run_transfer(job)
        self.assertEqual(dst.read_bytes(), b'existing valuable file')
        self.assertTrue(src.exists())

    def test_resume_valid_partial_and_reject_corrupt_partial(self):
        src, dst, job = self.transfer()
        partial = dst.parent / ('.drive-manager-' + job['id'] + '.part')
        partial.write_bytes(b'corrupt prefix')
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.store.run_transfer(job)
        self.assertFalse(dst.exists())
        partial.write_bytes(src.read_bytes()[:123])
        self.complete(job)
        self.assertEqual(digest(src), digest(dst))
        self.assertFalse(partial.exists())

    def test_resume_empty_partial_after_crash_before_first_write(self):
        src, dst, job = self.transfer()
        partial = dst.parent / ('.drive-manager-' + job['id'] + '.part')
        partial.touch()
        self.complete(job)
        self.assertEqual(digest(src), digest(dst))
        self.assertFalse(partial.exists())

    def test_capacity_hold_keeps_source(self):
        src, dst, job = self.transfer()
        with self.store.db() as db:
            db.execute("UPDATE settings SET value=? WHERE key='reserve'", (str(10**18),))
        with self.assertRaisesRegex(ValueError, 'Capacity hold'):
            self.store.run_transfer(job)
        self.assertTrue(src.exists())
        self.assertFalse(dst.exists())

    def test_open_source_is_not_transferred(self):
        src, dst, job = self.transfer()
        with patch.object(self.store, 'in_use', return_value=True):
            with self.assertRaisesRegex(ValueError, 'in use'):
                self.store.run_transfer(job)
        self.assertTrue(src.exists())
        self.assertFalse(dst.exists())

    def test_move_retains_recovery_and_purge_requires_new_approval(self):
        src, dst, job = self.transfer('move')
        original = src.read_bytes()
        self.complete(job)
        self.assertFalse(src.exists())
        recovery = src.parent / '.drive-manager-recovery' / job['id'] / src.name
        self.assertEqual(recovery.read_bytes(), original)
        self.assertEqual(dst.read_bytes(), original)
        purge = self.store.propose_purge(job['id'])
        with self.assertRaisesRegex(ValueError, 'individual review'):
            self.store.approve([purge], policy=True)
        self.store.approve([purge])
        with self.store.db() as db:
            row = dict(db.execute('SELECT * FROM jobs WHERE id=(SELECT job_id FROM candidates WHERE id=?)', (purge,)).fetchone())
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (row['id'],))
        self.complete(row)
        self.assertFalse(recovery.exists())
        self.assertEqual(dst.read_bytes(), original)

    def test_purge_refuses_changed_destination(self):
        src, dst, job = self.transfer('move')
        self.complete(job)
        purge = self.store.propose_purge(job['id'])
        self.store.approve([purge])
        dst.write_bytes(b'destination was edited')
        with self.store.db() as db:
            row = dict(db.execute('SELECT * FROM jobs WHERE id=(SELECT job_id FROM candidates WHERE id=?)', (purge,)).fetchone())
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (row['id'],))
        with self.assertRaisesRegex(ValueError, 'Destination changed'):
            self.store.run_transfer(row)
        self.assertTrue((src.parent / '.drive-manager-recovery' / job['id'] / src.name).exists())

    def test_move_reconciles_crash_after_original_rename(self):
        src, dst, job = self.transfer('move')
        original_write = self.store.write_receipt
        def crash(path, data):
            if data['phase'] == 'completed':
                raise RuntimeError('simulated crash after rename')
            original_write(path, data)
        with patch.object(self.store, 'write_receipt', side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
                self.store.run_transfer(job)
        self.assertFalse(src.exists())
        self.complete(job)
        self.assertTrue(dst.exists())

    def test_symlinks_hardlinks_and_virtual_disks_excluded(self):
        src = self.file()
        link = self.a / 'link'
        link.symlink_to(src)
        with self.assertRaisesRegex(ValueError, 'Symbolic'):
            self.store.propose(str(link), str(self.b / 'link'))
        os.link(src, self.a / 'hard')
        with self.assertRaisesRegex(ValueError, 'one hard link'):
            self.store.propose(str(src), str(self.b / 'copy'))
        vhd = self.file('ext4.vhdx', b'disk')
        with self.assertRaisesRegex(ValueError, 'offline'):
            self.store.propose(str(vhd), str(self.b / 'ext4.vhdx'), 'move')

    def test_scan_survives_restart_and_excludes_recovery(self):
        self.file('sub/nested.bin')
        self.file('.drive-manager-recovery/secret.bin')
        job = self.store.scan(str(self.a))
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job,))
        self.store.start()
        self.wait_job(job)
        with self.store.db() as db:
            paths = [r[0] for r in db.execute('SELECT path FROM entries')]
            self.assertIn(str(self.a / 'sub/nested.bin'), paths)
            self.assertFalse(any('recovery' in p for p in paths))

    def wait_job(self, job, state='completed'):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            with self.store.db() as db:
                result = db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
            if result['status'] == state:
                return result
            if result['status'] == 'blocked':
                self.fail(result['message'])
            time.sleep(.05)
        self.fail('Job timed out: ' + str(dict(result)))

    def test_standing_policy_runs_without_per_file_approval(self):
        src = self.file('archive/item.bin')
        job = self.store.scan(str(src.parent))
        self.store.policy(str(src.parent), str(self.b / 'archive'), 'move', True)
        self.store.start()
        self.wait_job(job)
        until = time.monotonic() + 10
        while src.exists() and time.monotonic() < until:
            time.sleep(.05)
        self.assertFalse(src.exists())
        self.assertTrue((self.b / 'archive/item.bin').exists())

    def test_pause_and_cancel_do_not_run_pending_work(self):
        job = self.store.scan(str(self.a))
        self.store.control(job, 'pause')
        self.store.start()
        time.sleep(.7)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone()[0], 'paused')
        self.store.control(job, 'resume')
        self.wait_job(job)

    def test_control_state_skips_slow_inventory_and_keeps_approval_token(self):
        src=self.file();ident=self.store.propose(str(src),str(self.b/'copy'))
        server=make_server(self.store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with self.store.inventory_lock, patch.object(self.store,'inventory_summary',side_effect=AssertionError('heavy inventory must not run')):
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/control-state',timeout=3) as response:data=json.load(response)
            self.assertTrue(data['inventory_loading']);self.assertIn(ident,[r['id'] for r in data['candidates']]);self.assertTrue(data['token'])
        finally:server.shutdown();server.server_close();thread.join()

    def test_light_control_state_reuses_cached_summary_without_lock(self):
        cached=self.store.inventory_summary()
        with self.store.inventory_lock:
            data=self.store.snapshot(include_inventory=False)
        self.assertFalse(data['inventory_loading']);self.assertEqual(data['totals'],cached['totals'])

    def test_http_guards_and_action_roundtrip(self):
        server = make_server(self.store, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base + '/api/state') as res:
                token = json.load(res)['token']
            with urllib.request.urlopen(base + '/api/session') as res:
                self.assertEqual(token, json.load(res)['token'])
            payload = json.dumps({'path': str(self.a), 'depth': 0}).encode()
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(base + '/api/scan', data=payload))
            self.assertEqual(caught.exception.code, 403)
            bad = urllib.request.Request(base + '/api/scan', data=payload,
                                         headers={'X-Drive-Token': token, 'Origin': 'https://foreign.example'})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(bad)
            good = urllib.request.Request(base + '/api/scan', data=payload,
                                          headers={'X-Drive-Token': token, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(good) as res:
                self.assertTrue(json.load(res)['ok'])
            with urllib.request.urlopen(base + '/') as res:
                self.assertIn(b'Review inbox', res.read())
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + '/workspace-review')
            self.assertEqual(caught.exception.code, 404)
            report = self.store.state / 'workspace-review' / 'report.html'
            report.parent.mkdir()
            report.write_text('<h1>Workspace evidence</h1>')
            with urllib.request.urlopen(base + '/workspace-review') as res:
                self.assertIn('text/html', res.headers['Content-Type'])
                self.assertIn(b'Workspace evidence', res.read())
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def model_pair(self):
        left = self.a / 'models/publisher/repository'
        right = self.b / 'models/publisher/repository'
        for folder in [left, right]:
            folder.mkdir(parents=True)
            (folder / 'model.gguf').write_bytes(b'verified weights' * 100)
        with self.store.db() as db:
            db.execute("INSERT INTO settings VALUES('model_roots',?)",
                       (json.dumps([str(self.a / 'models'), str(self.b / 'models')]),))
        return left, right

    def model_job(self, left, right):
        candidate = self.store.propose(str(left), str(right), 'model_route')
        self.store.approve([candidate])
        with self.store.db() as db:
            job = dict(db.execute('SELECT * FROM jobs WHERE id=(SELECT job_id FROM candidates WHERE id=?)', (candidate,)).fetchone())
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job['id'],))
        return job

    def test_model_route_preserves_application_path_and_original(self):
        left, right = self.model_pair()
        job = self.model_job(left, right)
        self.complete(job)
        self.assertTrue(left.is_symlink())
        self.assertEqual(left.resolve(), right)
        self.assertEqual((left / 'model.gguf').read_bytes(), (right / 'model.gguf').read_bytes())
        receipt = json.loads((self.store.state / 'model-routes' / (job['id'] + '.json')).read_text())
        recovery = Path(receipt['recovery'])
        self.assertTrue((recovery / 'model.gguf').is_file())
        self.assertNotIn(self.a / 'models', recovery.parents)
        # Reconciliation is idempotent after a process dies before committing completion.
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job['id'],))
        self.complete(job)

    def test_model_route_refuses_same_size_different_weights(self):
        left, right = self.model_pair()
        (right / 'model.gguf').write_bytes(b'wrong weights!!!' * 100)
        job = self.model_job(left, right)
        with self.assertRaisesRegex(ValueError, 'contents differ'):
            self.store.run_transfer(job)
        self.assertFalse(left.is_symlink())
        self.assertTrue((left / 'model.gguf').is_file())

    def test_model_route_restores_original_on_junction_failure(self):
        left, right = self.model_pair()
        job = self.model_job(left, right)
        with patch('drive_manager.models.create_junction', side_effect=RuntimeError('simulated Windows error')):
            with self.assertRaisesRegex(RuntimeError, 'Windows error'):
                self.store.run_transfer(job)
        self.assertTrue(left.is_dir())
        self.assertFalse(left.is_symlink())
        self.complete(job)
        self.assertTrue(left.is_symlink())

    def test_compare_records_content_evidence(self):
        source = self.file()
        other = self.b / source.name
        other.write_bytes(source.read_bytes())
        ident = self.store.compare(str(source), str(other))
        with self.store.db() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (ident,))
        self.store.run_compare(job)
        result = json.loads((self.store.state / 'comparisons' / (ident + '.json')).read_text())
        self.assertTrue(result['identical'])

    def test_schedule_is_durable(self):
        self.store.schedule(str(self.a), 0, 86400)
        reopened = Store(self.store.state)
        with reopened.db() as db:
            row = db.execute('SELECT * FROM schedules').fetchone()
        self.assertEqual(row['path'], str(self.a))
        self.assertEqual(row['interval'], 86400)

    def test_windows_model_paths_preserve_junction_identity(self):
        from drive_manager.models import windows_path
        # Conversion is lexical, even when the path may be an existing junction.
        with patch('drive_manager.models.subprocess.run', side_effect=AssertionError('must not resolve junction')):
            self.assertEqual(windows_path('/mnt/d/models/publisher/repository'),
                             'D:\\models\\publisher\\repository')

    def test_pending_shallow_scan_can_be_upgraded_to_recursive(self):
        self.file('one/two/nested.bin')
        first = self.store.scan(str(self.a), 0)
        second = self.store.scan(str(self.a), -1)
        self.assertEqual(first, second)
        self.store.start()
        self.wait_job(first)
        with self.store.db() as db:
            self.assertIsNotNone(db.execute('SELECT * FROM entries WHERE path=?',
                                           (str(self.a / 'one/two/nested.bin'),)).fetchone())

    def test_rescan_removes_metadata_for_missing_subtrees(self):
        import shutil
        self.file('sub/nested.bin')
        job = self.store.scan(str(self.a))
        self.store.start(); self.wait_job(job)
        shutil.rmtree(self.a / 'sub')
        job = self.store.scan(str(self.a))
        self.wait_job(job)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM entries').fetchone()[0], 0)

    def test_paused_partial_copy_resumes_with_verified_prefix(self):
        src = self.file(data=b'X' * (20 * 1024**2))
        src, dst, job = self.transfer(source=src)
        original_check = self.store.check
        count = 0
        def pause(ident):
            nonlocal count
            count += 1
            if count == 3:
                self.store.control(ident, 'pause')
            original_check(ident)
        with patch.object(self.store, 'check', side_effect=pause):
            with self.assertRaises(Deferred):
                self.store.run_transfer(job)
        partial = dst.parent / ('.drive-manager-' + job['id'] + '.part')
        self.assertGreater(partial.stat().st_size, 0)
        self.assertFalse(dst.exists())
        self.store.control(job['id'], 'resume')
        with self.store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job['id'],))
        self.complete(job)
        self.assertEqual(digest(src), digest(dst))

    def test_cancelled_transfer_can_be_proposed_fresh(self):
        src, dst, job = self.transfer()
        self.store.control(job['id'], 'cancel')
        fresh = self.store.propose(str(src), str(dst))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT status FROM candidates WHERE id=?', (fresh,)).fetchone()[0], 'review')

    def test_move_recovery_is_outside_application_subtree(self):
        src = self.file('application/files/item.bin')
        src, dst, job = self.transfer('move', source=src)
        self.complete(job)
        receipt = json.loads((self.store.state / 'receipts' / (job['id'] + '.json')).read_text())
        recovery = Path(receipt['recovery'])
        self.assertEqual(recovery, self.a / '.drive-manager-recovery' / job['id'] / src.name)
        self.assertEqual(recovery.read_bytes(), dst.read_bytes())

    def test_redirected_recovery_path_never_receives_original(self):
        src, dst, job = self.transfer('move')
        outside = self.base / 'outside'
        outside.mkdir()
        (self.a / '.drive-manager-recovery').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Recovery storage is redirected'):
            self.store.run_transfer(job)
        self.assertTrue(src.exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_inventory_rolls_up_nested_folders_and_bounds_duplicate_samples(self):
        for number in range(9):
            self.file(f'parent/child{number}/same.bin', b'12345')
        ident = self.store.scan(str(self.a))
        self.store.start(); self.wait_job(ident)
        inventory = self.store.inventory_summary()
        parent = next(row for row in inventory['folders'] if row['path'] == str(self.a / 'parent'))
        self.assertEqual(parent['size'], 45)
        self.assertEqual(parent['files'], 9)
        duplicate = inventory['duplicates'][0]
        self.assertEqual(duplicate['copies'], 9)
        self.assertEqual(len(duplicate['sample_paths']), 6)

    def test_move_updates_inventory_without_waiting_for_next_scan(self):
        src = self.file('active/item.bin')
        scan = self.store.scan(str(self.a))
        self.store.start(); self.wait_job(scan)
        self.store.inventory_summary()
        # Run the verified transfer directly so the assertions do not depend on worker timing.
        self.store.stop.set()
        for worker in self.store.threads:
            worker.join(5)
        self.store.stop.clear()
        src, dst, job = self.transfer('move', source=src)
        self.complete(job)
        with self.store.db() as db:
            self.assertIsNone(db.execute('SELECT * FROM entries WHERE path=?', (str(src),)).fetchone())
            self.assertIsNotNone(db.execute('SELECT * FROM entries WHERE path=?', (str(dst),)).fetchone())
        self.assertEqual(self.store.inventory_summary()['totals']['entries'], 1)

    def test_missing_used_model_copies_require_review_and_respect_rejection(self):
        import shutil
        from drive_manager.models import propose_missing
        left, right = self.model_pair()
        shutil.rmtree(right)
        history = self.base / 'history.json'
        history.write_text(json.dumps({'json': [['publisher/repository/model.gguf', {'lastLoadedTimestamp': 12345}]]}))
        proposed = propose_missing(self.store, history)
        self.assertEqual(len(proposed), 1)
        with self.store.db() as db:
            row = db.execute('SELECT * FROM candidates WHERE id=?', (proposed[0],)).fetchone()
            self.assertEqual(row['kind'], 'copy')
            self.assertEqual(row['status'], 'review')
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        self.store.reject(proposed)
        self.assertEqual(propose_missing(self.store, history), [])

    def test_policy_revocation_prevents_new_automatic_execution(self):
        src = self.file('archive/item.bin')
        policy = self.store.policy(str(src.parent), str(self.b / 'archive'), 'copy', False)
        original_approve = self.store.approve
        def revoke_before_approval(*args, **kwargs):
            with self.store.db() as db:
                db.execute('DELETE FROM policies WHERE id=?', (policy,))
            return original_approve(*args, **kwargs)
        with patch.object(self.store, 'approve', side_effect=revoke_before_approval):
            with self.assertRaisesRegex(ValueError, 'Standing permission was removed'):
                self.store.propose(str(src), str(self.b / 'archive/item.bin'), automatic=True, policy_id=policy)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        self.assertTrue(src.exists())


if __name__ == '__main__':
    unittest.main()
