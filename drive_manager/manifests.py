"""Resumable, full-tree content manifests. Manifests never authorize deletion."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import uuid

# Enumerate once per tree rather than launching PowerShell for each file. Never
# follow reparse points or read offline/encrypted content. Named stream payloads
# are hashed natively; default streams are hashed through no-follow Linux handles.
NATIVE_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Collections.Generic;
using Microsoft.Win32.SafeHandles;
public static class WorkspaceNativeStreams {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 public static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
 private struct FindStreamData {
  public long Size;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=296)] public string Name;
 }
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,ExactSpelling=true,SetLastError=true)]
 private static extern IntPtr FindFirstStreamW(string path,int level,out FindStreamData data,uint flags);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,ExactSpelling=true,SetLastError=true)]
 [return:MarshalAs(UnmanagedType.Bool)]
 private static extern bool FindNextStreamW(IntPtr handle,out FindStreamData data);
 [DllImport("kernel32.dll",SetLastError=true)]
 [return:MarshalAs(UnmanagedType.Bool)]
 private static extern bool FindClose(IntPtr handle);
 [DllImport("kernel32.dll",SetLastError=true)]
 private static extern bool DeviceIoControl(SafeFileHandle h,uint code,IntPtr input,int inputSize,byte[] output,int outputSize,out int returned,IntPtr overlap);
 [DllImport("kernel32.dll",SetLastError=true)]
 private static extern bool BackupRead(SafeFileHandle h,byte[] data,uint count,out uint read,bool abort,bool security,ref IntPtr context);
 [DllImport("kernel32.dll",SetLastError=true)]
 private static extern bool BackupSeek(SafeFileHandle h,uint low,uint high,out uint lowRead,out uint highRead,ref IntPtr context);
 private static void CheckLinkStreams(SafeFileHandle h) {
  IntPtr context=IntPtr.Zero;uint n;
  try {
   byte[] header=new byte[20];
   while(true) {
    if(!BackupRead(h,header,20,out n,false,false,ref context))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    if(n==0)break;if(n!=20)throw new InvalidOperationException("Truncated link backup stream header");
    uint id=BitConverter.ToUInt32(header,0);ulong size=BitConverter.ToUInt64(header,8);uint nameSize=BitConverter.ToUInt32(header,16);
    if(nameSize>65536)throw new InvalidOperationException("Unbounded link stream name");
    if(nameSize>0) {byte[] name=new byte[nameSize];if(!BackupRead(h,name,nameSize,out n,false,false,ref context)||n!=nameSize)throw new InvalidOperationException("Incomplete link stream name");}
    if(id==4 || (id!=8 && size!=0))throw new InvalidOperationException("Additional native link streams require another recovery format");
    if(size>0) {uint low,high;if(!BackupSeek(h,(uint)size,(uint)(size>>32),out low,out high,ref context)||(((ulong)high<<32)|low)!=size)throw new InvalidOperationException("Incomplete link backup stream traversal");}
   }
  } finally {BackupRead(h,null,0,out n,true,false,ref context);}
 }
 public static string ReparseRecord(string path) {
  using(var h=CreateFile(path,0x80000000,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
   if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   byte[] data=new byte[16384];int n;
   if(!DeviceIoControl(h,0x000900A8,IntPtr.Zero,0,data,data.Length,out n,IntPtr.Zero))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   string encoded=Convert.ToBase64String(data,0,n);CheckLinkStreams(h);return encoded;
  }
 }
 public sealed class StreamInfo {public string Stream;public long Length;}
 public static StreamInfo[] Enumerate(string path) {
  var result=new List<StreamInfo>();FindStreamData data;
  IntPtr handle=FindFirstStreamW(path,0,out data,0);
  if(handle==new IntPtr(-1)) {
   int error=Marshal.GetLastWin32Error();
   if(error==38)return result.ToArray();
   throw new System.ComponentModel.Win32Exception(error);
  }
  try {
   while(true) {
    string raw=data.Name;
    if(!String.Equals(raw,"::$DATA",StringComparison.OrdinalIgnoreCase)) {
     if(!raw.StartsWith(":")||!raw.EndsWith(":$DATA",StringComparison.OrdinalIgnoreCase))
      throw new InvalidOperationException("Unexpected NTFS stream type; source retained");
     result.Add(new StreamInfo {Stream=raw.Substring(1,raw.Length-7),Length=data.Size});
    }
    if(!FindNextStreamW(handle,out data)) {
     int error=Marshal.GetLastWin32Error();
     if(error!=38)throw new System.ComponentModel.Win32Exception(error);
     break;
    }
   }
  } finally {FindClose(handle);}
  return result.ToArray();
 }
}
'@
$root=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__SOURCE__'))
$todo=[Collections.Generic.Stack[string]]::new(); $todo.Push($root)
while($todo.Count -gt 0){
 $path=$todo.Pop(); $rel=if($path -eq $root){'.'}else{$path.Substring($root.Length+1).Replace('\','/')}
 try {
  $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
  $attrs=[int64]$item.Attributes; $dir=($attrs -band 16) -ne 0; $reparse=($attrs -band 1024) -ne 0
  $kind=if($reparse){'reparse'}elseif(($attrs -band 20480) -ne 0){'protected'}elseif($dir){'dir'}else{'file'}
  $sddl=$null; $streams=@(); $target=@()
  if($reparse){$target=@($item.Target)}else{
   $sddl=(Get-Acl -LiteralPath $path -ErrorAction Stop).Sddl
   if($kind -in @('file','dir')){
    foreach($stream in @([WorkspaceNativeStreams]::Enumerate($path))){
     $native=[WorkspaceNativeStreams]::CreateFile($path+':'+$stream.Stream,2147483648,7,[IntPtr]::Zero,3,0,[IntPtr]::Zero)
     if($native.IsInvalid){$native.Dispose();throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())}
     try {
      $reader=[IO.FileStream]::new($native,[IO.FileAccess]::Read)
      try {$h=[Security.Cryptography.SHA256]::Create();try{$sha=([BitConverter]::ToString($h.ComputeHash($reader))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}}finally{$reader.Dispose()}
     }finally{$native.Dispose()}
     $streams+=@{name=$stream.Stream;size=[int64]$stream.Length;sha256=$sha}
    }
   }
  }
  $ticks=([int64]$item.LastWriteTimeUtc.Ticks)-[int64]621355968000000000
  $record=@{relative=$rel;kind=$kind;size=if($dir){0}else{[int64]$item.Length};mtime_ns=$ticks*[int64]100;attributes=$attrs;sddl=$sddl;streams=@($streams|Sort-Object name);target=$target}
  if($reparse){$a=[WorkspaceNativeStreams]::ReparseRecord($path);$b=[WorkspaceNativeStreams]::ReparseRecord($path);if($a -cne $b){throw 'Reparse bytes changed during inventory'};$record.reparse_buffer_base64=$a;$record.reparse_additional_streams_absent=$true}
  [Console]::WriteLine(($record|ConvertTo-Json -Compress -Depth 8))
  if($kind -eq 'dir'){foreach($child in [IO.Directory]::EnumerateFileSystemEntries($path)){$todo.Push($child)}}
 } catch {[Console]::WriteLine((@{relative=$rel;kind='error';error=$_.Exception.Message}|ConvertTo-Json -Compress))}
}
'''

NATIVE_RECORD_SCRIPT = NATIVE_SCRIPT.replace('$root=', '\nAdd-Type -TypeDefinition @\'\nusing System;using System.Collections.Generic;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;\npublic static class LinkStreamObservation {\n [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFile(string p,uint a,uint s,IntPtr sec,uint d,uint f,IntPtr t);\n [DllImport("kernel32.dll",SetLastError=true)] static extern bool BackupRead(SafeFileHandle h,byte[] data,uint count,out uint read,bool abort,bool security,ref IntPtr context);\n [DllImport("kernel32.dll",SetLastError=true)] static extern bool BackupSeek(SafeFileHandle h,uint low,uint high,out uint lowRead,out uint highRead,ref IntPtr context);\n public sealed class StreamRecord {public uint id;public uint attributes;public ulong size;public string name;public string metadata_base64;public string metadata_sha256;}\n public static StreamRecord[] Read(string p) {\n  using(var h=CreateFile(p,0x80000000,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {\n   if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());\n   IntPtr context=IntPtr.Zero;uint n;var records=new List<StreamRecord>();\n   try {byte[] header=new byte[20];\n    while(true) {\n     if(!BackupRead(h,header,20,out n,false,false,ref context))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());\n     if(n==0)break;if(n!=20)throw new InvalidOperationException("Incomplete header");\n     if(records.Count>=32)throw new InvalidOperationException("Too many link streams");\n     uint id=BitConverter.ToUInt32(header,0);ulong size=BitConverter.ToUInt64(header,8);uint names=BitConverter.ToUInt32(header,16);\n     if((id!=2 && id!=8)||size==0||size>16384||names!=0||BitConverter.ToUInt32(header,4)!=0)throw new InvalidOperationException("Unsupported native link stream");\n     if(names>65536)throw new InvalidOperationException("Unbounded name");\n     byte[] name=new byte[names];if(names>0&&(!BackupRead(h,name,names,out n,false,false,ref context)||n!=names))throw new InvalidOperationException("Incomplete name");\n     var row=new StreamRecord {id=id,attributes=BitConverter.ToUInt32(header,4),size=size,name=System.Text.Encoding.Unicode.GetString(name)};\n     if(size>0 && (id==2||id==8) && size<=65536) {\n      byte[] data=new byte[(int)size];if(!BackupRead(h,data,(uint)size,out n,false,false,ref context)||n!=size)throw new InvalidOperationException("Incomplete metadata");row.metadata_base64=Convert.ToBase64String(data);using(var sha=System.Security.Cryptography.SHA256.Create()){row.metadata_sha256=BitConverter.ToString(sha.ComputeHash(data)).Replace("-","").ToLowerInvariant();}\n     } else if(size>0) {uint low,high;if(!BackupSeek(h,(uint)size,(uint)(size>>32),out low,out high,ref context)||(((ulong)high<<32)|low)!=size)throw new InvalidOperationException("Incomplete skip");}\n     records.Add(row);\n    }\n   }finally{BackupRead(h,null,0,out n,true,false,ref context);}\n   return records.ToArray();\n  }\n }\n}\n\'@\n'+'$root=',1).replace("  if($reparse){$a=[WorkspaceNativeStreams]::ReparseRecord($path);$b=[WorkspaceNativeStreams]::ReparseRecord($path);if($a -cne $b){throw 'Reparse bytes changed during inventory'};$record.reparse_buffer_base64=$a;$record.reparse_additional_streams_absent=$true}","  if($reparse){$a=@([LinkStreamObservation]::Read($path));$b=@([LinkStreamObservation]::Read($path));if((ConvertTo-Json -InputObject $a -Depth 6 -Compress) -cne (ConvertTo-Json -InputObject $b -Depth 6 -Compress)){throw 'Link backup metadata changed during inventory'};$record.link_backup_streams=$a}")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def file_signature(path):
    value = path.lstat()
    return dict(size=value.st_size, mtime_ns=value.st_mtime_ns, ctime_ns=value.st_ctime_ns,
                device=value.st_dev, inode=value.st_ino, mode=value.st_mode,
                uid=value.st_uid, gid=value.st_gid, nlink=value.st_nlink)


def checked_hash(path, expected, check):
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(path, flags)
    sha = hashlib.sha256()
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode): raise ValueError('File type changed: ' + str(path))
        def matches(s):
            return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_nlink) == tuple(expected[k] for k in ('device','inode','size','mtime_ns','ctime_ns','mode','nlink'))
        if not matches(s): raise ValueError('File changed before hashing: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            while chunk := handle.read(8 * 1024**2):
                check(); sha.update(chunk)
        if not matches(os.fstat(fd)) or file_signature(path) != expected:
            raise ValueError('File changed while hashing: ' + str(path))
    finally: os.close(fd)
    return sha.hexdigest()


def native_tree(source, output, check, preserve_native_link_records=False):
    from .models import windows_path
    payload = base64.b64encode(windows_path(source).encode()).decode()
    script = (NATIVE_RECORD_SCRIPT if preserve_native_link_records else NATIVE_SCRIPT).replace('__SOURCE__', payload)
    began = time.monotonic()
    with output.open('wb') as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
                                 '-NoProfile', '-NonInteractive', '-Command', script],
                                stdout=out, stderr=err, start_new_session=True)
        try:
            while proc.poll() is None:
                check()
                if time.monotonic()-began>7200: raise ValueError('Native metadata inventory exceeded two hours')
                time.sleep(.5)
            if proc.returncode:
                err.seek(0); raise ValueError('Native metadata inventory failed: ' + err.read(2000).decode(errors='replace'))
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait()


def verify_named_streams(source,database,check):
    """Read every expected NTFS stream through the legacy path, including root ADS."""
    from .models import windows_path
    count=0
    with tempfile.TemporaryFile() as payload,tempfile.TemporaryFile() as out,tempfile.TemporaryFile() as err:
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
            for index,(rel,raw) in enumerate(db.execute('SELECT relative,native FROM entries')):
                if index%128==0:check()
                for stream in json.loads(raw).get('streams',[]):
                    if not str(source).startswith('/mnt/'):raise ValueError('NTFS streams require a native legacy-path check')
                    payload.write((canonical({'path':windows_path(Path(source)/rel),'stream':stream})+'\n').encode())
                    count+=1
        if not count:return 0
        payload.seek(0)
        script=NATIVE_SCRIPT.split('$root=')[0]+r'''
$seen=0
while(($line=[Console]::ReadLine()) -ne $null){
 $entry=ConvertFrom-Json $line;$stream=$entry.stream
 $native=[WorkspaceNativeStreams]::CreateFile($entry.path+':'+$stream.name,2147483648,7,[IntPtr]::Zero,3,0,[IntPtr]::Zero)
 if($native.IsInvalid){$native.Dispose();throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())}
 try{
  $reader=[IO.FileStream]::new($native,[IO.FileAccess]::Read)
  try{
   if($reader.Length -ne $stream.size){throw 'Legacy-path named stream size differs'}
   $h=[Security.Cryptography.SHA256]::Create()
   try{$sha=([BitConverter]::ToString($h.ComputeHash($reader))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
   if($sha -ne $stream.sha256){throw 'Legacy-path named stream payload differs'}
  }finally{$reader.Dispose()}
 }finally{$native.Dispose()}
 $seen++
}
[Console]::WriteLine($seen)
'''
        proc=subprocess.Popen(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-Command',script],stdin=payload,stdout=out,stderr=err,start_new_session=True)
        began=time.monotonic()
        try:
            while proc.poll() is None:
                check()
                if time.monotonic()-began>7200:raise ValueError('Legacy named-stream verification exceeded two hours')
                time.sleep(.5)
            out.seek(0);err.seek(0)
            if proc.returncode or out.read().decode().strip()!=str(count):
                raise ValueError('Legacy named-stream verification failed: '+err.read(2000).decode(errors='replace'))
            check();return count
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()


def posix_tree(source, output, check):
    todo=[source]
    with output.open('w') as handle:
        while todo:
            check();path=todo.pop();rel=str(path.relative_to(source))
            try:
                sig=file_signature(path);mode=sig['mode']
                kind='dir' if stat.S_ISDIR(mode) else 'link' if stat.S_ISLNK(mode) else 'file' if stat.S_ISREG(mode) else 'special'
                attrs={name:base64.b64encode(os.getxattr(path,name,follow_symlinks=False)).decode() for name in os.listxattr(path,follow_symlinks=False)}
                value=dict(relative=rel,kind=kind,size=0 if kind=='dir' else sig['size'],mtime_ns=sig['mtime_ns'],xattrs=attrs)
                if kind=='link':value['target']=os.readlink(path)
                # Finish directory enumeration before publishing its record: a
                # permission failure must emit one error, never a duplicate path.
                children=[]
                if kind=='dir':
                    with os.scandir(path) as scan:children=[path / e.name for e in scan]
                handle.write(canonical(value)+'\n')
                todo.extend(children)
            except OSError as exc:handle.write(canonical(dict(relative=rel,kind='error',error=str(exc)))+'\n')


def enumerate_tree(source, output, check, preserve_native_link_records=False):
    if str(source).startswith('/mnt/'):
        if preserve_native_link_records:native_tree(source,output,check,True)
        else:native_tree(source,output,check)
    else:posix_tree(source,output,check)


def entries(output):
    seen_root=False
    with output.open(encoding='utf-8-sig') as handle:
        for line in handle:
            item=json.loads(line);rel=Path(item['relative'])
            if rel.is_absolute() or '..' in rel.parts:raise ValueError('Inventory contains a path outside its source')
            if item['relative']=='.':seen_root=True
            yield item['relative'],item
    if not seen_root:raise ValueError('Inventory omitted its source root')


def enqueue_manifest(store,source,preserve_wsl_file_links=False,preserve_native_link_records=False):
    from .workspaces import workspace_source
    src,_=workspace_source(store,source)
    if not src.is_dir():raise ValueError('Choose a directory for its full-tree manifest')
    if not isinstance(preserve_native_link_records,bool) or (preserve_native_link_records and preserve_wsl_file_links):raise ValueError('Choose one explicit link preservation format')
    if preserve_native_link_records and not str(src).startswith('/mnt/'):raise ValueError('Native link records require a Windows source')
    if not isinstance(preserve_wsl_file_links,bool):raise ValueError('Link preservation must be boolean')
    if preserve_wsl_file_links and not str(src).startswith('/mnt/'):raise ValueError('WSL native file-link mode requires a Windows source')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT id,payload FROM jobs WHERE kind='workspace_manifest' AND path=? AND status IN ('pending','running','paused')",(str(src),)).fetchone()
        if row:
            if json.loads(row[1]).get('preserve_wsl_file_links',False)!=preserve_wsl_file_links or json.loads(row[1]).get('preserve_native_link_records',False)!=preserve_native_link_records:raise ValueError('An inventory with different link preservation is already active')
            return row[0]
        ident=uuid.uuid4().hex
        db.execute("INSERT INTO jobs(id,kind,path,status,payload,created,updated) VALUES(?,'workspace_manifest',?,'pending',?,?,?)",(ident,str(src),json.dumps({'preserve_native_link_records':True}) if preserve_native_link_records else json.dumps({'preserve_wsl_file_links':True}) if preserve_wsl_file_links else '{}',time.time(),time.time()))
        db.execute('INSERT INTO workspace_manifests(job_id,source,updated) VALUES(?,?,?)',(ident,str(src),time.time()))
    store.event('Full-tree manifest queued, including ignored files and Git internals: '+str(src),ident)
    return ident


def catalog(store):
    with store.db() as db:
        rows=db.execute('SELECT a.*,j.status,j.message,j.files,j.bytes FROM workspace_manifests a JOIN jobs j ON j.id=a.job_id ORDER BY a.updated DESC').fetchall()
    return [dict(r,result=json.loads(r['result']) if r['result'] else None) for r in rows]


def run_manifest(store,job):
    from .workspaces import workspace_source
    source,root=workspace_source(store,job['path'])
    ident=job['id'];check=lambda:store.check(ident)
    preserve_links=json.loads(job['payload']).get('preserve_wsl_file_links',False)
    preserve_records=json.loads(job['payload']).get('preserve_native_link_records',False)
    if not isinstance(preserve_records,bool) or (preserve_records and preserve_links):raise ValueError('Invalid link record mode')
    if preserve_records and not str(source).startswith('/mnt/'):raise ValueError('Native link records require a Windows source')
    if not isinstance(preserve_links,bool):raise ValueError('Invalid native link preservation mode')
    if preserve_links and not str(source).startswith('/mnt/'):raise ValueError('Native link mode requires a Windows source')
    with store.db() as db:db.execute('UPDATE workspace_manifests SET result=NULL,updated=? WHERE job_id=?',(time.time(),ident))
    directory=store.state/'workspace-manifests'/ident
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    database=directory/'manifest.sqlite3'
    connection=sqlite3.connect(database)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.row_factory=sqlite3.Row
    connection.execute('CREATE TABLE IF NOT EXISTS entries(relative TEXT PRIMARY KEY,native TEXT NOT NULL,signature TEXT,sha256 TEXT,present INTEGER)')
    connection.execute('CREATE TABLE IF NOT EXISTS validation(relative TEXT PRIMARY KEY,native TEXT NOT NULL)')
    def progress(count,size,message):store.progress(ident,count,size,message)
    try:
        progress(0,0,'Recording full tree and native metadata; reparse points are never followed')
        initial=directory/'native-initial.jsonl'
        if preserve_records:enumerate_tree(source,initial,check,True)
        else:enumerate_tree(source,initial,check)
        connection.execute('UPDATE entries SET present=0')
        for rel,metadata in entries(initial):
            connection.execute('INSERT INTO entries(relative,native,present) VALUES(?,?,1) ON CONFLICT(relative) DO UPDATE SET native=excluded.native,present=1',(rel,canonical(metadata)))
        connection.execute('DELETE FROM entries WHERE present=0');connection.commit()
        if preserve_records:
            from .native_link_records import MAX_RECORDS, MAX_INVENTORY_BYTES
            entries_count,metadata_bytes=connection.execute('SELECT count(*),sum(length(CAST(relative AS BLOB))+length(CAST(native AS BLOB))+512) FROM entries').fetchone()
            if entries_count>MAX_RECORDS or metadata_bytes>MAX_INVENTORY_BYTES:raise ValueError('Native link record manifest exceeds bounded inventory budget')
        count=size=stream_count=stream_bytes=link_count=0;unsupported=[]
        # Stream rows in stable path order, without loading the tree into memory.
        for row in connection.execute('SELECT * FROM entries ORDER BY relative'):
            check();path=source/row['relative'];metadata=json.loads(row['native'])
            if metadata['kind']=='reparse' and preserve_records:
                from .native_link_records import decode_streams
                decoded=decode_streams(metadata.get('link_backup_streams'),row['relative']);link=decoded['link'];linux=decoded['linux_metadata']
                if metadata.get('streams')!=[] or not metadata.get('attributes',0)&1024 or metadata.get('attributes',0)&20480:raise ValueError('Unsupported inert link attributes')
                if not link['external']:
                    target=connection.execute('SELECT native FROM entries WHERE relative=?',(link['resolved_relative'],)).fetchone()
                    if target is None or json.loads(target[0])['kind'] not in ('file','dir'):raise ValueError('Internal link target must be a sealed direct file or directory')
                sig=file_signature(path)
                if not stat.S_ISLNK(sig['mode']) or sig['nlink']!=1 or os.readlink(path)!=link['target']:raise ValueError('Native link identity differs')
                if (sig['uid'],sig['gid'],sig['mode'])!=(linux['uid'],linux['gid'],linux['mode']):raise ValueError('Native link EA identity differs')
                if file_signature(path)!=sig:raise ValueError('Native link changed during capture')
                connection.execute('UPDATE entries SET signature=?,sha256=? WHERE relative=?',(canonical(sig),link['raw_sha256'],row['relative']))
                link_count+=1
                continue
            if metadata['kind']=='reparse' and preserve_links:
                from .native_reparse import decode_relative_file_link
                if metadata.get('reparse_additional_streams_absent') is not True or metadata.get('streams')!=[] or metadata.get('attributes',0)&(16|20480):raise ValueError('Native link stream or type eligibility is unverified')
                link=decode_relative_file_link(metadata.get('reparse_buffer_base64'),row['relative'])
                target=connection.execute('SELECT native FROM entries WHERE relative=?',(link['resolved_relative'],)).fetchone()
                if target is None or json.loads(target[0])['kind']!='file':raise ValueError('Native file link must resolve directly to a regular file inside the source')
                sig=file_signature(path)
                if not stat.S_ISLNK(sig['mode']) or sig['nlink']!=1 or os.readlink(path)!=link['target']:raise ValueError('WSL file link identity or target changed')
                if file_signature(path)!=sig:raise ValueError('WSL file link changed during reading')
                connection.execute('UPDATE entries SET signature=?,sha256=? WHERE relative=?',(canonical(sig),link['raw_sha256'],row['relative']))
                link_count+=1
                continue
            if metadata['kind'] in ('error','reparse','protected','special'):
                unsupported.append((row['relative'],metadata['kind']))
                continue
            sig=file_signature(path)
            if metadata['kind']=='file' and (sig['size']!=metadata['size'] or sig['mtime_ns']!=metadata['mtime_ns']):
                raise ValueError('File changed since native inventory: '+str(path))
            if metadata['kind']=='link' and not stat.S_ISLNK(sig['mode']):raise ValueError('Link type changed: '+str(path))
            if metadata['kind']=='dir' and not stat.S_ISDIR(sig['mode']):raise ValueError('Directory type changed: '+str(path))
            sha=row['sha256'] if row['signature']==canonical(sig) else None
            if metadata['kind']=='file':
                if sha is None:
                    # Hold only this read, so unrelated drives and reviews continue.
                    with store.lock_guard:
                        lock=store.drive_locks.setdefault(str(root),threading.Lock())
                    with lock:
                        check();sha=checked_hash(path,sig,check)
                count+=1;size+=sig['size']
            stream_count+=len(metadata.get('streams',[]))
            stream_bytes+=sum(s['size'] for s in metadata.get('streams',[]))
            connection.execute('UPDATE entries SET signature=?,sha256=? WHERE relative=?',(canonical(sig),sha,row['relative']))
            if count and count%50==0:
                connection.commit();progress(count,size,'Hashing every regular file, including ignored data and Git internals')
        connection.commit()
        progress(count,size,'Rechecking file identities, tree membership, permissions and named streams')
        final=directory/'native-final.jsonl'
        if preserve_records:enumerate_tree(source,final,check,True)
        else:enumerate_tree(source,final,check)
        connection.execute('DELETE FROM validation')
        for rel,metadata in entries(final):connection.execute('INSERT INTO validation VALUES(?,?)',(rel,canonical(metadata)))
        if connection.execute('SELECT 1 FROM entries e LEFT JOIN validation v USING(relative) WHERE v.relative IS NULL OR v.native!=e.native LIMIT 1').fetchone() or connection.execute('SELECT 1 FROM validation v LEFT JOIN entries e USING(relative) WHERE e.relative IS NULL LIMIT 1').fetchone():
            raise ValueError('Tree or native metadata changed during manifest generation; resume to capture a stable tree')
        sha=hashlib.sha256()
        for row in connection.execute('SELECT * FROM entries ORDER BY relative'):
            check()
            if row['signature'] and file_signature(source/row['relative'])!=json.loads(row['signature']):
                raise ValueError('File identity changed during final verification: '+row['relative'])
            sha.update(canonical(dict(relative=row['relative'],native=json.loads(row['native']),signature=json.loads(row['signature']) if row['signature'] else None,sha256=row['sha256'])).encode()+b'\n')
        connection.commit()
        if unsupported:raise ValueError(f'{len(unsupported)} inaccessible, protected, special or reparse entries need preservation review; first: {unsupported[0]}')
        result=dict(job=ident,source=str(source),manifest=str(database),sha256=sha.hexdigest(),files=count,bytes=size,
                    named_streams=stream_count,named_stream_bytes=stream_bytes,entries=connection.execute('SELECT count(*) FROM entries').fetchone()[0],
                    verified_at=time.time(),scope='full-visible-tree-manifest',source_retained=True,archive_copy_verified=False,
                    native_metadata=str(source).startswith('/mnt/'),
                    wsl_file_links=link_count if preserve_links else 0,preserve_wsl_file_links=preserve_links,
                    link_records=link_count if preserve_records else 0,preserve_native_link_records=preserve_records,
                    named_stream_scope='files-and-directories' if str(source).startswith('/mnt/') else 'posix-xattrs-and-links',
                    limitations=['A stable read-verified manifest is not an independent backup.',
                    'Windows SACL audit rules are not read; preserve them through native same-volume operations or privileged backup.',
                    'External Git object stores, linked worktrees and external LFS stores require dependency review.'])
        store.write_receipt(directory/'result.json',result)
        with store.db() as db:db.execute('UPDATE workspace_manifests SET result=?,updated=? WHERE job_id=?',(json.dumps(result),time.time(),ident))
        progress(count,size,'Full-tree manifest verified; archive copy and dependency review remain required')
    finally:connection.close()


def browse(store, ident, query=''):
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):
        raise ValueError('Invalid manifest identifier')
    with store.db() as db:
        row=db.execute('SELECT a.source,a.result,j.status FROM workspace_manifests a JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?',(ident,)).fetchone()
    if row is None:raise ValueError('Unknown manifest')
    database=store.state/'workspace-manifests'/ident/'manifest.sqlite3'
    if not database.exists():return dict(source=row['source'],complete=False,items=[])
    query=query[:200].replace('!','!!').replace('%','!%').replace('_','!_')
    try:
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
            rows=db.execute("SELECT relative,native,sha256 FROM entries WHERE relative LIKE ? ESCAPE '!' ORDER BY relative LIMIT 100",('%'+query+'%',)).fetchall()
    except sqlite3.OperationalError as exc:
        if row['status'] in ('pending','running'):
            return dict(source=row['source'],complete=False,items=[])
        raise ValueError('Manifest database is unavailable; preserve the original source') from exc
    return dict(source=row['source'],complete=row['status']=='completed' and row['result'] is not None,
                items=[dict(path=rel,kind=(metadata:=json.loads(raw))['kind'],size=metadata.get('size',0),sha256=sha,
                            streams=metadata.get('streams',[])) for rel,raw,sha in rows])


def compare(store,left,right):
    """Compare verified payloads, with bounded memory and bounded path samples."""
    if left==right:raise ValueError('Choose two different manifests')
    with store.db() as db:
        inputs=[]
        for ident in (left,right):
            row=db.execute("SELECT a.*,j.status FROM workspace_manifests a JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?",(ident,)).fetchone()
            if row is None or row['status']!='completed' or not row['result']:
                raise ValueError('Both manifests must have completed verification')
            inputs.append(dict(row,result=json.loads(row['result'])))
    connections=[]
    def items(ident):
        path=store.state/'workspace-manifests'/ident/'manifest.sqlite3'
        db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);connections.append(db)
        for rel,raw,sha in db.execute('SELECT relative,native,sha256 FROM entries ORDER BY relative'):
            if '.git' in Path(rel).parts:continue
            metadata=json.loads(raw)
            if metadata['kind']=='dir':continue
            if metadata['kind']=='file' and sha is None:raise ValueError('Manifest contains an unhashed regular file')
            yield rel,metadata,sha
    def payload(row):
        _,metadata,sha=row
        if metadata['kind']=='file':return canonical([sha,metadata.get('streams',[])])
        return canonical(metadata.get('target'))
    counts={key:0 for key in ('same_payload','different_payload','only_left','only_right','different_kind')}
    examples={key:[] for key in counts}
    def note(kind,path):
        counts[kind]+=1
        if len(examples[kind])<50:examples[kind].append(path)
    try:
        a,b=items(left),items(right);x,y=next(a,None),next(b,None)
        while x is not None or y is not None:
            if y is None or (x is not None and x[0]<y[0]):note('only_left',x[0]);x=next(a,None)
            elif x is None or y[0]<x[0]:note('only_right',y[0]);y=next(b,None)
            else:
                kind='different_kind' if x[1]['kind']!=y[1]['kind'] else 'same_payload' if payload(x)==payload(y) else 'different_payload'
                note(kind,x[0]);x,y=next(a,None),next(b,None)
    finally:
        for db in connections:db.close()
    result=dict(left=inputs[0]['source'],right=inputs[1]['source'],left_manifest=left,right_manifest=right,
                left_manifest_sha256=inputs[0]['result']['sha256'],right_manifest_sha256=inputs[1]['result']['sha256'],
                counts=counts,samples=examples,checked_at=time.time(),scope='working-tree payloads; Git internals excluded',
                metadata_equivalence_proven=False,retirement_authorized=False,
                limitations=['Matching payloads do not prove matching permissions, configuration or dependency closure.',
                             'Each manifest describes a verified point in time; revalidate before moving or retiring files.'])
    store.write_receipt(store.state/'workspace-comparisons'/(uuid.uuid4().hex+'.json'),result)
    return result


def comparisons(store):
    directory=store.state/'workspace-comparisons'
    paths=sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]
    fields=('left','right','left_manifest','right_manifest','counts','samples','checked_at','scope','retirement_authorized',
            'comparison_kind','manifest_digests_verified','all_recorded_payloads_equal','compared_metadata_equal','limitations',
            'named_stream_capture_scopes','directory_stream_capture_complete')
    return [{key:item.get(key) for key in fields} for path in paths for item in [json.loads(path.read_text())]]
