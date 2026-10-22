"""Exercise additive full-file backup creation and catalog visibility."""
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).parent))
from test_snapshots import FullFileSnapshotTests
from drive_manager.server import make_server
from playwright.sync_api import sync_playwright,expect


def main():
    fixture=FullFileSnapshotTests();fixture.setUp();server=None;workers=[]
    try:
        identifiers=fixture.capture();server=make_server(fixture.store,0)
        workers=[threading.Thread(target=server.serve_forever,daemon=True),threading.Thread(target=fixture.store.worker,args=('workspace',),daemon=True)]
        for worker in workers:worker.start()
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/home/cosgroma/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',headless=True)
            page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('**/api/workspace/snapshots',lambda route:route.fulfill(status=404,body='{}',content_type='application/json'))
            page.goto(f'http://127.0.0.1:{server.server_port}/workspace-archive')
            expect(page.locator('#snapshot-notice')).to_contain_text('Full-file backups are preparing')
            expect(page.locator('#snapshot-submit')).to_be_disabled()
            page.unroute('**/api/workspace/snapshots');page.reload()
            expect(page.locator('#snapshot-manifests option')).to_have_count(2)
            page.locator('#snapshot-manifests').select_option(identifiers)
            page.wait_for_timeout(4500)
            assert page.locator('#snapshot-manifests').evaluate('(el)=>el.selectedOptions.length')==2
            page.locator('#snapshot-form input[name=archive_root]').fill(str(fixture.archive))
            page.locator('#snapshot-submit').click()
            expect(page.locator('#snapshot-notice')).to_contain_text('Full-file backup queued')
            expect(page.locator('#snapshot-results')).to_contain_text('Verified full-file backup',timeout=40000)
            page.locator('#source-coverage').select_option('snapshot')
            expect(page.locator('#source-summary')).to_contain_text('of 2 matches')
            expect(page.locator('#source-results')).to_contain_text('Full-file backup independently restored and verified')
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),width
            assert not errors,errors
            assert (fixture.first/'dirty.txt').read_text()=='unique local edits'
            browser.close();print('Full-file backup queued through local page, independently restored, searchable for both sources; selections survived polling; both layouts fit; originals unchanged; no JS errors')
    finally:
        fixture.store.stop.set()
        if server:server.shutdown();server.server_close()
        for worker in workers:worker.join(5)
        fixture.doCleanups()


if __name__=='__main__':main()
