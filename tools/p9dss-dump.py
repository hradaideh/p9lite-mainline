#!/usr/bin/env python3
"""Dump the display-path registers (DSS blocks the vendor hisifb programs, DSI0, PCTRL, CRG, SCTRL,
LCD pins) as 'addr value' lines, for diffing a working vendor-4.4 boot against mainline.
Read-only. Run as root on the phone:  p9dss-dump.py > dump.txt
A clock-gated block raises SIGBUS, so each range is read in a child process; failed ranges print
"# range <base> unreadable"."""
import mmap, os, struct, sys

DSS = 0xE8600000
RANGES = [  # (base, length)
    (DSS + 0x00000, 0x700),     # GLB: clock gates, resets, mem ctrl, int masks
    (DSS + 0x01000, 0x200),     # MIPI DSI0 host
    (DSS + 0x0A000, 0x100),     # MIF
    (DSS + 0x10000, 0x200),     # MCTL_SYS
    (DSS + 0x10800, 0x100),     # MCTL_CTL0
    (DSS + 0x50000, 0x200),     # RCH_D0 DMA + DFC
    (DSS + 0x60000, 0x200),     # OVL0
    (DSS + 0x6D000, 0x100),     # DBUF0
    (DSS + 0x70000, 0x200),     # DPP
    (DSS + 0x7D000, 0x300),     # LDI0
    (DSS + 0x7D800, 0x100),     # IFBC
    (0xE8A09000, 0x200),        # PCTRL (PERI_CTRL23/29/30/33: DSI PHY clocks)
    (0xFFF35000, 0x200),        # peri CRG
    (0xFFF0A000 + 0x160, 0x50), # SCTRL SCPEREN/STAT 0-3
    (0xE896C000, 0x228),        # pin mux
    (0xE896C800, 0x234),        # pin config
    (0xE8A0D000 + 0x3FC, 0x8),  # GPIO bank 2 data + dir (reset GPIO020, TE GPIO021)
]

fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
for base, length in RANGES:
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        page = base & ~0xFFF
        span = ((base + length - page + 0xFFF) & ~0xFFF)
        m = mmap.mmap(fd, span, mmap.MAP_SHARED, mmap.PROT_READ, offset=page)
        out = "".join("%08x %08x\n" % (a, struct.unpack_from("<I", m, a - page)[0])
                      for a in range(base, base + length, 4))
        os.write(w, out.encode()); os._exit(0)
    os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 65536)
        if not chunk:
            break
        data += chunk
    os.close(r)
    _, st = os.waitpid(pid, 0)
    sys.stdout.write(data.decode() if st == 0 else "# range %08x unreadable\n" % base)
