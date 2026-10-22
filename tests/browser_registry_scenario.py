"""Checkbox approval of metadata-only registry removal during independent indexing."""
import json
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from drive_manager.core import Store
from drive_manager.server import make_server
from drive_manager import registry


def main():
    tool=Path.home()/'workspace/scripts/wksp.py'
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);workspace=root/'workspace';workspace.mkdir();drive=root/'A';drive.mkdir();scan_drive=root/'C';scan_drive.mkdir()
        inventory=workspace/'.wksp.json';missing=workspace/'missing-support';canonical=workspace/'canonical';canonical.mkdir();(canonical/'user.txt').write_text('keep my work')
        data={'schemaVersion':1,'workspaceRoot':str(workspace),'statusValues':['active','dormant'],
              'projects':[{'id':'parent','name':'Keep project metadata','status':'active','worktrees':[{'path':str(canonical),'status':'active','role':'canonical'}],
                           'relatedRepositories':[{'path':str(missing),'status':'dormant','role':'supporting repository','dirtyFiles':2}]}],
              'externalProjects':[],'sergeant':{'components':[],'designs':[],'engines':[]}}
        inventory.write_text(json.dumps(data,indent=2)+'\n')
        store=Store(root/'state',[drive,scan_drive],reserve=0)
        for i in range(200):
            child=scan_drive/str(i);child.mkdir();(child/'file').write_text('indexed')
        ready=threading.Event();entered=threading.Event();busy_entered=threading.Event();busy_release=threading.Event();original=store._scan_directory
        first,second=drive/'busy-a',drive/'busy-b';first.write_text('same');second.write_text('same')
        def hold_transfer(job):
            busy_entered.set()
            if not busy_release.wait(60):raise ValueError('Busy transfer fixture timed out')
        store.run_compare=hold_transfer
        busy=store.enqueue('compare',str(first),{'other':str(second)})
        def paced(*args):
            entered.set()
            if not ready.wait(60):raise ValueError('Browser did not become ready')
            time.sleep(.04);return original(*args)
        store._scan_directory=paced
        with patch.object(registry,'registry_path',return_value=inventory),patch.object(registry,'tool_path',return_value=tool):
            ident=registry.propose_missing(store,str(missing),'Remove this missing registration only; retain its exact recovery record')
            scan=store.scan(str(scan_drive));server=make_server(store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();store.start()
            errors=[]
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch(executable_path='/home/cosgroma/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',headless=True)
                    page=browser.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    checkbox=page.get_by_label('Select registry_remove '+str(missing),exact=True)
                    expect(checkbox).to_be_enabled();assert entered.wait(10);assert busy_entered.wait(10);ready.set()
                    with store.db() as db:assert db.execute('SELECT status FROM jobs WHERE id=?',(scan,)).fetchone()[0]=='running'
                    checkbox.check();page.get_by_role('button',name='Approve selected').click()
                    deadline=time.monotonic()+30
                    while time.monotonic()<deadline:
                        with store.db() as db:row=db.execute('SELECT c.status,j.status,j.message FROM candidates c LEFT JOIN jobs j ON j.id=c.job_id WHERE c.id=?',(ident,)).fetchone()
                        if row[0]=='completed':break
                        assert row[1]!='blocked',tuple(row)
                        time.sleep(.1)
                    else:raise AssertionError('Registry approval did not finish')
                    with store.db() as db:assert db.execute('SELECT status FROM jobs WHERE id=?',(busy,)).fetchone()[0]=='running'
                    actual=json.loads(inventory.read_text());assert actual['projects'][0]['relatedRepositories']==[]
                    assert actual['projects'][0]['worktrees']==data['projects'][0]['worktrees']
                    assert (canonical/'user.txt').read_text()=='keep my work' and not missing.exists()
                    assert len(list((store.state/'registry-backups').glob('*.json')))==1
                    assert not errors,errors;browser.close()
                    print('Registry checkbox executed while indexing and a busy transfer continued; only the missing metadata record changed; recovery backup retained')
            finally:
                ready.set();busy_release.set();store.stop.set();server.shutdown();server.server_close();thread.join()
                for worker in store.threads:worker.join(5)


if __name__=='__main__':main()
