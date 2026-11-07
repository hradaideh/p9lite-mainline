#!/usr/bin/env python3
# Pack a directory tree into a gzip newc initramfs (adds /dev/console). Usage: mkcpio.py <dir> <out.gz>
import gzip, os, stat, sys
ino = [100]
def entry(name, mode, data=b'', rdev=(0, 0)):
    ino[0] += 1
    n = name.encode() + b'\0'
    fields = (ino[0], mode, 0, 0, 1, 0, len(data), 0, 0, rdev[0], rdev[1], len(n), 0)
    out = b'070701' + b''.join(b'%08X' % v for v in fields) + n
    out += b'\0' * ((4 - len(out) % 4) % 4)
    out += data
    out += b'\0' * ((4 - len(out) % 4) % 4)
    return out
root, dst = sys.argv[1], sys.argv[2]
a = b''
for d, dirs, files in os.walk(root):
    dirs.sort(); files.sort()
    rel = os.path.relpath(d, root)
    if rel != '.':
        a += entry(rel, stat.S_IFDIR | 0o755)
    for f in files:
        p = os.path.join(d, f); r = os.path.normpath(os.path.join(rel, f))
        st = os.lstat(p)
        if stat.S_ISLNK(st.st_mode):
            a += entry(r, stat.S_IFLNK | 0o777, os.readlink(p).encode())
        else:
            a += entry(r, stat.S_IFREG | (st.st_mode & 0o777), open(p, 'rb').read())
if not os.path.exists(os.path.join(root, 'dev')):
    a += entry('dev', stat.S_IFDIR | 0o755)
a += entry('dev/console', stat.S_IFCHR | 0o600, rdev=(5, 1))
a += entry('TRAILER!!!', 0)
a += b'\0' * ((512 - len(a) % 512) % 512)
open(dst, 'wb').write(gzip.compress(a))
print('initramfs', len(a), 'bytes')
