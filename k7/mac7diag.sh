#!/bin/sh
# 7.3.1 diagnostic kernel = production + g_ether, into out7diag
set -e
cd /work/linux-7.3.1
export ARCH=arm64
O=/work/out7diag
rm -rf $O
make O=$O allnoconfig >/dev/null
scripts/kconfig/merge_config.sh -m -O $O $O/.config /work/p9min.config /work/p9wifi.config /work/p9prod.config /work/p9diag.config >/dev/null
make O=$O olddefconfig >/dev/null
echo "--- requested options that did not stick:"
cat /work/p9min.config /work/p9wifi.config /work/p9prod.config /work/p9diag.config | grep -E '^CONFIG_.*=y' | while read l; do grep -qx "$l" $O/.config || echo "  $l"; done
OUT=$O sh /work/kbuild.sh
make O=$O -j8 modules > /work/kbuild-modules.log 2>&1 || { tail -20 /work/kbuild-modules.log; exit 1; }
ls -la $O/arch/arm64/boot/Image $O/Module.symvers
