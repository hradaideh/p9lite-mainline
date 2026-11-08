#!/usr/bin/env python3
"""Mainline: does a frame stuck in LDI VACTIVE0 starve DSI generic long packets?
Stop the LDI, then send one DCS long write (brightness 0x51) and read it back (0x52)."""
import sys, time
sys.path.insert(0, "/home/user")
import p9panel_on as p   # tools/p9panel-on.py copied as p9panel_on.py
LDI = p.LDI
ldi = lambda o: p.rd(p.dss, LDI + o)
def st(tag):
    print("%-8s VSTATE=%03x PKT_STATUS=%08x PHY_STATUS=%08x" % (tag, ldi(0x54), p.dr(0x74), p.dr(0xB0)))
st("before")
p.wr(p.dss, LDI + 0x24, ldi(0x24) & ~1)        # LDI off
time.sleep(0.05); st("ldi-off")
for val in (0x40, 0x90):
    p.dw(0x68, p.CMD_MODE_INIT)                 # long writes in LP (as the init list)
    b = bytes([0x51, val]) + b"\0\0"
    p.dw(0x70, int.from_bytes(b, "little")); p.dw(0x6C, 0x39 | 2 << 8)
    t0 = time.time()
    while not (p.dr(0x74) & 4) and time.time() - t0 < 0.5:   # write-payload FIFO empty
        time.sleep(0.001)
    drained = p.dr(0x74) & 4
    p.dw(0x68, p.CMD_MODE_HS)
    print("long write 0x51=%02x: payload FIFO %s after %.0f ms; readback 0x52=%s" % (
        val, "empty" if drained else "STUCK", (time.time() - t0) * 1000, p.dcs_read(0x52)))
st("after")
