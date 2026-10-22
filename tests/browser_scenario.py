"""Optional browser integration scenario; uses an installed Playwright and Chromium."""
from pathlib import Path
import tempfile
import threading
import time

from playwright.sync_api import sync_playwright, expect

from drive_manager.core import Store
from drive_manager.server import make_server
from drive_manager.workspaces import git
from drive_manager import manifests, relocations


def main():
    chromium = '/home/cosgroma/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell'
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        a, b = base / 'A', base / 'B'
        a.mkdir(); b.mkdir()
        store = Store(base / 'state', [a, b], reserve=0)
        for index in range(200):
            child = a / 'inventory' / str(index)
            child.mkdir(parents=True)
            (child / 'file').write_bytes(b'indexed data')
        first, second = a / 'copy.bin', a / 'move.bin'
        first.write_bytes(b'copy data' * 1000); second.write_bytes(b'move data' * 1000)
        store.propose(str(first), str(b / first.name), 'copy')
        store.propose(str(second), str(b / second.name), 'move')
        project=a/'historical-project';project.mkdir();git(project,'init')
        git(project,'config','user.name','Browser Check');git(project,'config','user.email','browser@example.invalid')
        (project/'code.txt').write_text('historical source');git(project,'add','.');git(project,'commit','-m','fixture')
        manifest=manifests.enqueue_manifest(store,str(project))
        with store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(manifest,))
            manifest_job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(manifest,)).fetchone())
        manifests.run_manifest(store,manifest_job)
        with store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(manifest,))
        archive=relocations.propose(store,manifest)
        scan = store.scan(str(a / 'inventory'))
        original = store._scan_directory
        browser_ready = threading.Event()
        scan_entered = threading.Event()
        def paced_scan(*args):
            scan_entered.set()
            if not browser_ready.wait(30):
                raise ValueError('Browser scenario startup timed out')
            time.sleep(.04)
            return original(*args)
        store._scan_directory = paced_scan
        server = make_server(store, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        store.start()
        errors = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=chromium, headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('#connection')).to_contain_text('Connected')
                assert scan_entered.wait(5), 'Inventory worker did not enter its directory checkpoint'
                browser_ready.set()
                with store.db() as db:
                    assert db.execute('SELECT status FROM jobs WHERE id=?', (scan,)).fetchone()[0] == 'running'
                page.get_by_label('Select visible transfers (up to 100)').check()
                expect(page.locator('#selected-count')).to_have_text('3')
                page.get_by_role('button', name='Approve selected').click()
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    state = store.snapshot()
                    transfers = [job for job in state['jobs'] if job['kind'] == 'transfer']
                    if len(transfers) == 3 and all(job['status'] == 'completed' for job in transfers):
                        break
                    assert not any(job['status'] == 'blocked' for job in transfers), transfers
                    time.sleep(.1)
                else:
                    raise AssertionError('Approved transfers did not finish')
                assert first.exists() and not second.exists()
                assert (b / first.name).read_bytes() == b'copy data' * 1000
                assert (b / second.name).read_bytes() == b'move data' * 1000
                assert len(list((a / '.drive-manager-recovery').glob('*/move.bin'))) == 1
                assert project.is_symlink() and (project/'code.txt').read_text()=='historical source'
                assert not errors, errors
                browser.close()
                print('BROWSER APPROVAL PASSED: checkbox approval while indexing; copy, recoverable file move and complete archival relocation executed and verified')
        finally:
            browser_ready.set()
            store.stop.set(); server.shutdown(); server.server_close(); thread.join()
            for worker in store.threads:
                worker.join(5)


if __name__ == '__main__':
    main()
