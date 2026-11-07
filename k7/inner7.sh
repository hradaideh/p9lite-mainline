#!/bin/sh
set -e
cd /k7/linux-7.3.1
export ARCH=arm64 CROSS_COMPILE=aarch64-alpine-linux-musl-
make O=/k7/out7 defconfig
for a in $(grep -oE '^CONFIG_ARCH_[A-Z0-9]+=y' /k7/out7/.config | cut -d= -f1 | sed 's/CONFIG_//'); do
  case $a in ARCH_HISI) ;; *) scripts/config --file /k7/out7/.config -d $a ;; esac
done
scripts/config --file /k7/out7/.config -e PSTORE -e PSTORE_RAM -e PSTORE_CONSOLE -e PSTORE_PMSG -d PSTORE_COMPRESS \
  --set-val PANIC_TIMEOUT 5 -e PRINTK_TIME -d DRM -d SOUND -d WLAN -d BT -d MEDIA_SUPPORT -d KVM -d VIRTUALIZATION \
  -e ARM_SP805_WATCHDOG -e SERIAL_AMBA_PL011 -e SERIAL_AMBA_PL011_CONSOLE -d MODULES
make O=/k7/out7 olddefconfig
grep -E '^CONFIG_(PSTORE_RAM|PSTORE_CONSOLE|PANIC_TIMEOUT|ARCH_HISI|RELOCATABLE|MODULES)=' /k7/out7/.config || true
echo "arch-count $(grep -cE '^CONFIG_ARCH_[A-Z0-9]+=y' /k7/out7/.config)"
make O=/k7/out7 -j8 Image
ls -la /k7/out7/arch/arm64/boot/Image
