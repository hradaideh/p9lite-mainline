#!/usr/bin/env python3
"""Mainline, after p9disp-replay.py: restore the bootloader's display pipeline (from the fresh-boot dump:
MIF, MCTL, RCH_D0 reading the framebuffer at 0x0B000000, OVL0, DBUF0, DPP), paint test bands into the
framebuffer, flush through the MCTL mutex and push frames for SECONDS.
  p9fb-show.py DUMP [SECONDS]"""
import mmap, os, re, struct, sys, time
DSS, FB, W, H, STRIDE = 0xE8600000, 0x0B000000, 1080, 1920, 4320
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x80000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=DSS)
rd = lambda o: struct.unpack_from("<I", m, o)[0]
wr = lambda o, v: struct.pack_into("<I", m, o, v)
dump = {} if sys.argv[1] == "-" else {int(a, 16): int(v, 16) for a, v in (l.split() for l in open(sys.argv[1]) if re.match(r"^[0-9a-f]{8} [0-9a-f]{8}$", l.strip()))}
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120

fbm = mmap.mmap(fd, STRIDE * H, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=FB)
bands = [b"\x00\x00\xff\xff", b"\x00\xff\x00\xff", b"\xff\x00\x00\xff", b"\xff\xff\xff\xff"]   # BGRA: red green blue white
for i, px in enumerate(bands):
    row = px * W
    for y in range(i * H // 4, (i + 1) * H // 4):
        fbm[y * STRIDE:(y + 1) * STRIDE] = row
print("framebuffer painted: red / green / blue / white bands")

MCTL_SYS, CTL0, LDI = 0x10000, 0x10800, 0x7D000
if "--no-restore" in sys.argv:
    dump = {}
wr(CTL0 + 0x04, 1)                                          # MCTL_CTL_MUTEX lock
for lo, n in ((0xA000, 0x100), (0x10000, 0x200), (0x10800, 0x100), (0x50000, 0x200), (0x60000, 0x200),
              (0x6D000, 0x100), (0x70000, 0x200)):
    for o in range(lo, lo + n, 4):
        a = DSS + o
        if a in dump and o not in (CTL0 + 0x04, CTL0 + 0x08, CTL0 + 0x58):   # not mutex/status/clear
            wr(o, dump[a])
if dump:
    wr(0x70000 + 0x10, 0)                                   # DPP colour bar off
    wr(MCTL_SYS + 0x118, 1)                                 # MCTL_RCH6_FLUSH_EN (RCH_D0)
    wr(MCTL_SYS + 0x128, 1)                                 # MCTL_OV0_FLUSH_EN
wr(CTL0 + 0x04, 0)                                          # unlock -> shadow registers take effect
print("pipeline restored: RCH_D0 addr=%08x stride=%x OVL0 size=%08x MCTL_RCH_OV0_SEL=%08x" % (
    rd(0x50060), rd(0x50064), rd(0x6003c) if rd(0x6003c) else rd(0x60000), rd(MCTL_SYS + 0x180)))
wr(LDI + 0x44, 0)
t0, n, seen = time.time(), 0, {}
while time.time() - t0 < secs:
    wr(LDI + 0x48, 1); wr(LDI + 0x24, rd(LDI + 0x24) | 1); n += 1
    for _ in range(15):
        v = rd(LDI + 0x54); seen[v] = seen.get(v, 0) + 1; time.sleep(0.001)
print("frames: %d, LDI VSTATE histogram: %s, LDI INTS=%08x, DSI PHY_STATUS=%08x" % (
    n, {hex(k): c for k, c in seen.items()}, rd(LDI + 0x248), rd(0x10B0)))
