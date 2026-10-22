"""Strict decoding of bounded, relative WSL file-link records; no filesystem writes."""
import base64
import hashlib
import posixpath
from pathlib import PurePosixPath

def decode_relative_file_link(encoded, relative):
    if not isinstance(relative,str) or relative in ('','.'):raise ValueError('A file link path is required')
    path=PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or str(path)!=relative or any(c in relative for c in ('\\',':','\0')):
        raise ValueError('Noncanonical link path')
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError) as exc:raise ValueError('Invalid reparse encoding') from exc
    if len(raw)<13 or len(raw)>16384 or int.from_bytes(raw[:4],'little')!=0xa000001d:
        raise ValueError('Only bounded WSL file links are supported')
    if raw[6:8]!=b'\0\0' or len(raw)!=8+int.from_bytes(raw[4:6],'little') or int.from_bytes(raw[8:12],'little')!=2:
        raise ValueError('Unsupported or inconsistent WSL link record')
    try:target=raw[12:].decode('utf8',errors='strict')
    except UnicodeDecodeError as exc:raise ValueError('Invalid WSL link target') from exc
    if not target or target.startswith('/') or any(c in target for c in ('\\',':','\0')):
        raise ValueError('Only relative POSIX file targets are supported')
    resolved=posixpath.normpath(posixpath.join(str(path.parent),target))
    if resolved in ('.','..') or resolved.startswith('../') or resolved==relative:
        raise ValueError('Link target escapes its source tree or refers to itself')
    return {'target':target,'resolved_relative':resolved,'tag':'0xa000001d','version':2,'raw_sha256':hashlib.sha256(raw).hexdigest()}
