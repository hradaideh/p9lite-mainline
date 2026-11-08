#!/usr/bin/env python3
"""Mark this boot successful for the Huawei boot-fail monitor: PMIC HRST_REG1 keypoint = 250, the same
write p9test/p9early does on mainline. After it, a crash or watchdog reset reboots normally instead of
counting as a boot failure (eRecovery)."""
import mmap, os, struct
REG = 0xFFF34630
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=REG & ~0xFFF)
o = REG & 0xFFF
before = struct.unpack_from("<I", m, o)[0]
struct.pack_into("<I", m, o, 250)
print("keypoint %d -> %d" % (before, struct.unpack_from("<I", m, o)[0]))
