#!/usr/bin/env python3
"""Mainline: replay the vendor 4.4 hisifb power-on recorded by k44/p9iotrace.c
(k7/logs/iotrace-4.4-display-offon.txt), after the step 4.4 does on every power-off and mainline never
did: hold the DSI block in hardware reset (CRG PERRSTEN3 bit 28).
  p9disp-replay.py TRACE        -> replays, then prints DSI/LDI/panel state
Replayed: phase 6 (8.79-9.12 s: display clocks, GLB/LDI/pipeline init, panel reset pulses, DSI reset
release, DSI host + D-PHY init) and the panel on-commands (13.85-14.04 s). Not replayed: the first-frame
setup at 14.04 s (SMMU page tables + command lists in 4.4 memory), I2C/other drivers' CRG noise."""
import mmap, os, struct, subprocess, sys, time
sys.path.insert(0, "/home/user")
import p9panel_on as p
import p9lpm3

trace = [l.split() for l in open(sys.argv[1]) if not l.startswith("#")]
trace = [(int(t), int(a, 16), int(s), int(v, 16)) for t, a, s, v in trace]
WIN = [(8.79e6, 9.12e6), (13.85e6, 14042950)]   # through mipi_dsi_on_sub2 (HS + LPCLK_CTRL=3), before the first-frame SMMU/cmdlist
PANEL_PINS = {0x30, 0x44, 0x48, 0x54, 0x83c, 0x850, 0x854, 0x860}
CRG_KEEP = {0x00: 0x10000, 0x30: None, 0x50: None, 0xf0: None, 0xf8: None, 0x88: None}
def keep(a, v):
    if 0xE8600000 <= a < 0xE8680000:
        blk = (a - 0xE8600000) & ~0xfff
        if "--dsi-only" in sys.argv:          # keep the bootloader's pipeline (RCH/OVL/DBUF/MCTL/DPP) untouched
            return blk in (0x1000, 0x7D000) or (blk == 0 and a - 0xE8600000 in (0x100, 0x104, 0x108, 0x10c, 0x110))
        return blk not in (0x2000, 0x8000, 0xA000)   # cmdlist, SMMU, MIF
    if 0xE8A0D000 <= a < 0xE8A0E000 or a in (0xE8A09400, 0xE8A09404):        # GPIO bank 2 (panel), its lock
        return True
    if 0xE896C000 <= a < 0xE896D000:
        return a - 0xE896C000 in PANEL_PINS
    if 0xFFF35000 <= a < 0xFFF36000:
        o = a - 0xFFF35000
        return o in CRG_KEEP and (CRG_KEEP[o] is None or CRG_KEEP[o] == v)
    return a in (0xFFF0A258, 0xFFF0A170)
seq = [r for r in trace if any(lo <= r[0] <= hi for lo, hi in WIN) and keep(r[1], r[3])]
if "--hs-cmds" in sys.argv:
    # mainline: LP transmission does not drain, so blind-queued LP commands overflow the payload FIFO and
    # shift every later command onto the wrong data. Run mipi_dsi_on_sub2 (HS + clock lane) first.
    SUB2 = (14042907, 14042911)
    sub2 = [r for r in seq if SUB2[0] <= r[0] <= SUB2[1]]
    seq = [r for r in seq if not SUB2[0] <= r[0] <= SUB2[1]]
    first_cmd = min(r[0] for r in seq if r[1] in (0xE8601070, 0xE860106C) and r[0] > 13.8e6)
    seq += [(first_cmd - 100 + i, a, s_, v) for i, (t, a, s_, v) in enumerate(sub2)]
# panel rails: hi6522 (i2c-0, 0x6b) reg 0x11, as 4.4 does (decoded from the trace's I2C writes)
RAIL = 0xFFFFFFF0
if "--i2c-raw" in sys.argv:   # no i2c-dev (vendor 4.4): replay the vendor's own DesignWare I2C register writes
    # ... plus the I2C4 clock gate (CRG PEREN2/PERDIS2 bit 27) the vendor driver toggles around each transfer
    seq += [r for r in trace if 8.8185e6 <= r[0] <= 8.8315e6 and (0xFDF0D000 <= r[1] < 0xFDF0E000 or
            (r[1] in (0xFFF35020, 0xFFF35024) and r[3] == 1 << 27))]
else:
    seq += [(8819115, RAIL, 0, 0x04), (8825250, RAIL, 0, 0x06), (8830955, RAIL, 0, 0x07)]
LPM3_ON = 0xFFFFFFF1                         # dsssubsys on via LPM3, in the 0.76 ms gap 4.4 shows
seq += [(8802500, LPM3_ON, 0, 0)]
seq.sort(key=lambda e: e[0])
def rail(v):
    subprocess.run(["i2cset", "-f", "-y", I2C_BUS, "0x6b", "0x11", str(v)], check=True)
def rail_get(reg):
    return subprocess.run(["i2cget", "-f", "-y", I2C_BUS, "0x6b", str(reg)], capture_output=True, text=True).stdout.strip()

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
maps = {}
def mm(a):
    pg = a & ~0xFFF
    if pg not in maps:
        maps[pg] = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=pg)
    return maps[pg], a - pg
def w(a, v, size=4):
    m, o = mm(a)
    struct.pack_into({1: "<B", 2: "<H", 4: "<I"}[size], m, o, v)
def r(a):
    m, o = mm(a)
    return struct.unpack_from("<I", m, o)[0]

LDI = 0xE867D000
ON_ONLY = "--on-only" in sys.argv      # vendor 4.4 with p9-display stopped: hisifb already powered everything off
I2C_BUS = os.environ.get("P9_I2C_BUS", "0")
if ON_ONLY:
    print("on-only: display already off (hisifb), skipping state reads and the power-off half")
if not ON_ONLY:
  print("before: LDI VSTATE=%03x DSI PKT_STATUS=%08x PHY_STATUS=%08x" % (r(LDI + 0x54), r(0xE8601074), r(0xE86010B0)))
if not ON_ONLY:
 # 4.4 power-off tail: LDI off, PHY off, DSI block into hardware reset
 w(LDI + 0x44, 1); w(LDI + 0x24, r(LDI + 0x24) & ~1)
 w(0xE86010A0, 0)
 w(0xFFF35084, 1 << 28)
 print("hi6522 reg 0x11=%s 0x12=%s; panel rails off (06 -> 04 -> 00)" % (rail_get(0x11), rail_get(0x12)))
 for v in (0x06, 0x04, 0x00):
     rail(v); time.sleep(0.005)
 # 4.4 dpe_off tail (trace 5.306 s): inner clocks off, LPM3 powers the display subsystem off, bus clocks off.
 # No DSS register access from here until LPM3 has powered it back on.
 CRG = 0xFFF35000
 if "--no-lpm3" in sys.argv:                # keep the display domain powered: a power cycle makes MCTL/RCH secure-only
  time.sleep(0.5)
 else:
  w(CRG + 0x34, 1 << 29); w(CRG + 0x34, 1 << 28); w(CRG + 0x54, 1 << 28)   # D-PHY ref/cfg, pclk_dsi0 off
  w(CRG + 0x34, 1 << 15); w(CRG + 0xf0, 0x00400000)                       # clk_ldi0 off
  w(CRG + 0x34, 1 << 17); w(CRG + 0xf0, 0x01000000)                       # clk_edc0 off
  if not p9lpm3.send(0xc0101, 0x0b):
      raise SystemExit("LPM3 refused dsssubsys off - stopping before touching anything else")
  for dom in (0x09, 0x0a):                      # mmbuf, vivobus (reverse of the power-on order)
      p9lpm3.send(0xc0101, dom)
  w(CRG + 0x34, 1 << 12); w(CRG + 0x34, 1 << 13); w(0xFFF0A174, 1 << 24) # pclk/aclk_dss, MMBUF off
  print("display subsystem powered off (LPM3)")
  time.sleep(0.5)                               # let the panel discharge
print("DSI reset asserted, RSTSTAT3=%08x; replaying %d writes" % (r(0xFFF3508C), len(seq)))
prev = seq[0][0]
ncmd, pld = 0, []
for t, a, s, v in seq:
    gap = (t - prev) / 1e6
    if gap > 20e-6:
        time.sleep(min(gap, float(os.environ.get("P9_GAP_CAP", "0.2"))))
    prev = t
    if a == RAIL:
        rail(v); continue
    if a == LPM3_ON and "--no-lpm3" in sys.argv:
        continue
    if a == LPM3_ON:                          # 4.4 sends three, in this order (all-writes trace, mbx14)
        for dom, name in ((0x0a, "vivobus"), (0x0b, "dsssubsys"), (0x09, "mmbuf")):
            if not p9lpm3.send(0xc0001, dom):
                raise SystemExit("LPM3 refused %s on" % name)
        continue
    if a == 0xE8601070:
        pld.append(v)
    if a == 0xE860106C:                       # GEN_HDR: wait like the vendor (cmd FIFO not full)
        ncmd += 1
        for _ in range(500):
            if not r(0xE8601074) & 2:
                break
            time.sleep(0.0002)
    w(a, v, s)
    if a == 0xE860106C:
        t0 = time.time()
        while not (r(0xE8601074) & 1 and r(0xE8601074) & 4) and time.time() - t0 < 0.1:
            time.sleep(0.0002)
        st = r(0xE8601074)
        if not (st & 1 and st & 4) and ("--check" in sys.argv or "--hs-cmds" in sys.argv):
            print("STALL at panel cmd %d: hdr=%08x (dtype %02x len %d) pld=%s PKT_STATUS=%08x PHY_STATUS=%08x" % (
                ncmd, v, v & 0x3f, v >> 8 & 0xffff, [hex(x) for x in pld], st, r(0xE86010B0)))
            break
        pld = []
time.sleep(0.05)
print("after:  LDI VSTATE=%03x DSI PKT_STATUS=%08x PHY_STATUS=%08x INT_ST0=%08x INT_ST1=%08x RSTSTAT3=%08x" % (
    r(LDI + 0x54), r(0xE8601074), r(0xE86010B0), r(0xE86010BC), r(0xE86010C0), r(0xFFF3508C)))
for i in range(20):                       # queue should drain now that the HS clock runs
    if r(0xE8601074) & 1 and r(0xE8601074) & 4:
        break
    time.sleep(0.05)
print("FIFO drained" if r(0xE8601074) & 5 == 5 else "FIFO NOT drained", "PKT_STATUS=%08x" % r(0xE8601074))
print("panel: power mode 0x0A=%s signal 0x0E=%s brightness 0x52=%s" % (p.dcs_read(0x0A), p.dcs_read(0x0E), p.dcs_read(0x52)))
