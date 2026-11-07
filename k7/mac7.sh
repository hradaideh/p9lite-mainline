#!/bin/sh
# Native arm64 build of linux 7.3.1 with the same config as the Deck test (~/k7/inner7.sh)
set -e
cd /work
[ -d linux-7.3.1 ] || { curl -sSL -o linux-7.3.1.tar.xz https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.3.1.tar.xz; tar xJf linux-7.3.1.tar.xz; }
cd linux-7.3.1
export ARCH=arm64
make O=/work/out7 defconfig
for a in $(grep -oE '^CONFIG_ARCH_[A-Z0-9]+=y' /work/out7/.config | cut -d= -f1 | sed 's/CONFIG_//'); do
  case $a in ARCH_HISI) ;; *) scripts/config --file /work/out7/.config -d $a ;; esac
done
scripts/config --file /work/out7/.config -e PSTORE -e PSTORE_RAM -e PSTORE_CONSOLE -e PSTORE_PMSG -d PSTORE_COMPRESS \
  --set-val PANIC_TIMEOUT 5 -e PRINTK_TIME -d DRM -d SOUND -d WLAN -d BT -d MEDIA_SUPPORT -d KVM -d VIRTUALIZATION \
  -e ARM_SP805_WATCHDOG -e SERIAL_AMBA_PL011 -e SERIAL_AMBA_PL011_CONSOLE -d MODULES
make O=/work/out7 olddefconfig
echo "BUILD_START $(date +%s)"
make O=/work/out7 -j8 Image
echo "BUILD_END $(date +%s)"
ls -la /work/out7/arch/arm64/boot/Image
