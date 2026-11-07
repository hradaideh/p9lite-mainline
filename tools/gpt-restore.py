#!/usr/bin/env python3
"""Rebuild the P9 lite eMMC primary GPT (sectors 1-33) from an `sfdisk -d` dump, keeping Huawei's
layout: last usable LBA = last disk sector (no room for a standard backup GPT, which sfdisk refuses).
  gpt-restore.py DUMP OUT        -> writes 33 sectors (header + 128 entries) to OUT
  gpt-restore.py --check FILE    -> parses a 34-sector image (LBA0-33) and prints the table
Sector 0 (protective MBR) is not produced; write OUT at byte offset 512 of the disk."""
import re, struct, sys, uuid, zlib

SECTOR, NENT, ESIZE = 512, 128, 128


def guid_bytes(s):
    return uuid.UUID(s).bytes_le


def parse_dump(path):
    hdr, parts = {}, []
    for line in open(path):
        m = re.match(r"(label-id|first-lba|last-lba): (\S+)", line)
        if m:
            hdr[m.group(1)] = m.group(2)
        m = re.match(r"/dev/\S+?p(\d+) : start=\s*(\d+), size=\s*(\d+), type=(\S+), uuid=(\S+), name=\"([^\"]*)\"", line)
        if m:
            n, st, sz, t, u, name = m.groups()
            parts.append((int(n), int(st), int(sz), t.rstrip(","), u.rstrip(","), name))
    return hdr, sorted(parts)


def build(hdr, parts):
    entries = bytearray(NENT * ESIZE)
    for n, st, sz, t, u, name in parts:
        e = guid_bytes(t) + guid_bytes(u) + struct.pack("<QQQ", st, st + sz - 1, 0)
        e += name.encode("utf-16-le").ljust(72, b"\0")
        entries[(n - 1) * ESIZE:n * ESIZE] = e
    last = int(hdr["last-lba"])
    h = bytearray(struct.pack("<8sIIIIQQQQ16sQIII", b"EFI PART", 0x00010000, 92, 0, 0,
                              1, last, int(hdr["first-lba"]), last, guid_bytes(hdr["label-id"]),
                              2, NENT, ESIZE, zlib.crc32(entries) & 0xFFFFFFFF))
    struct.pack_into("<I", h, 16, zlib.crc32(h) & 0xFFFFFFFF)
    return bytes(h.ljust(SECTOR, b"\0")) + bytes(entries)


def check(img):
    d = open(img, "rb").read()
    h = d[SECTOR:2 * SECTOR]
    sig, rev, hsz, crc = struct.unpack_from("<8sIII", h)
    hh = bytearray(h[:hsz]); struct.pack_into("<I", hh, 16, 0)
    assert sig == b"EFI PART" and zlib.crc32(hh) & 0xFFFFFFFF == crc, "header CRC"
    first, last = struct.unpack_from("<QQ", h, 40)
    disk = uuid.UUID(bytes_le=h[56:72])
    elba, n, esz, ecrc = struct.unpack_from("<QIII", h, 72)
    ents = d[elba * SECTOR:elba * SECTOR + n * esz]
    assert zlib.crc32(ents) & 0xFFFFFFFF == ecrc, "entries CRC"
    print("disk %s first %d last %d" % (str(disk).upper(), first, last))
    for i in range(n):
        e = ents[i * esz:(i + 1) * esz]
        if e[:16] == bytes(16):
            continue
        s, l, a = struct.unpack_from("<QQQ", e, 32)
        name = e[56:128].decode("utf-16-le").rstrip("\0")
        print("p%d start=%d size=%d uuid=%s name=%s" % (i + 1, s, l - s + 1, str(uuid.UUID(bytes_le=e[16:32])).upper(), name))


if __name__ == "__main__":
    if sys.argv[1] == "--check":
        check(sys.argv[2])
    else:
        hdr, parts = parse_dump(sys.argv[1])
        assert len(parts) == 49, len(parts)
        open(sys.argv[2], "wb").write(build(hdr, parts))
