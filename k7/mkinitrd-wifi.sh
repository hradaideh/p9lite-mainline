#!/bin/sh
# Runs INSIDE p9build: proven USB test initrd (byte-for-byte, it holds a dev/console node the
# container cannot recreate) + an appended cpio with the Hi1102 modules and bring-up script.
set -e
T=/tmp/wifi-add; rm -rf $T; mkdir -p $T/p9 $T/bin $T/mnt/root; cd $T
cp /work/hi1102/hisi/platform/plat.ko /work/hi1102/hisi/wifi/wifi.ko p9/
cp /work/p9wifi.sh p9/p9wifi; chmod +x p9/p9wifi; ln -s /p9/p9wifi bin/p9wifi
find . | cpio -o -H newc 2>/dev/null | gzip -9 > /tmp/wifi-add.cpio.gz
cat /work/p9-initrd.gz /tmp/wifi-add.cpio.gz > /work/p9-wifi-initrd.gz
ls -la /work/p9-initrd.gz /work/p9-wifi-initrd.gz; sha256sum p9/*.ko
