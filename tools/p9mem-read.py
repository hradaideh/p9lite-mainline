#!/usr/bin/env python3
"""Read ONE physical register block as 'addr value' lines:  p9mem-read.py BASE LEN  (hex). Read-only."""
import mmap, os, struct, sys
base, length = int(sys.argv[1], 16), int(sys.argv[2], 16)
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
page = base & ~0xFFF
m = mmap.mmap(fd, (base + length - page + 0xFFF) & ~0xFFF, mmap.MAP_SHARED, mmap.PROT_READ, offset=page)
out = ["%08x %08x" % (a, struct.unpack_from("<I", m, a - page)[0]) for a in range(base, base + length, 4)]
print("\n".join(out))
