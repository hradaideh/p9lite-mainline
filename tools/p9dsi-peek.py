#!/usr/bin/env python3
"""Mainline: drain the DSI read FIFO (panel responses / ack-error reports) and query the panel with
DCS reads, without requiring the write-payload FIFO to be empty.  p9dsi-peek.py"""
import mmap, os, struct, time
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0xE8601000)
rd = lambda o: struct.unpack_from("<I", m, o)[0]
wr = lambda o, v: struct.pack_into("<I", m, o, v)
def drain(tag):
    words = []
    while not rd(0x74) & 0x10 and len(words) < 64:
        words.append(rd(0x70))
    print("%-12s PKT_STATUS=%08x read FIFO: %s" % (tag, rd(0x74), " ".join("%08x" % w for w in words) or "(empty)"))
    return words
drain("initial")
print("INT_ST0=%08x INT_ST1=%08x" % (rd(0xBC), rd(0xC0)))
for reg, name in ((0x0A, "power mode"), (0x0E, "signal mode"), (0x0F, "self-diag"), (0x52, "brightness"), (0xDA, "ID1")):
    for _ in range(200):
        if not rd(0x74) & 2:          # command FIFO not full
            break
        time.sleep(0.001)
    wr(0x6C, 0x37 | 1 << 8)           # max return packet size 1
    wr(0x6C, 0x06 | reg << 8)         # DCS read
    t0 = time.time()
    while rd(0x74) & 0x10 and time.time() - t0 < 0.2:
        time.sleep(0.001)
    w = drain("0x%02X %s" % (reg, name))
