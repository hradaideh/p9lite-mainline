#!/usr/bin/env python3
# Read the registers listed in p9regs.txt through /dev/mem (run as root on the phone).
import mmap, os, struct, sys
regs = [l.split() for l in open(sys.argv[1]) if l.strip() and not l.startswith('#')]
fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
for name, addr in regs:
    a = int(addr, 16)
    page = a & ~0xfff
    try:
        m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=page)
        v = struct.unpack('<I', m[a - page:a - page + 4])[0]
        m.close()
        print(f'{name} {addr} 0x{v:08X}')
    except Exception as e:
        print(f'{name} {addr} ERR {e}')
