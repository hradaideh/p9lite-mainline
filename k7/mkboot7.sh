#!/bin/sh
# Build a RAM-boot test image of linux 7.3.1 for the P9 Lite (run inside the pmbootstrap native chroot)
set -e
cd /k7
python3 /k7/mkstub.py /k7/out7/arch/arm64/boot/Image /k7/Image7-stub
# empty initramfs (valid newc archive with only the trailer) -> kernel falls back to root mount -> panic
python3 - <<'PY'
import gzip
def hdr(name, mode=0, nlink=1):
    n = name.encode() + b'\0'
    h = b'070701' + b''.join(b'%08X' % v for v in (0, mode, 0, 0, nlink, 0, 0, 0, 0, 0, 0, len(n), 0))
    d = h + n
    return d + b'\0' * ((4 - len(d) % 4) % 4)
data = hdr('TRAILER!!!')
data += b'\0' * ((512 - len(data) % 512) % 512)
open('/k7/empty-initrd.gz', 'wb').write(gzip.compress(data))
PY
CMD="ignore_loglevel printk.time=1 panic=5 ramoops.mem_address=0x34800000 ramoops.mem_size=0x100000 ramoops.record_size=0x20000 ramoops.console_size=0x80000 ramoops.pmsg_size=0x20000"
mkbootimg --kernel /k7/Image7-stub --ramdisk /k7/empty-initrd.gz --cmdline "$CMD" \
  --base 0x00478000 --kernel_offset 0x00008000 --ramdisk_offset 0x07b88000 \
  --second_offset 0x00e88000 --tags_offset 0x07588000 --pagesize 2048 -o /k7/boot-7.3.1-test.img
ls -la /k7/boot-7.3.1-test.img
