#!/bin/sh
# Runs INSIDE the Mac podman container p9build.
# Builds a P9 Lite mainline test boot image from /work/out7min (or $OUT):
#   stubbed Image (2 MiB alignment) + /work/p9-initrd.gz + vendor mkbootimg offsets
# Usage: mkboot-test.sh [extra kernel cmdline]   -> /work/boot-test.img
set -e
OUT=${OUT:-/work/out7min}
python3 /work/mkstub.py $OUT/arch/arm64/boot/Image /work/Image-stub
CMD="ignore_loglevel printk.time=1 panic=1 rdinit=/init p9test.reboot_delay=${DELAY:-20} $*"
mkbootimg --kernel /work/Image-stub --ramdisk ${RAMDISK:-/work/p9-initrd.gz} --cmdline "$CMD" \
  --base 0x00478000 --kernel_offset 0x00008000 --ramdisk_offset 0x07b88000 \
  --second_offset 0x00e88000 --tags_offset 0x07588000 --pagesize 2048 -o ${IMG:-/work/boot-test.img}
ls -la ${IMG:-/work/boot-test.img}
