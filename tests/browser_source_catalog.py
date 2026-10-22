"""Read-only source search, pagination, live evidence and archive-path linking."""
import sys
from pathlib import Path
import threading
sys.path.insert(0,str(Path(__file__).parent))
from test_sources import SourceCatalogTests
from drive_manager.server import make_server
from playwright.sync_api import sync_playwright,expect


def main():
    fixture=SourceCatalogTests('test_search_pagination_curated_roles_and_unknown_status_are_read_only');fixture.setUp()
    server=None
    try:
        fixture.evidence();before=fixture.metadata.read_bytes()
        server=make_server(fixture.store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/home/cosgroma/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',headless=True)
            page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/workspace-archive')
            summary=page.locator('#source-summary');expect(summary).to_contain_text('29 known source paths')
            page.get_by_role('button',name='Next sources',exact=True).click();expect(summary).to_contain_text('Showing 21–29')
            page.locator('#source-query').fill('D:\\wksp\\project-03');expect(summary).to_contain_text('of 1 matches')
            expect(page.locator('#source-results')).to_contain_text('/mnt/d/wksp/project-03')
            page.locator('#source-query').fill('preserved-only');expect(page.locator('#source-results')).to_contain_text(fixture.old)
            page.locator('#source-coverage').select_option('archived');expect(summary).to_contain_text('of 1 matches')
            page.locator('#source-root').select_option('/mnt/h');expect(summary).to_contain_text('of 0 matches')
            expect(page.locator('#source-results')).to_contain_text('does not establish that a missing source is lost')
            page.locator('#source-root').select_option('all');expect(summary).to_contain_text('of 1 matches')
            page.get_by_role('button',name='Show preservation records',exact=True).click()
            expect(page.locator('#archive-search')).to_have_value(fixture.old)
            expect(page.locator('#manifest-results')).to_contain_text(fixture.dest)
            page.locator('#source-results details summary').click()
            expect(page.locator('#source-results')).to_contain_text('not a current status check')
            with page.expect_response(lambda r:'/api/workspace/sources?' in r.url,timeout=20000):pass
            expect(page.locator('#source-results details')).to_have_attribute('open','')
            expect(page.locator('#source-query')).to_have_value('preserved-only')
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
            assert not errors,errors;assert fixture.metadata.read_bytes()==before
            with fixture.store.db() as db:assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==3
            browser.close()
            print('Source search: pagination, Windows paths, preserved branch refs, evidence/location filters, unknown-source wording, physical archive manifest linking, desktop/mobile fit and no mutations verified')
    finally:
        if server:server.shutdown();server.server_close();thread.join()
        fixture.doCleanups()


if __name__=='__main__':main()
