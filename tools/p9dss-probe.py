#!/usr/bin/env python3
# Read-only probe of the hi6250 DSS state left by the bootloader (offsets: vendor soc_dss_interface.h).
import mmap, os, struct, sys
BASE, SIZE = 0xE8600000, 0x80000
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
m = mmap.mmap(fd, SIZE, mmap.MAP_SHARED, mmap.PROT_READ, offset=BASE)
r = lambda o: struct.unpack_from("<I", m, o)[0]
print("GLB_DSS_TAG   %08x" % r(0x318))
if len(sys.argv) > 1 and sys.argv[1] == "tag":
    sys.exit(0)
L = 0x7D000
for n, o in [("LDI_HRZ_CTRL1", 4), ("LDI_VRT_CTRL1", 0x10), ("LDI_CTRL", 0x24), ("LDI_FRM_MSK", 0x44)]:
    print("%-13s %08x" % (n, r(L + o)))
print("OVL0_SIZE     %08x" % r(0x60000))
print("MCTL_CTL0_EN  %08x" % r(0x10800))
for i in range(4):
    d = 0x50000 + i * 0x1000
    print("RCH_D%d ctrl=%08x addr0=%08x stride0=%08x oftx0=%08x ofty0=%08x" % (
        i, r(d + 0x1C), r(d + 0x60), r(d + 0x64), r(d + 0x0), r(d + 0x4)))
