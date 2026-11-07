#!/bin/sh
# Trimmed 7.3.1 build for the P9 Lite boot test: allnoconfig + p9min.config fragment
set -e
cd /work/linux-7.3.1
export ARCH=arm64
rm -rf /work/out7min
make O=/work/out7min allnoconfig
scripts/kconfig/merge_config.sh -m -O /work/out7min /work/out7min/.config /work/p9min.config
make O=/work/out7min olddefconfig
echo "--- requested options that did not stick:"
grep -E '^CONFIG_' /work/p9min.config | while read l; do grep -qx "$l" /work/out7min/.config || echo "  $l"; done
echo "BUILD_START $(date +%s)"
make O=/work/out7min -j8 Image
echo "BUILD_END $(date +%s)"
ls -la /work/out7min/arch/arm64/boot/Image
