#!/usr/bin/env python3
"""Full power-on of the BOE OTM1906C command-mode panel on mainline, replaying the vendor 4.4
hw_lcd_on() (drivers/huawei_platform/lcd/hw_lcd_panel.c) over /dev/mem:
  reset GPIO020 H/L/H, LP-11 wait, reset H/L/H, the DT dss-on-cmds in DSI low-power mode,
  back to high-speed, brightness, then hardware-TE frames from the DSS LDI.
The rails (hi6522 ldo3/boost4/cpn1, WLED) are left on by the bootloader.
Without this the panel keeps the bootloader's state: it answers reads but ignores writes, its TE
line stays low and the LDI never starts a frame.
  p9panel-on.py [brightness 0-255]

STATUS 2026-11-07: the panel resets, all 55 on-cmds go out and it reports power mode 0x9C with
backlight control on, but nothing is displayed. Findings:
  - bootloader leaves PCTRL PERI_CTRL23 bit 3 (DSI0 PHY ref/cfg clock) at 0: short writes are lost
    until it is set; with it set, short packets and reads work (HS).
  - long packets (0x29/0x39) are the blocker: data lane 0 leaves stop state mid-packet and hangs
    (PHY_STATUS bit 4 drops), in HS and LP, with or without auto clock lane, escape divider 7/14/28,
    HS write timeout off, LDI off, and with the vendor read-modify-write access pattern. After a PHY
    restart at most one long packet gets out, so this tool restarts the PHY before each one (enough
    for the init list, not for pixel data, which also travels as long packets).
  - verified equal to the vendor: PLL test codes (tc10=00 tc14=10 tc15=33 tc17=02 tc1d=05 @19.2 MHz),
    escape divider 7, every DSS/DSI clock gate (CRG PEREN3/5, SCTRL SCPEREN1), host timing registers,
    panel pinmux, per-lane D-PHY timing test codes (all 4 lanes: 3f 00 0e 09 09 09 03 04; clock lane
    00 19 0e 0a 1a 08), DSS pixel-clock gates (GLB_PXL0_* = single-DSI/no-IFBC table), DSS/DSI resets
    (all released), SCTRL DSS AXI/MMBUF clocks. The TE pin never toggles.
  - also ruled out: PCTRL PERI_CTRL24 (USB3 PHY only), escape divider 14/28, auto clock lane off.
  - the vendor takeover from the bootloader (dpe_set_fastboot / mipi_dsi_set_fastboot) only enables
    clocks and DSS-internal clock/memory selects; under 4.4 long writes worked after it.
  - PERI_CTRL23 bit 3 is a ULPS-exit PULSE in the vendor code (set, PHY_ULPS_CTRL=0xF, 1 ms,
    PHY_ULPS_CTRL=0, clear) - not a clock to keep on. With the proper pulse on a fresh boot, long
    packets are not lost but queue: the payload FIFO never reads empty again and packets are released
    late (brightness readback lags one write behind), about one per bus turnaround.
  - frames have a second blocker: TE never pulses on GPIO021, and with TE gating off (0x20040) the
    LDI still never starts a frame.
  - r16 (4.4) has no /dev/mem, no modules, no kprobes: a register diff needs a 4.4 build with
    CONFIG_DEVMEM (vendor tree in p9build /work/vendor, or the Deck pmbootstrap setup).
    Fresh 7.3.1 bootloader-state dump: k7/logs/dss-dump-7.3.1-fresh.txt (tools/p9dss-dump.py).
  - 2026-11-08 register diff, vendor 4.4 (working panel) vs 7.3.1 fresh: k7/logs/dss-dump-4.4-working.txt
    (captured with tools/p9dss-live.py: hisifb idle-gates the DSS clocks, and a blind read of a gated
    block hangs the SoC). DSI0 host config, LDI0 config, panel pinmux, PCTRL DSS bits and the display
    clock dividers are IDENTICAL. So static config is not the blocker; the difference is procedural.
  - CORRECTION: GPIO021 is muxed to function 2 (DSS TE input) on both kernels, so the GPIO data register
    never shows TE. "TE never toggles" above was a measurement error - judge TE from LDI status instead.
  - What does differ: pipeline routing. 4.4 feeds the LDI from another read channel (MCTL_CTL0 +0x14/+0x30
    = 1, MCTL_SYS +0x160 = 0x102, OVL0 layer size 077f0437, RCH_D0 idle); the bootloader/mainline state
    uses RCH_D0 (MCTL_CTL0 +0x48 = 1, MCTL_SYS +0x178 = 0x102). LDI VSTATE 4 (4.4) vs 8 (mainline).
  - Routing is not the problem: 4.4 happened to use RCH_V0 via the scaler; the bootloader's RCH_D0 -> OV0
    path is valid (it shows the logo).
  - On mainline the LDI sits in VSTATE 0x08 (VACTIVE0) from the first moment, horizontal state moving,
    while all DSI lanes stay in stop state: the frame started but no pixel (long) packet ever goes out.
    Pixels and init commands hit the same wall: the DSI host transmits no long payload.
  - Refuted 2026-11-08: "a frame stuck in VACTIVE0 starves generic long packets". With the LDI stopped
    (VSTATE -> IDLE) a DCS long write still does not take effect and the next one sticks in the payload
    FIFO (tools/p9ldi-abort-test.py). Also refuted: SCTRL MMBUF/DSS AXI clocks (mainline has more on).
  - Untested difference left: the D-PHY's internal test-code registers on a live 4.4 vs mainline (only
    compared against the vendor source values so far). Readable through PHY_TST_CTRL0/1 with the safe
    4.4 harness (tools/p9kp.py + gate-checked reads).
    Attempt 2026-11-08: tools/p9dphy-read.py read all 256 codes on mainline (k7/logs/dphy-7.3.1.txt), but on
    4.4 it hit SIGBUS and the SoC hung shortly after (keypoint 250 -> plain reboot, no eRecovery). Cause: the
    gate check covered DSS/LDI/pclk_dsi0 but not clk_txdphy0_cfg/ref (PERSTAT3 bits 28/29), which hisifb
    gates when idle and which the PHY test interface needs. Fixed in the tool; not retried yet. Pushing a
    frame may not keep the PHY cfg clock on long enough - check that first with CRG reads only.
  - 2026-11-08 structured pass, all refuted on mainline: LDI stopped then DSI host+PHY reset (with and
    without PERI_CTRL23 bit3), LDI/DSS routing, ULPS (all lanes in stop state, none in ULPS), D-PHY test
    codes (identical, all 4 lanes), PHY ref/cfg clocks (19.2 MHz crystal, gates on), pixel/core clocks
    (PPLL0 144/360 MHz both kernels), DSS GLB clock enables, PCTRL DSI bits, SCTRL MMBUF/AXI clocks.
    Static state is identical to working 4.4; the difference is in the power-on sequence itself (4.4
    power-cycles and re-inits DSS+DSI+panel in C with exact timing on every fb open), which register
    dumps cannot capture. Decision point: port the vendor hisifb power-on path (dpe_on -> mipi_dsi_on ->
    panel on -> single_frame_update) into the kernel, as was done for the Hi1102 Wi-Fi driver.
Next step needs lane-level visibility (logic analyser) or D-PHY escape-mode documentation, or
running the vendor 4.4 takeover and dumping every DSS/DSI register for a diff against 7.x.
"""
import mmap, os, struct, sys, time

DT = "/proc/device-tree/boe_otm1906c_5p2_1080p_cmd/"
GPIO2, RST_BIT = 0xE8A0D000, 4            # GPIO020 = bank 2 pin 4 (gpios[1] in the panel node)
PCTRL = 0xE8A09000                        # PERI_CTRL23 (0x60) bit 3: pctrl_dphytx_ulpsexit0 = DSI0 PHY ref/cfg clock
DSS, DSI, LDI = 0xE8600000, 0x1000, 0x7D000
CMD_MODE_LP, CMD_MODE_HS = 0x010F7F00, 0
# What works on this hardware: long packets (generic 0x29 / DCS 0x39) in low-power mode, short packets
# and reads in high-speed. All-LP stalls the short writes/reads; all-HS never sends a long payload.
CMD_MODE_INIT = 1 << 14 | 1 << 19                   # CMD_MODE_CFG gen_lw_tx | dcs_lw_tx

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
dss = mmap.mmap(fd, 0x80000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=DSS)
gpio = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=GPIO2)
pctrl = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=PCTRL)
rd = lambda m, o: struct.unpack_from("<I", m, o)[0]
wr = lambda m, o, v: struct.pack_into("<I", m, o, v)
dr = lambda o: rd(dss, DSI + o)
dw = lambda o, v: wr(dss, DSI + o, v)

def dt_cells(name):
    d = open(DT + name, "rb").read()
    return [struct.unpack_from(">I", d, i)[0] for i in range(0, len(d), 4)]

def reset(level):
    wr(gpio, 0x400, rd(gpio, 0x400) | 1 << RST_BIT)          # PL061 GPIODIR: output
    wr(gpio, (1 << RST_BIT) << 2, (1 << RST_BIT) if level else 0)

def fifo_ready():
    for _ in range(2000):
        st = dr(0x74)
        if st & 1 and st & 4:                                 # cmd FIFO and write-payload FIFO empty
            return
        time.sleep(0.0005)
    raise SystemExit("DSI command FIFO stuck, PKT_STATUS=%08x" % dr(0x74))

def phy_restart():
    """PHY_RSTZ 0 -> 7, wait for PLL lock and 4-lane stop state (vendor mipi_init, PLL settings kept)."""
    mode = dr(0x68)
    dw(0x04, 0); dw(0xA0, 0); time.sleep(0.001); dw(0xA0, 7)
    for _ in range(500):
        st = dr(0xB0)
        if st & 1 and st & 0xA90 == 0xA90:
            break
        time.sleep(0.0005)
    dw(0x04, 1); time.sleep(0.001); dw(0x68, mode)

def send(dtype, payload):
    if dtype not in (0x05, 0x15, 0x03, 0x13, 0x23):
        # ponytail: after a PHY restart the DSI host transmits exactly one long packet and then stalls
        # (cause unknown: PLL, clocks and host config all match the vendor). Restart before each one.
        phy_restart()
    fifo_ready()
    if dtype in (0x05, 0x15, 0x03, 0x13, 0x23):               # short packets: data in the header
        p = list(payload) + [0, 0]
        dw(0x6C, dtype | p[0] << 8 | p[1] << 16)
    else:                                                      # long packets: payload FIFO, then header
        b = bytes(payload) + b"\0" * (-len(payload) % 4)
        for i in range(0, len(b), 4):
            dw(0x70, struct.unpack_from("<I", b, i)[0])
        dw(0x6C, dtype | len(payload) << 8)

def dcs_read(reg, n=1):
    fifo_ready(); dw(0x6C, 0x37 | n << 8)
    fifo_ready(); dw(0x6C, 0x06 | reg << 8)
    for _ in range(300):
        st = dr(0x74)
        if not st & 0x40 and not st & 0x10:
            v = dr(0x70)
            while not dr(0x74) & 0x10:
                dr(0x70)
            return [(v >> 8 * i) & 0xFF for i in range(n)]
        time.sleep(0.001)
    return None

def on_cmds():
    b = [c & 0xFF for c in dt_cells("hisilicon,dss-on-cmds")]
    i, out = 0, []
    while i + 5 <= len(b):
        dtype, _vc, wait, wtype, dlen = b[i:i + 5]
        out.append((dtype, b[i + 5:i + 5 + dlen], wait / 1000.0 if wtype else wait / 1e6))
        i += 5 + dlen
    return out

def main():
    level = int(sys.argv[1]) if len(sys.argv) > 1 else 0x66     # dss-panel-bl-def
    seq = dt_cells("power-on-sequence")                         # VCI IOVCC R1H R1L R1H VSP VSN LP11 R2H R2L R2H TP2INIT BL
    ms = lambda i: time.sleep(seq[i] / 1000.0)
    # The bootloader leaves the DSI0 PHY with its ref/cfg clock off (as for ULPS): reads still come
    # back, but every write is lost and long-packet payload sticks in the FIFO. Clock on, then reset
    # the DSI host core to flush whatever is stuck.
    wr(pctrl, 0x60, rd(pctrl, 0x60) | 1 << 3)
    phy_restart()
    dr(0xBC); dr(0xC0)                                          # clear DSI error status
    reset(1); ms(2); reset(0); ms(3); reset(1); ms(4)           # first reset pulse
    ms(7)                                                       # LP-11
    reset(1); ms(8); reset(0); ms(9); reset(1); ms(10)          # second reset pulse
    ms(11)                                                      # TP reset -> LCD init
    dw(0x68, CMD_MODE_INIT)
    cmds = on_cmds()
    for n, (dtype, payload, wait) in enumerate(cmds):
        try:
            send(dtype, payload)
        except SystemExit as e:
            raise SystemExit("%s at on-cmd %d/%d: dtype %02x %s" % (e, n + 1, len(cmds), dtype,
                                                                   " ".join("%02x" % x for x in payload)))
        time.sleep(wait)
    fifo_ready()
    dw(0x68, CMD_MODE_HS)
    send(0x15, [0x51, level])
    err0, err1 = dr(0xBC), dr(0xC0)
    # DSS: hardware TE from the panel, frames unmasked, push one
    wr(dss, LDI + 0x34, 0x20041)
    wr(dss, LDI + 0x44, 0)
    wr(dss, LDI + 0x48, 1)
    wr(dss, LDI + 0x24, rd(dss, LDI + 0x24) | 1)
    time.sleep(0.1)
    te = [(rd(gpio, 0x3FC) >> 5) & 1 for _ in range(20000)]
    print("sent %d on-cmds; DSI INT_ST0=%08x INT_ST1=%08x" % (len(cmds), err0, err1))
    print("power mode 0x0A=%s signal 0x0E=%s brightness 0x52=%s" % (dcs_read(0x0A), dcs_read(0x0E), dcs_read(0x52)))
    print("TE pin GPIO021: %d transitions in %d samples" % (sum(a != b for a, b in zip(te, te[1:])), len(te)))
    print("LDI VSTATE=%08x INTS=%08x" % (rd(dss, LDI + 0x54), rd(dss, LDI + 0x248)))

if __name__ == "__main__":
    main()
