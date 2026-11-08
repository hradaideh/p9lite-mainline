#!/usr/bin/env python3
"""Mainline only (DSS clocks are on): show LDI0/DSI0 state; optionally stop the LDI.
  p9ldi-state.py            read-only
  p9ldi-state.py stop       LDI_CTRL bit0 = 0, then show state again"""
import mmap, os, struct, sys, time
DSS, LDI, DSI = 0xE8600000, 0x7D000, 0x1000
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x80000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=DSS)
rd = lambda o: struct.unpack_from("<I", m, o)[0]
wr = lambda o, v: struct.pack_into("<I", m, o, v)
VS = {1: "IDLE", 2: "VSW", 4: "VBP", 8: "VACTIVE0", 0x10: "VACT_SPACE", 0x20: "VACTIVE1", 0x40: "VFP",
      0x80: "WAIT_TE0", 0x100: "WAIT_TE1", 0x200: "WAIT_TE_EN"}
INT = ["FRM_START", "FRM_END", "UNFLOW", "VFP_END", "VSYNC", "VBP", "VFP", "VACT0_START", "VACT0_END",
       "VACT1_START", "VACT1_END", "TE1_PIN", "TE0_PIN", "DSI_TE_TRI"]
def show(tag):
    vs, ints = rd(LDI + 0x54), rd(LDI + 0x248)
    print("%-6s VSTATE=%03x %-10s HSTATE=%08x CTRL=%08x FRM_MSK=%x UP=%x INTS=%04x [%s]" % (
        tag, vs, VS.get(vs, "?"), rd(LDI + 0x58), rd(LDI + 0x24), rd(LDI + 0x44), rd(LDI + 0x48),
        ints, ",".join(n for i, n in enumerate(INT) if ints >> i & 1)))
    print("       DSI MODE_CFG=%08x CMD_MODE_CFG=%08x PKT_STATUS=%08x PHY_STATUS=%08x INT_ST0=%08x INT_ST1=%08x" % (
        rd(DSI + 0x34), rd(DSI + 0x68), rd(DSI + 0x74), rd(DSI + 0xB0), rd(DSI + 0xBC), rd(DSI + 0xC0)))
show("now")
time.sleep(0.2); show("+200ms")
if "stop" in sys.argv:
    wr(LDI + 0x24, rd(LDI + 0x24) & ~1)
    time.sleep(0.05); show("stop")
