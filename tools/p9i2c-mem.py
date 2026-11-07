#!/usr/bin/env python3
"""Userspace DesignWare I2C master over /dev/mem (hi6250 i2c4 @ 0xFDF0D000, left configured by the
bootloader). Diagnostic only; the kernel driver (i2c-designware + i2c-dev) is the production path.
  p9i2c-mem.py check                  CRG reset state + controller ID
  p9i2c-mem.py get <addr> <reg> [n]   read n registers
  p9i2c-mem.py set <addr> <reg> <val> write one register"""
import mmap, os, struct, sys, time
CRG, I2C, RSTBIT = 0xFFF35000, 0xFDF0D000, 27
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
crg = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=CRG)
rc = lambda o: struct.unpack_from("<I", crg, o)[0]
in_reset = (rc(0x80) >> RSTBIT) & 1
if not (rc(0x2C) >> 27) & 1:                    # PERSTAT2: clk_i2c4 gated -> PEREN2 bit 27
    struct.pack_into("<I", crg, 0x20, 1 << 27); time.sleep(0.001)
if sys.argv[1] == "check":
    print("CRG rst_stat(0x80)=%08x i2c4 %s" % (rc(0x80), "IN RESET" if in_reset else "out of reset"))
    if in_reset:
        sys.exit(1)
i2c = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=I2C)
r = lambda o: struct.unpack_from("<I", i2c, o)[0]
w = lambda o, v: struct.pack_into("<I", i2c, o, v)
if sys.argv[1] == "check":
    print("COMP_TYPE=%08x VERSION=%08x PARAM1=%08x CON=%08x ENABLE=%08x STATUS=%08x SS_H/L=%d/%d FS_H/L=%d/%d" % (
        r(0xFC), r(0xF8), r(0xF4), r(0x00), r(0x6C), r(0x70), r(0x14), r(0x18), r(0x1C), r(0x20)))
    sys.exit(0)

def setup(addr):
    w(0x6C, 0)
    for _ in range(100):
        if not r(0x9C) & 1: break
        time.sleep(0.001)
    w(0x04, addr)
    w(0x6C, 1)

def wait(cond, what):
    for _ in range(500):
        if r(0x34) & 0x40:                      # TX_ABRT
            src = r(0x80); r(0x54)
            raise SystemExit("abort (%s) src=%08x" % (what, src))
        if cond(): return
        time.sleep(0.0005)
    raise SystemExit("timeout (%s) status=%08x" % (what, r(0x70)))

def get(addr, reg, n=1):
    setup(addr); out = []
    for i in range(n):
        w(0x10, (reg + i) & 0xFF)               # register pointer
        w(0x10, 0x100 | 0x200)                  # read + STOP
        wait(lambda: r(0x78) > 0, "read")
        out.append(r(0x10) & 0xFF)
    return out

def set_(addr, reg, val):
    setup(addr)
    w(0x10, reg & 0xFF)
    w(0x10, (val & 0xFF) | 0x200)               # write + STOP
    wait(lambda: r(0x70) & 0x4 and not r(0x70) & 0x20, "write")   # TFE and not ACTIVITY

a = int(sys.argv[2], 0); g = int(sys.argv[3], 0)
if sys.argv[1] == "get":
    n = int(sys.argv[4], 0) if len(sys.argv) > 4 else 1
    print(" ".join("%02x:%02x" % (g + i, v) for i, v in enumerate(get(a, g, n))))
else:
    set_(a, g, int(sys.argv[4], 0)); print("ok %02x <- %02x; now %02x" % (g, int(sys.argv[4], 0), get(a, g)[0]))
