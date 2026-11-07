#!/bin/sh
# usage: ct.sh NAME src...   (files or one dir)
NAME=$1; shift
P=/k7/port/$NAME; rm -rf $P; mkdir -p $P
if [ $# -eq 1 ] && [ -d /k7/vendor/$1 ]; then cp -r /k7/vendor/$1/. $P/; find $P -name Makefile -exec sed -i "s/obj-y/obj-m/g" {} +; else
  for f in "$@"; do cp /k7/vendor/$(dirname $f)/*.h $P/ 2>/dev/null; cp /k7/vendor/$f $P/; b=$(basename $f .c); echo "obj-m += $b.o" >> $P/Makefile; done; fi
cd /k7/linux-7.3.1
make O=/k7/out7 ARCH=arm64 CROSS_COMPILE=aarch64-alpine-linux-musl- M=$P -k -j8  KCFLAGS="-include /k7/shim/vendor_config.h -idirafter /k7/shim/include -I/k7/linux-7.3.1/drivers/mmc/host -I$P -idirafter /k7/vendor/drivers/hisi/include -Wno-error -w @/k7/shim/vdirs.flags"  $(cat /k7/shim/vendor_config.mk) $EXTRA modules > /k7/port/$NAME.log 2>&1
cc=$(grep -c ' CC \[M\]' /k7/port/$NAME.log); srcs=$(find $P -name '*.c' | wc -l)
errs=$(grep -c 'error:' /k7/port/$NAME.log); ef=$(grep 'error:' /k7/port/$NAME.log | cut -d: -f1 | sort -u | wc -l)
ok=$(find $P -name '*.o' ! -name '*.mod.o' | wc -l)
echo "$NAME: c-files=$srcs attempted=$cc compiled-ok=$ok files-with-errors=$ef error-lines=$errs"
