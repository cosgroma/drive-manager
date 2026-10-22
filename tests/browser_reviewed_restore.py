"""Fresh-baseline restoration through the actual local HTTP/checkbox workflow."""
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).parent))
from test_reviewed_restore import ReviewedRestoreTests
from drive_manager.server import make_server
from playwright.sync_api import sync_playwright,expect


def main():
    fixture=ReviewedRestoreTests('test_post_review_edit_blocks_without_removing_alias_or_new_work')
    fixture.setUp();server=None;ready=threading.Event()
    try:
        fixture.changed_archive();store=fixture.store
        scan_root=fixture.root/'C';scan_root.mkdir()
        for i in range(400):
            child=scan_root/str(i);child.mkdir();(child/'file').write_text('continue indexing')
        with store.db() as db:db.execute("UPDATE settings SET value=? WHERE key='roots'",(json.dumps([str(fixture.drive),str(scan_root)]),))
        entered=threading.Event();original_scan=store._scan_directory
        def paced(*args):
            entered.set()
            if not ready.wait(60):raise ValueError('Browser indexing fixture timed out')
            time.sleep(.08);return original_scan(*args)
        store._scan_directory=paced
        scan=store.scan(str(scan_root));server=make_server(store,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();store.start()
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/home/cosgroma/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',headless=True)
            page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            url=f'http://127.0.0.1:{server.server_port}'
            page.goto(url+'/workspace-archive')
            page.get_by_text('Restore an archive that has newer work',exact=True).click()
            select=page.get_by_label('Restore manifest for '+str(fixture.source),exact=True)
            expect(select).to_be_visible();select.select_option(fixture.fresh)
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
            page.get_by_role('button',name='Review restoration with fresh manifest',exact=True).click()
            expect(page.locator('#archive-notice')).to_contain_text('No move has been approved')
            with store.db() as db:proposal=dict(db.execute("SELECT * FROM candidates WHERE kind='workspace_restore_review'").fetchone())
            assert proposal['status']=='review' and fixture.source.is_symlink()
            page.goto(url+'/')
            checkbox=page.get_by_label('Select workspace_restore_review '+str(fixture.destination),exact=True)
            expect(checkbox).to_be_enabled();assert not checkbox.is_checked()
            assert entered.wait(10);ready.set();checkbox.check()
            page.get_by_role('button',name='Approve selected').click()
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                with store.db() as db:row=db.execute('SELECT c.status,j.status,j.message FROM candidates c JOIN jobs j ON j.id=c.job_id WHERE c.id=?',(proposal['id'],)).fetchone()
                if row and row[0]=='completed':break
                assert not row or row[1]!='blocked',tuple(row)
                time.sleep(.1)
            else:raise AssertionError('Reviewed restoration did not finish')
            with store.db() as db:assert db.execute('SELECT status FROM jobs WHERE id=?',(scan,)).fetchone()[0]=='running'
            assert not fixture.source.is_symlink() and not fixture.destination.exists()
            assert (fixture.source/'ignored-local-data').read_bytes()==b'untracked new data'
            assert not errors,errors
            browser.close()
            print('Fresh manifest selected; concrete restore proposal unchecked until approval; full restoration preserved newer data while another drive kept indexing; desktop/mobile fit; no JS errors')
    finally:
        ready.set();fixture.store.stop.set()
        if server:
            server.shutdown();server.server_close();thread.join()
            for worker in fixture.store.threads:worker.join(5)
        fixture.doCleanups()


if __name__=='__main__':main()
