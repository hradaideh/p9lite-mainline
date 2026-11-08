#!/usr/bin/env python3
"""Send a 2-word message to the LPM3 power MCU over HiIPCV230 mailbox 14, as the vendor
hisi_mailbox_dev.c does for RPROC_SYNC_SEND(HISI_RPROC_LPM3_MBX14) (manual ack).
  p9lpm3.py status                  read-only: mailbox 14 mode/source/data
  p9lpm3.py send W0 W1              e.g. dsssubsys on: 0xc0001 0x0b, off: 0xc0101 0x0b
Mailbox: base 0xE896B000, channel 14, src bit 1 (AP), dst bit 3 (LPM3), unlock key 0x1ACCE551."""
import mmap, os, struct, sys, time
BASE, CH, SRC, DST, KEY = 0xE896B000, 14, 1, 3, 0x1ACCE551
IDLE, ACK = 1 << 4, 1 << 7
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE)
rd = lambda o: struct.unpack_from("<I", m, o)[0]
wr = lambda o, v: struct.pack_into("<I", m, o, v & 0xFFFFFFFF)
MB = CH << 6
SOURCE, DSET, MODE, IMASK, ICLR, SEND, DATA = MB, MB + 4, MB + 0x10, MB + 0x14, MB + 0x18, MB + 0x1C, MB + 0x20

def status():
    return "mode=%08x source=%08x imask=%08x data=%08x %08x" % (rd(MODE), rd(SOURCE), rd(IMASK), rd(DATA), rd(DATA + 4))

def send(w0, w1, timeout=0.3):
    for _ in range(3):                                   # unlock the IPC block
        wr(0xA00, KEY)
        if rd(0xA00) == 0:
            break
        time.sleep(0.00001)
    else:
        raise SystemExit("IPC lock stays locked")
    for _ in range(100):                                 # occupy: wait idle, claim as source
        if rd(MODE) & IDLE:
            wr(SOURCE, 1 << SRC)
            if rd(SOURCE) & (1 << SRC):
                break
        time.sleep(0.001)
    else:
        raise SystemExit("mailbox 14 busy: " + status())
    wr(IMASK, ~0)
    wr(IMASK, rd(IMASK) & ~((1 << SRC) | (1 << DST)))   # manual ack: unmask src + dst
    wr(DSET, 1 << DST)
    wr(MODE, 0)                                           # NO_FUNC (manual ack)
    wr(DATA, w0); wr(DATA + 4, w1)
    wr(SEND, 1 << SRC)
    t0 = time.time()
    while not rd(MODE) & ACK and time.time() - t0 < timeout:
        time.sleep(0.0005)
    acked = bool(rd(MODE) & ACK)
    ack = (rd(DATA), rd(DATA + 4))
    wr(ICLR, 1 << SRC)                                    # clear our ack interrupt
    wr(IMASK, ~0); wr(SOURCE, 1 << SRC)                   # release (vendor hisi_mdev_release)
    ok = acked and ack[0] == w0 and (ack[1] >> 24) == 0
    print("send %08x %08x -> %s ack=%08x %08x after %.1f ms" % (w0, w1, "OK" if ok else "FAIL", ack[0], ack[1],
                                                           (time.time() - t0) * 1000))
    return ok

if __name__ == "__main__":
    if sys.argv[1] == "status":
        print(status())
    elif sys.argv[1] == "send":
        sys.exit(0 if send(int(sys.argv[2], 0), int(sys.argv[3], 0)) else 1)
