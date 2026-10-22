"""Opt-in WSL/NTFS regression check; uses disposable folders on D: only.
Run: PYTHONPATH=. python3 tests/native_manifest_check.py
"""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from drive_manager.core import Store
from drive_manager.manifests import enqueue_manifest,run_manifest,catalog,enumerate_tree,entries,file_signature,NATIVE_SCRIPT
from drive_manager.models import windows_path,create_junction,powershell


def main():
    with tempfile.TemporaryDirectory(prefix='workspace-native-check-',dir='/mnt/d') as temp, tempfile.TemporaryDirectory() as state:
        base=Path(temp);source=base/'source';source.mkdir();path=source/'hidden';path.write_bytes(b'preserve this payload')
        encoded=base64.b64encode(windows_path(path).encode()).decode()
        script="$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+encoded+"'));Set-Content -LiteralPath $p -Stream review -Value ([byte[]](65,66,67)) -Encoding Byte;$f=Get-Item -LiteralPath $p -Force;$f.Attributes=$f.Attributes -bor [IO.FileAttributes]::Hidden"
        proc=subprocess.run(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True)
        if proc.returncode:raise RuntimeError(proc.stderr)
        empty=source/'empty';empty.mkdir()
        # .NET Framework's path validator rejects ADS paths; create only these
        # disposable fixture streams through the same explicit Win32 binding.
        setup=NATIVE_SCRIPT.split('$root=')[0]+r'''
foreach($p in @($x.root,$x.child)){
 $h=[WorkspaceNativeStreams]::CreateFile($p+':directory-note',1073741824,7,[IntPtr]::Zero,2,0,[IntPtr]::Zero)
 if($h.IsInvalid){throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())}
 try {$writer=[IO.FileStream]::new($h,[IO.FileAccess]::Write);try{$writer.Write([byte[]](68,73,82),0,3)}finally{$writer.Dispose()}}finally{$h.Dispose()}
}
'''
        powershell(setup,{'root':windows_path(source),'child':windows_path(empty)})
        before=file_signature(path);before_root=file_signature(source);before_empty=file_signature(empty)
        store=Store(state,['/mnt/d'],reserve=0);ident=enqueue_manifest(store,str(source))
        with store.db() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(ident,))
            job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone())
        run_manifest(store,job);result=catalog(store)[0]['result']
        assert result['files']==1 and result['named_streams']==3 and result['named_stream_bytes']==9
        assert result['named_stream_scope']=='files-and-directories'
        assert file_signature(path)==before,'Native inspection changed the source identity or timestamps'
        assert file_signature(source)==before_root and file_signature(empty)==before_empty,'Directory stream inspection changed its source'
        with sqlite3.connect(result['manifest']) as db:
            metadata=json.loads(db.execute("SELECT native FROM entries WHERE relative='hidden'").fetchone()[0])
            root_metadata=json.loads(db.execute("SELECT native FROM entries WHERE relative='.'").fetchone()[0])
            child_metadata=json.loads(db.execute("SELECT native FROM entries WHERE relative='empty'").fetchone()[0])
        assert metadata['attributes'] & 2
        assert metadata['sddl'] and metadata['streams'][0]['sha256']==hashlib.sha256(b'ABC').hexdigest()
        assert root_metadata['streams'][0]['sha256']==hashlib.sha256(b'DIR').hexdigest()
        assert child_metadata['streams'][0]['sha256']==hashlib.sha256(b'DIR').hexdigest()
        outside=base/'outside';outside.mkdir();(outside/'unique.txt').write_text('external data')
        link=source/'junction';create_junction(link,outside)
        try:
            output=Path(state)/'junction.jsonl';enumerate_tree(source,output,lambda:None)
            records=dict(entries(output))
            assert records['junction']['kind']=='reparse'
            assert not any('unique.txt' in name for name in records)
        finally:powershell('[IO.Directory]::Delete($x.source)',{'source':windows_path(link)})
        protected=source/'offline-dir';protected.mkdir();(protected/'not-traversed').write_text('leave offline content untouched')
        powershell('$f=Get-Item -LiteralPath $x.path -Force;$f.Attributes=$f.Attributes -bor [IO.FileAttributes]::Offline',{'path':windows_path(protected)})
        output=Path(state)/'protected.jsonl';enumerate_tree(source,output,lambda:None);records=dict(entries(output))
        assert records['offline-dir']['kind']=='protected'
        assert not any(name.startswith('offline-dir/') for name in records)
        print('Native file/root/child-directory ADS hashes, ACLs, unchanged source identities/timestamps, no-follow junctions and no traversal of offline directories passed')


if __name__=='__main__':main()
