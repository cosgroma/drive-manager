"""Show a verified named-ref archive without implying a default HEAD was chosen."""
import sys
from pathlib import Path
import threading
sys.path.insert(0,str(Path(__file__).parent))
from test_workspaces import WorkspaceArchiveTests
from drive_manager.workspaces import run_history
from drive_manager.server import make_server
from playwright.sync_api import sync_playwright,expect


def main():
    fixture=WorkspaceArchiveTests('test_named_history_with_unborn_default_is_restored_without_source_repair');fixture.setUp();server=None
    try:
        bare,job=fixture.unborn_bare();before=(bare/'HEAD').read_bytes()
        broken=bare/'refs/heads/develop';broken.parent.mkdir(parents=True,exist_ok=True);broken.write_bytes(b'')
        run_history(fixture.store,job)
        with fixture.store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(job['id'],))
        server=make_server(fixture.store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/home/cosgroma/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',headless=True)
            page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/workspace-archive')
            page.locator('#archive-search').fill('unselected-default')
            expect(page.locator('#archive-results')).to_contain_text('unresolved default HEAD (refs/heads/unselected-default)')
            expect(page.locator('#archive-results')).to_contain_text('Verified readable Git history · source warnings')
            expect(page.locator('#archive-results')).to_contain_text('Original ref metadata was not repaired')
            page.locator('#source-query').fill('unselected-default')
            expect(page.locator('#source-summary')).to_contain_text('of 1 matches')
            page.locator('#source-results details summary').click()
            expect(page.locator('#source-results')).to_contain_text('unresolved default HEAD: refs/heads/unselected-default')
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
            assert not errors,errors;assert (bare/'HEAD').read_bytes()==before;assert broken.read_bytes()==b''
            browser.close()
            print('Unresolved symbolic HEAD is explicitly labeled and searchable; verified history does not imply a branch was chosen; source HEAD unchanged; both layouts fit with no JS errors')
    finally:
        if server:server.shutdown();server.server_close();thread.join()
        fixture.doCleanups()


if __name__=='__main__':main()
