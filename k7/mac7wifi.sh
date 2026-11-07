#!/bin/sh
# 7.3.1 boot kernel + Wi-Fi prerequisites, built into out7wifi (out7min stays the last-tested build)
set -e
cd /work/linux-7.3.1
export ARCH=arm64
O=/work/out7wifi
rm -rf $O
make O=$O allnoconfig >/dev/null
scripts/kconfig/merge_config.sh -m -O $O $O/.config /work/p9min.config /work/p9wifi.config >/dev/null
make O=$O olddefconfig >/dev/null
echo "--- requested options that did not stick:"
cat /work/p9min.config /work/p9wifi.config | grep -E '^CONFIG_.*=y' | while read l; do grep -qx "$l" $O/.config || echo "  $l"; done
OUT=$O sh /work/kbuild.sh
make O=$O -j8 modules > /work/kbuild-modules.log 2>&1 || { tail -20 /work/kbuild-modules.log; exit 1; }
ls -la $O/arch/arm64/boot/Image $O/Module.symvers
