#!/usr/bin/env python3
"""Full power-on of the BOE OTM1906C command-mode panel on mainline, replaying the vendor 4.4
hw_lcd_on() (drivers/huawei_platform/lcd/hw_lcd_panel.c) over /dev/mem:
  reset GPIO020 H/L/H, LP-11 wait, reset H/L/H, the DT dss-on-cmds in DSI low-power mode,
  back to high-speed, brightness, then hardware-TE frames from the DSS LDI.
The rails (hi6522 ldo3/boost4/cpn1, WLED) are left on by the bootloader.
Without this the panel keeps the bootloader's state: it answers reads but ignores writes, its TE
line stays low and the LDI never starts a frame.
  p9panel-on.py [brightness 0-255]
STATUS (2026-11-07): work in progress. Reset + PHY clock + host reset work; long DSI packets still
never leave the payload FIFO (HS and LP), so the on-cmds stall at the first one. Next: replay the
vendor mipi_init (hisi_mipi_dsi.c: PHY reset, PLL/timing for 490 Mbit/s lanes) before sending."""
import mmap, os, struct, sys, time

DT = "/proc/device-tree/boe_otm1906c_5p2_1080p_cmd/"
GPIO2, RST_BIT = 0xE8A0D000, 4            # GPIO020 = bank 2 pin 4 (gpios[1] in the panel node)
PCTRL = 0xE8A09000                        # PERI_CTRL23 (0x60) bit 3: pctrl_dphytx_ulpsexit0 = DSI0 PHY ref/cfg clock
DSS, DSI, LDI = 0xE8600000, 0x1000, 0x7D000
CMD_MODE_LP, CMD_MODE_HS = 0x010F7F00, 0

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

def send(dtype, payload):
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
    dw(0x04, 0); time.sleep(0.002); dw(0x04, 1); time.sleep(0.005)
    dr(0xBC); dr(0xC0)                                          # clear DSI error status
    reset(1); ms(2); reset(0); ms(3); reset(1); ms(4)           # first reset pulse
    ms(7)                                                       # LP-11
    reset(1); ms(8); reset(0); ms(9); reset(1); ms(10)          # second reset pulse
    ms(11)                                                      # TP reset -> LCD init
    # The vendor sends these in low-power mode, but LP transmit never drains on this setup
    # (payload FIFO stays full, LP reads end in a protocol-violation error); HS works.
    dw(0x68, CMD_MODE_LP if os.environ.get("P9_LP") else CMD_MODE_HS)
    cmds = on_cmds()
    for dtype, payload, wait in cmds:
        send(dtype, payload)
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
