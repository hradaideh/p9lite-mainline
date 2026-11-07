#!/usr/bin/env python3
# Draw three colour bands into the bootloader's DSS scanout buffer and push one frame
# to the command-mode panel (vendor single_frame_update: LDI_FRM_MSK_UP=1, LDI_CTRL bit0=1).
import mmap, os, struct
W, H, FB = 1080, 1920, 0x0B000000
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
fb = mmap.mmap(fd, W * H * 4, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=FB)
band = W * 4 * (H // 3)
for i, px in enumerate([0xFFFF0000, 0xFF00FF00, 0xFF0000FF]):  # as little-endian 0xAARRGGBB
    fb[i * band:(i + 1) * band] = struct.pack("<I", px) * (W * (H // 3))
dss = mmap.mmap(fd, 0x80000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0xE8600000)
L = 0x7D000
rd = lambda o: struct.unpack_from("<I", dss, o)[0]
wr = lambda o, v: struct.pack_into("<I", dss, o, v)
wr(L + 0x48, rd(L + 0x48) | 1)   # LDI_FRM_MSK_UP
wr(L + 0x24, rd(L + 0x24) | 1)   # LDI_CTRL: start one frame
print("pushed; LDI_CTRL=%08x FRM_MSK=%08x" % (rd(L + 0x24), rd(L + 0x44)))
