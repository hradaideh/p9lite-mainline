#!/usr/bin/env python3
"""Mainline: replay the vendor 4.4 ORDER. The bootloader hands over with the LDI mid-frame (VACTIVE0);
4.4 never inherits that - it resets the DSI host with the LDI stopped and sends long commands before
frames start. Test: LDI off -> wait IDLE -> DSI host + PHY reset -> long writes (0x51) with readback (0x52)."""
import sys, time
sys.path.insert(0, "/home/user")
import p9panel_on as p
LDI = p.LDI
ldi = lambda o: p.rd(p.dss, LDI + o)
def st(tag):
    print("%-10s VSTATE=%03x PKT_STATUS=%08x PHY_STATUS=%08x" % (tag, ldi(0x54), p.dr(0x74), p.dr(0xB0)))
st("before")
if "bit3" in sys.argv:                           # PERI_CTRL23 bit3: force D-PHY ref/cfg clock (needed on mainline for short writes)
    p.wr(p.pctrl, 0x60, p.rd(p.pctrl, 0x60) | 1 << 3)
p.wr(p.dss, LDI + 0x44, 1)                      # LDI_FRM_MSK: mask frames
p.wr(p.dss, LDI + 0x24, ldi(0x24) & ~1)         # LDI_CTRL bit0: LDI off
for _ in range(100):
    if ldi(0x54) == 1:
        break
    time.sleep(0.001)
st("ldi-off")
p.phy_restart()                                  # PWR_UP 0 -> PHY_RSTZ cycle -> lock/stopstate -> PWR_UP 1
p.dr(0xBC); p.dr(0xC0)                           # clear DSI error status
st("host-reset")
ok = 0
for val in (0x40, 0x90, 0x55, 0x66):
    p.dw(0x68, p.CMD_MODE_INIT)                  # long writes in LP, as the init list
    p.dw(0x70, 0x51 | val << 8); p.dw(0x6C, 0x39 | 2 << 8)
    t0 = time.time()
    while not (p.dr(0x74) & 4) and time.time() - t0 < 0.5:
        time.sleep(0.001)
    p.dw(0x68, p.CMD_MODE_HS)
    rb = p.dcs_read(0x52)
    ok += rb == [val]
    print("long write 0x51=%02x: FIFO %s in %3.0f ms, readback 0x52=%s" % (
        val, "empty" if p.dr(0x74) & 4 else "STUCK", (time.time() - t0) * 1000, rb))
st("after")
print("RESULT: %d/4 long writes landed" % ok)
