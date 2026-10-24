"""Bounded named-stream preservation as sealed data, without native activation."""
import base64
import hashlib
import json
import os
from pathlib import PurePosixPath
import signal
import subprocess
import tempfile
import time

MAX_STREAM_BYTES = 16 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**2
MAX_STREAMS = 4096


def descriptors(entries):
    result=[];seen=set();total=0
    for relative,entry in entries.items():
        if not isinstance(relative,str):raise ValueError('Noncanonical stream owner path')
        path=PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or str(path)!=relative or any(x in relative for x in ('\\',':','\0')):
            raise ValueError('Noncanonical stream owner path')
        streams=entry['native'].get('streams')
        if not isinstance(streams,list):raise ValueError('Native stream inventory required')
        if streams and entry['native'].get('kind') not in ('file','dir'):raise ValueError('Stream owner must be a regular file or directory')
        for stream in streams:
            name=stream.get('name');size=stream.get('size');digest=stream.get('sha256')
            if not isinstance(name,str) or not name or len(name.encode('utf-16le'))>510 or any(x in name for x in ('\\','/',':','\0')):raise ValueError('Invalid native stream name')
            if type(size) is not int or not 0<=size<=MAX_STREAM_BYTES:raise ValueError('Native stream exceeds per-stream capture budget')
            if not isinstance(digest,str) or len(digest)!=64 or any(x not in '0123456789abcdef' for x in digest):raise ValueError('Native stream hash required')
            key=(relative.casefold(),name.casefold())
            if key in seen:raise ValueError('Duplicate or ambiguous native stream')
            seen.add(key);total+=size
            if len(seen)>MAX_STREAMS or total>MAX_TOTAL_BYTES:raise ValueError('Native streams exceed bounded capture budget')
            result.append(dict(relative=relative,name=name,size=size,sha256=digest))
    return sorted(result,key=lambda x:(x['relative'],x['name']))


def validate_payloads(entries,payloads):
    expected={(x['relative'],x['name']):x for x in descriptors(entries)}
    if not isinstance(payloads,list) or len(payloads)!=len(expected):raise ValueError('Native stream payload membership differs')
    seen=set()
    for item in payloads:
        if not isinstance(item,dict) or set(item)!={'relative','name','size','sha256','data_base64'}:raise ValueError('Unsupported native stream payload record')
        if not isinstance(item['relative'],str) or not isinstance(item['name'],str):raise ValueError('Invalid stream payload identity')
        if type(item['size']) is not int:raise ValueError('Invalid stream payload size')
        key=(item['relative'],item['name'])
        if key in seen or key not in expected:raise ValueError('Unexpected or duplicate native stream payload')
        seen.add(key);descriptor=expected[key]
        if any(item[k]!=v for k,v in descriptor.items()):raise ValueError('Native stream descriptor differs')
        encoded=item['data_base64']
        if not isinstance(encoded,str) or len(encoded)>4*((descriptor['size']+2)//3):raise ValueError('Native stream encoding exceeds its size')
        try:data=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError) as exc:raise ValueError('Invalid native stream payload encoding') from exc
        if len(data)!=descriptor['size'] or hashlib.sha256(data).hexdigest()!=descriptor['sha256']:raise ValueError('Native stream payload differs from sealed hash')
    return payloads


SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition @'
using System;using System.IO;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;
public static class NativeStreamPayload {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFile(string p,uint a,uint s,IntPtr sec,uint d,uint f,IntPtr t);
 public static string Read(string path,string name,long expected) {
  if(expected<0||expected>16777216||String.IsNullOrEmpty(name)||name.IndexOfAny(new char[]{'\\','/',':','\0'})>=0)throw new InvalidOperationException("Invalid bounded stream request");
  using(var h=CreateFile(path+":"+name,0x80000000,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
   if(h.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   using(var f=new FileStream(h,FileAccess.Read)) {
    if(f.Length!=expected)throw new InvalidOperationException("Native stream length changed");
    byte[] data=new byte[(int)expected];int offset=0;
    while(offset<data.Length){int count=f.Read(data,offset,data.Length-offset);if(count==0)throw new InvalidOperationException("Native stream ended early");offset+=count;}
    if(f.ReadByte()!=-1||f.Length!=expected)throw new InvalidOperationException("Native stream grew during reading");
    return Convert.ToBase64String(data);
   }
  }
 }
}
'@
while(($line=[Console]::ReadLine()) -ne $null){
 $x=ConvertFrom-Json $line
 $data=[NativeStreamPayload]::Read($x.path,$x.name,[int64]$x.size)
 [Console]::WriteLine((@{relative=$x.relative;name=$x.name;size=$x.size;sha256=$x.sha256;data_base64=$data}|ConvertTo-Json -Depth 4 -Compress))
}
'''


def capture(source,entries,check):
    from .models import windows_path
    rows=descriptors(entries)
    if not rows:return []
    check();started=time.monotonic()
    with tempfile.TemporaryFile() as requests,tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
        for row in rows:requests.write((json.dumps(dict(row,path=windows_path(source/row['relative'])),ensure_ascii=True)+'\n').encode())
        requests.seek(0)
        proc=subprocess.Popen(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-Command',SCRIPT],stdin=requests,stdout=output,stderr=errors,start_new_session=True)
        try:
            while proc.poll() is None:
                check()
                if time.monotonic()-started>300:raise ValueError('Bounded native stream capture timed out')
                time.sleep(.25)
            if proc.returncode:
                errors.seek(0);raise ValueError('Native stream capture failed: '+errors.read(1500).decode(errors='replace'))
            output.seek(0);payloads=[json.loads(line.decode('utf-8-sig')) for line in output]
            check();return validate_payloads(entries,payloads)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
