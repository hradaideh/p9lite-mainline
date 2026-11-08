#!/usr/bin/env python3
"""Dump the always-on control blocks, one block per child process (a faulting block only loses itself):
SCTRL 0x800, PCTRL 0xc00, peri CRG 0xd00 (the ranges the vendor rdr crash dumper reads), PMCTRL 0x400,
PMU SSI 0x1000 (hi6555 PMIC registers, 4-byte stride). Read-only.  p9aon-dump.py > dump.txt"""
import mmap, os, struct, sys
R = [(0xFFF0A000, 0x800), (0xE8A09000, 0xC00), (0xFFF35000, 0xD00), (0xFFF31000, 0x400), (0xFFF34000, 0x1000)]
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
for base, n in R:
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        m = mmap.mmap(fd, n, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
        os.write(w, "".join("%08x %08x\n" % (base + o, struct.unpack_from("<I", m, o)[0]) for o in range(0, n, 4)).encode())
        os._exit(0)
    os.close(w)
    data = b""
    while True:
        c = os.read(r, 65536)
        if not c:
            break
        data += c
    _, st = os.waitpid(pid, 0)
    sys.stdout.write(data.decode() if st == 0 else "# %08x unreadable\n" % base)
    sys.stdout.flush()
