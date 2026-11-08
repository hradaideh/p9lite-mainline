#!/usr/bin/env python3
"""Mainline, after p9disp-replay.py: backlight on and push colour-bar frames for SECONDS (default 30).
DPP colour bar (DPP_CLRBAR_CTRL) needs no framebuffer; frames are triggered like the vendor
single_frame_update() for command-mode panels (LDI_FRM_MSK_UP=1, LDI_CTRL bit0=1)."""
import mmap, os, struct, subprocess, sys, time
DSS = 0xE8600000
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x80000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=DSS)
rd = lambda o: struct.unpack_from("<I", m, o)[0]
wr = lambda o, v: struct.pack_into("<I", m, o, v)
DSI, LDI, DPP = 0x1000, 0x7D000, 0x70000
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
subprocess.run(["i2cset", "-f", "-y", "0", "0x6b", "0x12", "0x14"], check=True)      # WLED on, as 4.4
for _ in range(200):
    if not rd(DSI + 0x74) & 2:
        break
    time.sleep(0.001)
wr(DSI + 0x6C, 0x15 | 0x51 << 8 | 0xFF << 16)                                    # DCS brightness 255 (HS)
wr(DPP + 0x10, 0x30000001)                                                       # colour bar on
wr(LDI + 0x44, 0)                                                                # frames unmasked
VS = {1: "IDLE", 4: "VBP", 8: "VACT0", 0x40: "VFP", 0x80: "WAIT_TE0", 0x200: "WAIT_TE_EN"}
seen, t0, n = {}, time.time(), 0
while time.time() - t0 < secs:
    wr(LDI + 0x48, 1)                                                            # LDI_FRM_MSK_UP
    wr(LDI + 0x24, rd(LDI + 0x24) | 1)                                           # LDI_CTRL: enable
    n += 1
    for _ in range(20):
        v = rd(LDI + 0x54)
        seen[v] = seen.get(v, 0) + 1
        time.sleep(0.001)
print("frames triggered: %d; LDI VSTATE seen: %s" % (n, {VS.get(k, hex(k)): c for k, c in seen.items()}))
print("LDI INTS=%08x DSI PKT_STATUS=%08x PHY_STATUS=%08x INT_ST0=%08x INT_ST1=%08x" % (
    rd(LDI + 0x248), rd(DSI + 0x74), rd(DSI + 0xB0), rd(DSI + 0xBC), rd(DSI + 0xC0)))
