"""Compare real fixture manifests through the local UI without changing sources."""
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).parent))
from test_snapshot_comparisons import SnapshotComparisonTests
from drive_manager.server import make_server
from playwright.sync_api import sync_playwright,expect


def main():
    fixture=SnapshotComparisonTests('test_working_payload_equality_does_not_hide_unique_git_internals');fixture.setUp();server=None
    try:
        path=fixture.right/'.git/objects/unreachable';path.write_bytes(b'a distinct unnamed Git object')
        a,b=fixture.capture(fixture.left),fixture.capture(fixture.right)
        before=path.read_bytes();server=make_server(fixture.store,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/home/cosgroma/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',headless=True)
            page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/workspace-archive')
            left,right=page.locator('#comparison-left'),page.locator('#comparison-right')
            expect(left.locator('option')).to_have_count(3)
            left.select_option(a);right.select_option(b)
            with page.expect_response(lambda r:r.url.endswith('/api/workspace/manifests'),timeout=10000):pass
            expect(left).to_have_value(a);expect(right).to_have_value(b)
            page.get_by_role('button',name='Compare snapshots',exact=True).click()
            expect(page.get_by_role('heading',name='Full-tree comparison',exact=True)).to_be_visible()
            page.locator('#comparison-results details summary').filter(has_text='Recorded differences').first.click()
            expect(page.locator('#comparison-results')).to_contain_text('.git/objects/unreachable')
            expect(page.locator('#comparison-results')).to_contain_text('Both manifest database digests verified')
            expect(page.locator('#archive-notice')).to_contain_text('No move or deletion has been approved')
            page.locator('#comparison-scope').select_option('working')
            page.get_by_role('button',name='Compare snapshots',exact=True).click()
            heading=page.get_by_role('heading',name='Working-file comparison',exact=True)
            expect(heading).to_be_visible()
            working=page.locator('#comparison-results > article').filter(has=heading)
            expect(working).to_contain_text('0 different');expect(working).to_contain_text('Git internals and directories are excluded')
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
            assert not errors,errors;assert path.read_bytes()==before
            with fixture.store.db() as db:
                assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==2
                assert db.execute('SELECT count(*) FROM candidates').fetchone()[0]==0
            browser.close()
            print('Browser full comparison exposed unique Git data; working-only comparison labeled exclusions; manifest selections survived refresh; desktop/mobile fit; no JS errors or source/job mutations')
    finally:
        if server:server.shutdown();server.server_close();thread.join()
        fixture.doCleanups()


if __name__=='__main__':main()
