"""Read-only, no-atime inventory of a self-contained protected directory tree."""
import os,stat,hashlib,json,sys

def signature(s):
 return dict(device=s.st_dev,inode=s.st_ino,mode=s.st_mode,uid=s.st_uid,gid=s.st_gid,nlink=s.st_nlink,size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def xattrs(fd):return {n:os.getxattr(fd,n).hex() for n in sorted(os.listxattr(fd))}
def seal(root):
 records=[];root=os.path.abspath(root);rootfd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NOATIME)
 def visit(fd,rel):
  before=signature(os.fstat(fd));attrs=xattrs(fd)
  if before['device']!=os.fstat(rootfd).st_dev:raise ValueError('Cross-device entry: '+rel)
  if before['mode']&(stat.S_ISUID|stat.S_ISGID) or 'security.capability' in attrs:raise ValueError('Privileged executable metadata: '+rel)
  if stat.S_ISDIR(before['mode']):
   names=sorted(os.listdir(fd));records.append(dict(relative=rel,kind='dir',signature=before,xattrs=attrs,sha256=None))
   for name in names:
    childrel=name if rel=='.' else rel+'/'+name
    if name=='postmaster.pid' and rel=='.':raise ValueError('Database PID file present')
    entry=os.stat(name,dir_fd=fd,follow_symlinks=False)
    if not (stat.S_ISREG(entry.st_mode) or stat.S_ISDIR(entry.st_mode)):raise ValueError('Unsupported linked or special entry: '+childrel)
    child=os.open(name,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_NOATIME|(os.O_DIRECTORY if stat.S_ISDIR(entry.st_mode) else 0),dir_fd=fd)
    try:
     if signature(os.fstat(child))!=signature(entry):raise ValueError('Entry identity changed: '+childrel)
     visit(child,childrel)
    finally:os.close(child)
   if sorted(os.listdir(fd))!=names:raise ValueError('Directory membership changed: '+rel)
  elif stat.S_ISREG(before['mode']):
   if before['nlink']!=1:raise ValueError('Hardlinked file: '+rel)
   h=hashlib.sha256()
   while True:
    block=os.read(fd,1024*1024)
    if not block:break
    h.update(block)
   records.append(dict(relative=rel,kind='file',signature=before,xattrs=attrs,sha256=h.hexdigest()))
  else:raise ValueError('Unsupported entry: '+rel)
  if signature(os.fstat(fd))!=before or xattrs(fd)!=attrs:raise ValueError('Entry changed during read: '+rel)
 try:
  visit(rootfd,'.')
  # Reopen every recorded path without following links, checking identities and
  # directory membership after all payload reads have completed.
  for record in records:
   parts=[] if record['relative']=='.' else record['relative'].split('/')
   fd=os.dup(rootfd)
   try:
    for index,part in enumerate(parts):
     flags=os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_NOATIME
     if index<len(parts)-1 or record['kind']=='dir':flags|=os.O_DIRECTORY
     nxt=os.open(part,flags,dir_fd=fd);os.close(fd);fd=nxt
    if signature(os.fstat(fd))!=record['signature'] or xattrs(fd)!=record['xattrs']:raise ValueError('Entry changed after payload reads: '+record['relative'])
   finally:os.close(fd)
  if os.path.realpath(root)!=root or signature(os.stat(root,follow_symlinks=False))!=records[0]['signature']:raise ValueError('Source root changed or uses a symlink')
 finally:os.close(rootfd)
 return {'source':root,'scope':'full-protected-posix-tree','records':records,'source_written':False,'noatime_reads':True}
if __name__=='__main__':print(json.dumps(seal(sys.argv[1]),sort_keys=True,separators=(',',':')))
