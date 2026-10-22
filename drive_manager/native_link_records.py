"""Bounded legacy WSL metadata decoding. No filesystem access or link activation."""
import base64
import hashlib
import posixpath
import stat
import struct
from pathlib import PurePosixPath

MAX_RECORDS = 500000
MAX_INVENTORY_BYTES = 512 * 1024**2


def decode64(value):
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid metadata encoding') from exc
    if not raw or len(raw) > 16384:
        raise ValueError('Metadata outside bounded size')
    return raw


def decode_ea(encoded):
    raw = decode64(encoded)
    offset = 0
    values = {}
    while True:
        if offset + 8 > len(raw):
            raise ValueError('Truncated EA header')
        next_offset, flags, name_size, value_size = struct.unpack_from('<IBBH', raw, offset)
        end = offset + 8 + name_size + 1 + value_size
        if end > len(raw) or flags != 0 or value_size != 4:
            raise ValueError('Unsupported EA record')
        name = raw[offset + 8:offset + 8 + name_size]
        if name not in (b'$LXUID', b'$LXGID', b'$LXMOD') or name in values:
            raise ValueError('Unknown or duplicate EA')
        if raw[offset + 8 + name_size] != 0:
            raise ValueError('Unterminated EA name')
        values[name] = int.from_bytes(raw[end - 4:end], 'little')
        if next_offset == 0:
            if end != len(raw):
                raise ValueError('Trailing EA bytes')
            break
        if next_offset % 4 or next_offset < end - offset or offset + next_offset >= len(raw):
            raise ValueError('Invalid EA offset')
        if any(raw[end:offset + next_offset]):
            raise ValueError('Nonzero EA padding')
        offset += next_offset
    if set(values) != {b'$LXUID', b'$LXGID', b'$LXMOD'} or not stat.S_ISLNK(values[b'$LXMOD']):
        raise ValueError('Complete WSL link metadata required')
    return dict(uid=values[b'$LXUID'], gid=values[b'$LXGID'], mode=values[b'$LXMOD'], raw_sha256=hashlib.sha256(raw).hexdigest())


def decode_link(encoded, relative):
    if not isinstance(relative, str) or not relative or relative == '.':
        raise ValueError('Link path required')
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or str(path) != relative or any(c in relative for c in ('\\', ':', '\0')):
        raise ValueError('Noncanonical link path')
    raw = decode64(encoded)
    if len(raw) < 13 or raw[6:8] != b'\0\0' or len(raw) != 8 + int.from_bytes(raw[4:6], 'little'):
        raise ValueError('Unsupported reparse record')
    tag = int.from_bytes(raw[:4], 'little')
    if tag == 0xa000001d:
        if int.from_bytes(raw[8:12], 'little') != 2:
            raise ValueError('Unsupported WSL version')
        try:
            target = raw[12:].decode('utf8', errors='strict')
        except UnicodeDecodeError as exc:
            raise ValueError('Invalid target encoding') from exc
    elif tag == 0xa000000c:
        if len(raw) < 20:
            raise ValueError('Truncated Windows symlink')
        so, sl, po, pl, flags = struct.unpack_from('<HHHHI',raw,8)
        payload=raw[20:]
        if flags != 1 or any(x % 2 for x in (so,sl,po,pl)) or so+sl>len(payload) or po+pl>len(payload):
            raise ValueError('Unsupported Windows relative link')
        if set(range(so,so+sl)) | set(range(po,po+pl)) != set(range(len(payload))):
            raise ValueError('Unaccounted Windows link bytes')
        try:
            substitute=payload[so:so+sl].decode('utf-16le',errors='strict')
            printed=payload[po:po+pl].decode('utf-16le',errors='strict')
        except UnicodeDecodeError as exc:
            raise ValueError('Invalid Windows link target') from exc
        if substitute != printed or substitute.startswith(('\\','/')):
            raise ValueError('Windows target names differ or are absolute')
        target=substitute.replace('\\','/')
    else:
        raise ValueError('Unsupported link tag')
    if not target or any(c in target for c in ('\\', ':', '\0')) or target.startswith('//'):
        raise ValueError('Unsupported POSIX target')
    resolved = None if target.startswith('/') else posixpath.normpath(posixpath.join(str(path.parent), target))
    external = resolved is None or resolved == '..' or resolved.startswith('../')
    if resolved == relative:
        raise ValueError('Self-referential link')
    return dict(target=target, resolved_relative=resolved, external=external, activation_deferred=True, raw_sha256=hashlib.sha256(raw).hexdigest())


def decode_streams(streams, relative):
    if not isinstance(streams, list) or len(streams) != 2 or {x.get('id') for x in streams} != {2, 8}:
        raise ValueError('Exactly bounded EA and reparse streams required')
    decoded = {}
    for stream in streams:
        raw = decode64(stream.get('metadata_base64'))
        if stream.get('attributes') != 0 or stream.get('name') != '' or stream.get('size') != len(raw) or stream.get('metadata_sha256') != hashlib.sha256(raw).hexdigest():
            raise ValueError('Stream identity or payload differs')
        decoded[stream['id']] = stream['metadata_base64']
    return dict(link=decode_link(decoded[8], relative), linux_metadata=decode_ea(decoded[2]))
