#!/bin/sh
# P9 Lite mainline test boot image: stubbed Image + tiny initramfs (runs inside pmbootstrap native chroot)
set -e
cd /k7
python3 /k7/mkstub.py /k7/Image7t /k7/Image7t-stub
CMD="ignore_loglevel printk.time=1 panic=1 rdinit=/init p9test.reboot_delay=20 ramoops.mem_address=0x34800000 ramoops.mem_size=0x100000 ramoops.record_size=0x20000 ramoops.console_size=0x80000 ramoops.pmsg_size=0x20000"
mkbootimg --kernel /k7/Image7t-stub --ramdisk /k7/p9-initrd.gz --cmdline "$CMD" \
  --base 0x00478000 --kernel_offset 0x00008000 --ramdisk_offset 0x07b88000 \
  --second_offset 0x00e88000 --tags_offset 0x07588000 --pagesize 2048 -o /k7/boot-7.3.1-t.img
ls -la /k7/boot-7.3.1-t.img
