#!/usr/bin/env python3
"""Vendor 4.4 only: read ONE DSS block while hisifb has its clocks on.  p9dss-live.py BASE LEN (hex)
hisifb gates the DSS clocks when the command-mode panel is idle; reading a gated block hangs the SoC.
So: push a frame (FBIOPAN_DISPLAY, as p9-display does), confirm pclk_dss/aclk_dss/clk_ldi0 (PERSTAT3
bits 12/13/15) and pclk_dsi0 (PERSTAT5 bit 28) are on, then read. Never reads with a gate off."""
import fcntl, mmap, os, struct, sys, time
FBIOGET_VSCREENINFO, FBIOPAN_DISPLAY = 0x4600, 0x4606
base, length = int(sys.argv[1], 16), int(sys.argv[2], 16)
mem = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
crg = mmap.mmap(mem, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=0xFFF35000)
page = base & ~0xFFF
blk = mmap.mmap(mem, (base + length - page + 0xFFF) & ~0xFFF, mmap.MAP_SHARED, mmap.PROT_READ, offset=page)
rd = lambda m, o: struct.unpack_from("<I", m, o)[0]
fb = os.open("/dev/fb0", os.O_RDWR)
var = bytearray(160)
fcntl.ioctl(fb, FBIOGET_VSCREENINFO, var)
def gates_on():
    return rd(crg, 0x3C) & 0xB000 == 0xB000 and rd(crg, 0x5C) & (1 << 28)
for attempt in range(50):
    fcntl.ioctl(fb, FBIOPAN_DISPLAY, var)
    if gates_on():
        vals = [rd(blk, a - page) for a in range(base, base + length, 4)]
        if gates_on():          # still on after the read: values are trustworthy
            print("\n".join("%08x %08x" % (base + 4 * i, v) for i, v in enumerate(vals)))
            sys.exit(0)
    time.sleep(0.02)
sys.exit("gates never on (PERSTAT3=%08x PERSTAT5=%08x)" % (rd(crg, 0x3C), rd(crg, 0x5C)))
