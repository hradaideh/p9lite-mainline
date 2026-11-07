#!/bin/sh
# Runs INSIDE the Mac podman container p9build.
# console=tty0: the bootloader appends console=ttyS0, which matches no UART on 7.x, so PID 1 got no
# /dev/console and pmOS init (setup_log: exec 3>&1) died -> "Attempted to kill init" -> reboot loop -> eRecovery.
# Production boot image: 7.3.1 (out7prod, stubbed for 2 MiB alignment) + r16's postmarketOS initramfs
# (used as-is, XZ; the kernel has the XZ decompressor)
# + r16's root UUIDs + p9test production mode.  -> /work/boot-prod.img
# Needs /work/r16-initramfs.xz (ramdisk of boot-r16-nft.img).
set -e
OUT=${OUT:-/work/out7prod}
python3 /work/mkstub.py $OUT/arch/arm64/boot/Image /work/Image-stub-prod
# keep r16 initramfs as XZ: the gzip re-pack is larger and did not boot
CMD="console=tty0 pmos_boot_uuid=515c41f5-9e9a-45f4-bcab-7d4d88780f5d pmos_root_uuid=ae796b76-c7ad-4d52-a7ef-e58daed65aca"
CMD="$CMD pmos_rootfsopts=defaults printk.time=1 panic=10 p9test.prod=1 p9test.sdio_prep=1 p9early $*"
mkbootimg --kernel /work/Image-stub-prod --ramdisk /work/r16-initramfs.xz --cmdline "$CMD" \
  --base 0x00478000 --kernel_offset 0x00008000 --ramdisk_offset 0x07b88000 \
  --second_offset 0x00e88000 --tags_offset 0x07588000 --pagesize 2048 -o ${IMG:-/work/boot-prod.img}
ls -la ${IMG:-/work/boot-prod.img}
