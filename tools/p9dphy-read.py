#!/usr/bin/env python3
"""Read the DSI0 D-PHY test-code registers 0x00-0xFF (read-only: address latch only, no data clock).
  p9dphy-read.py          mainline (DSS clocks left on by the bootloader)
  p9dphy-read.py --live   vendor 4.4: push a frame and check the DSS/DSI gates before and after every
                          16 codes (hisifb idle-gates the clocks; a gated read hangs the SoC)
Prints 'code value' lines."""
import fcntl, mmap, os, struct, sys, time
DSI = 0xE8601000
TST0, TST1 = 0xB4, 0xB8
mem = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
dsi = mmap.mmap(mem, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=DSI)
crg = mmap.mmap(mem, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=0xFFF35000)
rd = lambda m, o: struct.unpack_from("<I", m, o)[0]
wr = lambda m, o, v: struct.pack_into("<I", m, o, v)
live = "--live" in sys.argv
if live:
    fb = os.open("/dev/fb0", os.O_RDWR)
    var = bytearray(160); fcntl.ioctl(fb, 0x4600, var)
def gates_on():
    return rd(crg, 0x3C) & 0x3000B000 == 0x3000B000 and rd(crg, 0x5C) & (1 << 28)   # + txdphy0 cfg/ref (bits 28/29)
def ready():
    if not live:
        return True
    for _ in range(50):
        fcntl.ioctl(fb, 0x4606, var)
        if gates_on():
            return True
        time.sleep(0.02)
    sys.exit("gates never on")
def code(a):
    wr(dsi, TST1, 0x10000 | a)    # testen + address
    wr(dsi, TST0, 2); wr(dsi, TST0, 0)   # testclk pulse latches the address
    v = (rd(dsi, TST1) >> 8) & 0xFF
    wr(dsi, TST1, 0)              # testen low, no clock: nothing written
    return v
saved1 = rd(dsi, TST1)
for a in range(0x100):
    ready()                      # live: a frame was just pushed and every gate reads on
    v = code(a)
    if live and not gates_on():
        sys.exit("gate dropped at code %02x" % a)
    print("%02x %02x" % (a, v), flush=True)
wr(dsi, TST1, saved1)
