#!/usr/bin/env python3
# Wake the BOE OTM1906C command-mode panel through the DSS MIPI DSI host (DesignWare) and push a frame.
# Backlight on this panel is BL_SET_BY_MIPI: DCS 0x51 brightness, 0x53 BCTRL.
import mmap, os, struct, sys, time
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
dss = mmap.mmap(fd, 0x80000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0xE8600000)
rd = lambda o: struct.unpack_from("<I", dss, o)[0]
wr = lambda o, v: struct.pack_into("<I", dss, o, v)
D, L = 0x1000, 0x7D000
print("DSI PWR_UP=%08x MODE=%08x CMD_MODE_CFG=%08x PHY_STATUS=%08x PKT=%08x" % (
    rd(D + 4), rd(D + 0x34), rd(D + 0x68), rd(D + 0xB0), rd(D + 0x74)))

def dcs(cmd, param=None):
    for _ in range(1000):                       # wait for gen command FIFO empty (bit0)
        if rd(D + 0x74) & 1:
            break
        time.sleep(0.001)
    if param is None:
        wr(D + 0x6C, 0x05 | cmd << 8)            # DCS short write, no parameter
    else:
        wr(D + 0x6C, 0x15 | cmd << 8 | param << 16)  # DCS short write, 1 parameter

level = int(sys.argv[1]) if len(sys.argv) > 1 else 0xFF
dcs(0x11); time.sleep(0.12)                     # exit sleep
dcs(0x29); time.sleep(0.02)                     # display on
dcs(0x53, 0x24)                                 # BCTRL on, backlight on
dcs(0x51, level)                                # brightness
time.sleep(0.02)
wr(L + 0x48, rd(L + 0x48) | 1)                  # LDI_FRM_MSK_UP
wr(L + 0x24, rd(L + 0x24) | 1)                  # one frame
print("sent; PKT=%08x brightness=%d" % (rd(D + 0x74), level))
