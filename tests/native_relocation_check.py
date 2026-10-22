"""Opt-in WSL check: verified native relocation/legacy Git URL/restore on disposable D: folders."""
import base64
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from drive_manager.core import Store
from drive_manager.workspaces import git,refs
from drive_manager import manifests,relocations
from drive_manager.models import windows_path,is_junction,powershell


def claim(store, ident):
    with store.db() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
        return dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())


def main():
    with tempfile.TemporaryDirectory(prefix='workspace-relocation-check-',dir='/mnt/d') as temp,tempfile.TemporaryDirectory() as state:
        base=Path(temp);origin=base/'origin';origin.mkdir();git(origin,'init')
        git(origin,'config','user.name','Native Check');git(origin,'config','user.email','native@example.invalid')
        (origin/'unique.txt').write_text('preserve this committed version');git(origin,'add','.');git(origin,'commit','-m','native fixture');git(origin,'tag','v1')
        source=base/'repos'/'libs'/'fixture.git';source.parent.mkdir(parents=True);git(origin,'clone','--bare','--no-hardlinks',str(origin),str(source))
        git(source,'config','--remove-section','remote.origin')
        note=source/'hidden-notes';note.write_bytes(b'untracked archive data')
        encoded=base64.b64encode(windows_path(note).encode()).decode()
        powershell("$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+encoded+"'));Set-Content -LiteralPath $p -Stream review -Value ([byte[]](65,66,67)) -Encoding Byte;$f=Get-Item -LiteralPath $p -Force;$f.Attributes=$f.Attributes -bor [IO.FileAttributes]::Hidden",{})
        setup=manifests.NATIVE_SCRIPT.split('$root=')[0]+r'''
$h=[WorkspaceNativeStreams]::CreateFile($x.root+':directory-note',1073741824,7,[IntPtr]::Zero,2,0,[IntPtr]::Zero)
if($h.IsInvalid){throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())}
try{$writer=[IO.FileStream]::new($h,[IO.FileAccess]::Write);try{$writer.Write([byte[]](68,73,82),0,3)}finally{$writer.Dispose()}}finally{$h.Dispose()}
'''
        powershell(setup,{'root':windows_path(source)})
        store=Store(state,['/mnt/d'],reserve=0)
        ident=manifests.enqueue_manifest(store,str(source));manifests.run_manifest(store,claim(store,ident))
        with store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(ident,))
        before=refs(source)
        print('Fixture local config keys:',git(source,'config','--local','--name-only','--list').splitlines(),flush=True)
        candidate_id=relocations.propose(store,ident,automatic=True,archive_root=base/'archive')
        with store.db() as db:candidate=dict(db.execute('SELECT * FROM candidates WHERE id=?',(candidate_id,)).fetchone())
        job=claim(store,candidate['job_id']);destination=Path(candidate['destination'])
        try:
            relocations.run(store,job,candidate)
            assert is_junction(source,destination)
            assert refs(source)==before
            assert (source/'hidden-notes').read_bytes()==b'untracked archive data'
            clone=Path(state)/'restored-via-old-url.git';git(origin,'clone','--mirror','--no-hardlinks',str(source),str(clone))
            assert refs(clone)==before
            windows_git=Path('/mnt/c/Program Files/Git/cmd/git.exe')
            if windows_git.exists():
                result=subprocess.run([str(windows_git),'--git-dir',windows_path(source),'show-ref'],capture_output=True,text=True,timeout=30)
                assert result.returncode==0,result.stderr
                assert all(sha in result.stdout for name,sha in before.items() if name!='HEAD')
            receipt=json.loads((store.state/'workspace-relocations'/(job['id']+'.json')).read_text())
            assert receipt['native_metadata_verified'] and receipt['space_reclaimed']==0
            assert receipt['legacy_named_streams_verified']==2
            # New data and a new branch appeared after archival. The original
            # baseline must hold; only a reviewed fresh baseline may restore it.
            (source/'newer-data').write_bytes(b'new work through the legacy junction')
            git(source,'update-ref','refs/heads/after-archive',before['HEAD'])
            newer_refs=refs(source)
            restore=relocations.enqueue_restore(store,job['id'])
            try:relocations.run_restore(store,claim(store,restore))
            except ValueError:pass
            else:raise AssertionError('Old baseline incorrectly accepted a changed archive')
            assert is_junction(source,destination) and (source/'newer-data').exists()
            store.control(restore,'cancel')
            fresh=manifests.enqueue_manifest(store,str(destination));manifests.run_manifest(store,claim(store,fresh))
            with store.db() as db:db.execute("UPDATE jobs SET status='completed' WHERE id=?",(fresh,))
            reviewed=relocations.propose_reviewed_restore(store,job['id'],fresh)
            store.approve([reviewed])
            with store.db() as db:restoration_job=db.execute('SELECT job_id FROM candidates WHERE id=?',(reviewed,)).fetchone()[0]
            store.run_transfer(claim(store,restoration_job))
            assert source.resolve()==source and not destination.exists()
            assert refs(source)==newer_refs and (source/'hidden-notes').read_bytes()==b'untracked archive data'
            assert (source/'newer-data').read_bytes()==b'new work through the legacy junction'
            receipt=json.loads((store.state/'workspace-relocations'/(job['id']+'.json')).read_text())
            assert receipt['manifest']==ident and receipt['restore_manifest']==fresh
            print('Native full-tree archive, hidden file/ADS/ACL preservation, legacy clone, stale-restore hold and checkbox-reviewed fresh-baseline restoration preserved newer files and refs')
        finally:
            if source.exists() and destination.exists() and is_junction(source,destination):
                powershell('[IO.Directory]::Delete($x.source)',{'source':windows_path(source)})


if __name__=='__main__':main()
